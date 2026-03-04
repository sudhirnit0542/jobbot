"""
JobBot LangGraph Agent
Fallback chain: Groq 70B → Gemini → Zhipu GLM → Groq 8B
"""

from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from typing import TypedDict, Annotated, Sequence
from loguru import logger
import operator
import asyncio

from agent.tools.job_search import search_jobs, fetch_full_jd
from agent.tools.matcher import analyse_jd, match_candidate_to_jd
from agent.tools.resume_builder import build_resume
from agent.tools.applicator import apply_to_job
from agent.tools.repository import (
    save_job_to_repo, save_resume_to_repo, record_application,
    save_portal_credentials, get_portal_credentials,
    check_already_applied, get_application_dashboard
)
from config import get_settings

settings = get_settings()

APPLY_SYSTEM_PROMPT = """You are JobBot — apply to pre-matched jobs for a candidate.

For each job in the list:
1. check_already_applied — skip if true
2. get_portal_credentials — get existing account if any
3. build_resume — create tailored PDF using candidate profile + JD
4. apply_to_job — submit application
5. If new account was created → save_portal_credentials
6. record_application — log APPLIED or FAILED
7. save_resume_to_repo — save resume record

IMPORTANT: Always use the full UUID from build_resume result as resume_id.
Report each job: ✅ Applied | ❌ Failed | ⏭ Already applied"""

ALL_TOOLS = [
    fetch_full_jd,
    analyse_jd,
    match_candidate_to_jd,
    build_resume,
    apply_to_job,
    save_job_to_repo,
    save_resume_to_repo,
    record_application,
    save_portal_credentials,
    get_portal_credentials,
    check_already_applied,
    get_application_dashboard,
]


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]


def is_rate_limit_error(error: Exception, rate_limit_errors: list[str]) -> bool:
    """Check if error is a rate limit or decommissioned model error."""
    error_str = str(error).lower()
    if "decommissioned" in error_str or "no longer supported" in error_str:
        return True
    return any(indicator.lower() in error_str for indicator in rate_limit_errors)


# ─── FallbackLLM — same pattern as BrokerBot ─────────────────────────────────

class FallbackLLM:
    """
    Wraps multiple LLMs with automatic fallback on rate limit errors.
    Tries models in order — if one hits rate limit, moves to next.
    """

    def __init__(self, model_chain: list[dict], tools: list):
        self.bound_models = []
        for entry in model_chain:
            try:
                bound = entry["llm"].bind_tools(tools)
                self.bound_models.append({
                    "name": entry["name"],
                    "llm": bound,
                    "rate_limit_errors": entry["rate_limit_errors"],
                })
            except Exception as e:
                logger.warning(f"Could not bind tools to {entry['name']}: {e}")

    async def ainvoke(self, messages: list) -> BaseMessage:
        last_error = None
        for i, model_entry in enumerate(self.bound_models):
            try:
                logger.info(f"🤖 Trying model: {model_entry['name']}")
                response = await model_entry["llm"].ainvoke(messages)
                if i > 0:
                    logger.info(f"✅ Fell back to: {model_entry['name']}")
                return response
            except Exception as e:
                if is_rate_limit_error(e, model_entry["rate_limit_errors"]):
                    logger.warning(f"⚡ Skipping {model_entry['name']} (rate limit) — trying next...")
                    last_error = e
                    await asyncio.sleep(0.5)
                    continue
                else:
                    logger.error(f"❌ Error on {model_entry['name']}: {e}")
                    raise e
        raise RuntimeError(f"All models exhausted. Last error: {last_error}")


# ─── Build Model Chain ────────────────────────────────────────────────────────

def build_model_chain() -> list[dict]:
    """
    Build fallback chain in priority order:
    1. Groq Llama 3.3 70B  — best tool use, free, high RPM
    2. Gemini 2.5 Flash     — free but only 10 RPM on free tier
    3. Zhipu GLM-4-Flash    — free, generous limits, via OpenAI-compatible API
    4. Groq Llama 3.1 8B   — very high RPM, last resort
    """
    models = []

    # ── 1. Groq Llama 3.3 70B (primary — best tool use) ──
    if settings.groq_api_key:
        try:
            from langchain_groq import ChatGroq
            models.append({
                "name": "Groq / llama-3.3-70b-versatile",
                "llm": ChatGroq(
                    model="llama-3.3-70b-versatile",
                    groq_api_key=settings.groq_api_key,
                    max_tokens=4096,
                    temperature=0.1,
                ),
                "rate_limit_errors": ["rate_limit_exceeded", "429", "RateLimitError", "Too Many Requests"],
            })
            logger.info("✅ Model loaded: Groq llama-3.3-70b-versatile")
        except Exception as e:
            logger.warning(f"⚠️ Groq 70B unavailable: {e}")

    # ── 2. Gemini 2.5 Flash (second — good quality, free) ──
    if settings.google_api_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            models.append({
                "name": "Google / gemini-2.5-flash-lite",
                "llm": ChatGoogleGenerativeAI(
                    model="gemini-2.5-flash-lite",
                    google_api_key=settings.google_api_key,
                    temperature=0.1,
                    max_output_tokens=4096,
                ),
                "rate_limit_errors": ["429", "quota", "resource exhausted", "resourceexhausted"],
            })
            logger.info("✅ Model loaded: Google gemini-2.5-flash-lite")
        except Exception as e:
            logger.warning(f"⚠️ Gemini unavailable: {e}")

    # ── 3. Zhipu GLM-4-Flash (third — free, generous limits) ──
    if settings.zhipu_api_key:
        try:
            from langchain_openai import ChatOpenAI
            models.append({
                "name": "Zhipu / glm-4-flash",
                "llm": ChatOpenAI(
                    model="glm-4-flash",
                    api_key=settings.zhipu_api_key,
                    base_url="https://open.bigmodel.cn/api/paas/v4/",
                    max_tokens=4096,
                    temperature=0.1,
                ),
                "rate_limit_errors": ["429", "rate limit", "RateLimitError", "too many requests"],
            })
            logger.info("✅ Model loaded: Zhipu glm-4-flash")
        except Exception as e:
            logger.warning(f"⚠️ Zhipu GLM unavailable: {e}")

    # ── 4. Groq Llama 3.1 8B (last resort — very high RPM) ──
    if settings.groq_api_key:
        try:
            from langchain_groq import ChatGroq
            models.append({
                "name": "Groq / llama-3.1-8b-instant",
                "llm": ChatGroq(
                    model="llama-3.1-8b-instant",
                    groq_api_key=settings.groq_api_key,
                    max_tokens=4096,
                    temperature=0.1,
                ),
                "rate_limit_errors": ["rate_limit_exceeded", "429", "RateLimitError", "Too Many Requests"],
            })
            logger.info("✅ Model loaded: Groq llama-3.1-8b-instant")
        except Exception as e:
            logger.warning(f"⚠️ Groq 8B unavailable: {e}")

    if not models:
        raise RuntimeError("No LLM configured! Set at least one of: GROQ_API_KEY, GOOGLE_API_KEY, ZHIPU_API_KEY")

    logger.info(f"🔗 Fallback chain: {' → '.join(m['name'] for m in models)}")
    return models


