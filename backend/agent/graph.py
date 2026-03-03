"""
JobBot LangGraph Agent
Groq primary → Gemini fallback → Groq 8B last resort
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


def build_llm():
    models = []

    # ── Groq 70B first — higher RPM than Gemini free tier ──
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
                ).bind_tools(ALL_TOOLS),
                "rate_errors": ["rate_limit_exceeded", "429", "too many requests"],
            })
            logger.info("✅ Model loaded: Groq llama-3.3-70b-versatile")
        except Exception as e:
            logger.warning(f"Groq 70B unavailable: {e}")

    # ── Gemini second ──
    if settings.google_api_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            models.append({
                "name": "Gemini / gemini-2.5-flash-lite",
                "llm": ChatGoogleGenerativeAI(
                    model="gemini-2.5-flash-lite",
                    google_api_key=settings.google_api_key,
                    temperature=0.1,
                    max_output_tokens=4096,
                ).bind_tools(ALL_TOOLS),
                "rate_errors": ["429", "quota", "resource exhausted", "resourceexhausted"],
            })
            logger.info("✅ Model loaded: Gemini gemini-2.5-flash-lite")
        except Exception as e:
            logger.warning(f"Gemini unavailable: {e}")

    # ── Groq 8B — high rate limits, last resort ──
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
                ).bind_tools(ALL_TOOLS),
                "rate_errors": ["rate_limit_exceeded", "429", "too many requests"],
            })
            logger.info("✅ Model loaded: Groq llama-3.1-8b-instant")
        except Exception as e:
            logger.warning(f"Groq 8B unavailable: {e}")

    if not models:
        raise RuntimeError("No LLM configured! Set GROQ_API_KEY or GOOGLE_API_KEY")

    logger.info(f"🔗 Fallback chain: {' → '.join(m['name'] for m in models)}")
    return models


async def invoke_with_fallback(models, messages):
    last_error = None
    for i, m in enumerate(models):
        try:
            response = await m["llm"].ainvoke(messages)
            if i > 0:
                logger.info(f"✅ Fell back to: {m['name']}")
            return response
        except Exception as e:
            err = str(e).lower()
            if any(r in err for r in m["rate_errors"]):
                logger.warning(f"⚡ Rate limit on {m['name']}, trying next...")
                last_error = e
                await asyncio.sleep(1)
                continue
            raise e
    raise RuntimeError(f"All models exhausted. Last error: {last_error}")


def build_agent():
    llm_chain = build_llm()

    async def call_model(state: AgentState):
        messages = list(state["messages"])
        if not any(isinstance(m, SystemMessage) for m in messages):
            messages = [SystemMessage(content=APPLY_SYSTEM_PROMPT)] + messages
        response = await invoke_with_fallback(llm_chain, messages)
        return {"messages": [response]}

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(ALL_TOOLS))
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    return graph.compile()


job_agent = build_agent()


async def run_auto_apply(
    candidate: dict,
    job_ids: list[str],
    session_id: str,
    history: list = None,
) -> tuple[str, list]:
    """Apply to pre-filtered jobs (already scored >=80%)."""
    import json
    from db.supabase_client import supabase

    history = history or []

    # Fetch full job details from DB
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

    # Strip base_resume_text from candidate dict shown in prompt (too long)
    candidate_display = {k: v for k, v in candidate.items() if k != "base_resume_text"}

    prompt = f"""Apply to these {len(jobs)} pre-matched jobs for this candidate.

CANDIDATE:
{json.dumps(candidate_display, indent=2)}

{"NOTE: Candidate has uploaded a PDF CV. The full CV text is in candidate base_resume_text field — reference it when building resumes." if has_pdf_cv else "NOTE: No PDF CV. Use profile data only."}

JOBS TO APPLY:
{json.dumps([{
    "id": j.get("id"),
    "title": j.get("title"),
    "company": j.get("company"),
    "portal": j.get("portal"),
    "apply_url": j.get("apply_url"),
    "description": (j.get("description") or "")[:400],
    "skills_required": j.get("skills_required", []),
} for j in jobs], indent=2)}

Process each job in order. For resume_id always use the full UUID returned by build_resume."""

    messages = [HumanMessage(content=prompt)]
    result = await job_agent.ainvoke({"messages": messages})
    response = result["messages"][-1].content

    updated_history = history + [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": response}
    ]
    return response, updated_history


async def run_job_search(
    candidate: dict,
    job_query: str,
    location: str = "India",
    history: list = None
) -> tuple[str, list]:
    """Legacy single-step search+apply (kept for compatibility)."""
    import json
    history = history or []
    prompt = f"Search and apply for {job_query} jobs in {location} for candidate: {json.dumps(candidate, indent=2)}"
    messages = [HumanMessage(content=prompt)]
    result = await job_agent.ainvoke({"messages": messages})
    response = result["messages"][-1].content
    updated_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": response}]
    return response, updated_history