# ─── Build Agent ──────────────────────────────────────────────────────────────

def build_agent():
    model_chain = build_model_chain()
    fallback_llm = FallbackLLM(model_chain, ALL_TOOLS)

    async def call_model(state: AgentState):
        messages = list(state["messages"])
        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=APPLY_SYSTEM_PROMPT)] + messages
        response = await fallback_llm.ainvoke(messages)
        return {"messages": [response]}

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(ALL_TOOLS))
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    return graph.compile()


job_agent = build_agent()


# ─── Auto Apply (called from main.py) ────────────────────────────────────────

async def run_auto_apply(
    candidate: dict,
    job_ids: list[str],
    session_id: str,
    history: list = None,
) -> tuple[str, list]:
    """Apply to pre-filtered jobs (already scored ≥80%)."""
    import json
    from db.supabase_client import supabase

    history = history or []

    jobs = []
    for job_id in job_ids:
        try:
            r = supabase.table("jobs").select("*").eq("id", job_id).single().execute()
            if r.data:
                jobs.append(r.data)
        except Exception as e:
            logger.warning(f"Could not fetch job {job_id}: {e}")

    if not jobs:
        return "No valid jobs found to apply to.", history

    has_pdf_cv = (candidate.get("base_resume_text") or "").startswith("PDF:")
    candidate_display = {k: v for k, v in candidate.items() if k != "base_resume_text"}

    # Process in batches of 4 to stay within recursion limits
    # Each job needs ~8 tool calls; 4 jobs × 8 = 32 + buffer = 60
    BATCH_SIZE = 4
    all_responses = []

    for batch_start in range(0, len(jobs), BATCH_SIZE):
        batch = jobs[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(jobs) + BATCH_SIZE - 1) // BATCH_SIZE
        logger.info(f"🔄 Processing batch {batch_num}/{total_batches} ({len(batch)} jobs)")

        prompt = f"""Apply to these {len(batch)} pre-matched jobs for this candidate. (Batch {batch_num} of {total_batches})

CANDIDATE:
{json.dumps(candidate_display, indent=2)}

{"NOTE: Candidate has uploaded a PDF CV — reference base_resume_text when building resumes." if has_pdf_cv else "NOTE: No PDF CV — use profile data only."}

JOBS TO APPLY:
{json.dumps([{
    "id": j.get("id"),
    "title": j.get("title"),
    "company": j.get("company"),
    "portal": j.get("portal"),
    "apply_url": j.get("apply_url"),
    "description": (j.get("description") or "")[:400],
    "skills_required": j.get("skills_required", []),
} for j in batch], indent=2)}

For each job: check_already_applied → build_resume → apply_to_job → record_application → save_resume_to_repo
Use the full UUID from build_resume result as resume_id."""

        try:
            messages = [HumanMessage(content=prompt)]
            recursion_limit = max(60, len(batch) * 12 + 20)
            result = await job_agent.ainvoke(
                {"messages": messages},
                config={"recursion_limit": recursion_limit}
            )
            batch_response = result["messages"][-1].content
            all_responses.append(f"Batch {batch_num}: {batch_response}")
            logger.info(f"✅ Batch {batch_num} complete")
        except Exception as e:
            logger.error(f"❌ Batch {batch_num} failed: {e}")
            all_responses.append(f"Batch {batch_num} failed: {str(e)}")

    response = "\n\n".join(all_responses)
    updated_history = history + [
        {"role": "user", "content": f"Applied to {len(jobs)} jobs in {len(all_responses)} batches"},
        {"role": "assistant", "content": response}
    ]
    return response, updated_history


# ─── Legacy ───────────────────────────────────────────────────────────────────

async def run_job_search(candidate: dict, job_query: str, location: str = "India", history: list = None) -> tuple[str, list]:
    import json
    history = history or []
    prompt = f"Search and apply for {job_query} jobs in {location} for candidate: {json.dumps(candidate, indent=2)}"
    messages = [HumanMessage(content=prompt)]
    result = await job_agent.ainvoke(
        {"messages": messages},
        config={"recursion_limit": 150}
    )
    response = result["messages"][-1].content
    return response, history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": response}]
