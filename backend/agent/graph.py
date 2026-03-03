"""
JobBot LangGraph Agent
Orchestrates: Search → Analyse → Match → Build Resume → Apply → Save
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

# ─── System Prompt ────────────────────────────────────────────────────────────

APPLY_SYSTEM_PROMPT = """You are JobBot — an AI agent applying to pre-matched jobs on behalf of a candidate.

You have been given a list of jobs that already passed the 80% match threshold.
For each job:

1. Use check_already_applied to skip duplicates
2. Use get_portal_credentials to find existing portal account
3. Use build_resume to create a tailored PDF resume using the candidate's CV + JD keywords
4. Use apply_to_job to submit the application
5. If new account created, use save_portal_credentials to save it
6. Use record_application to log the result (APPLIED or FAILED)
7. Use save_resume_to_repo to save the resume record

IMPORTANT:
- The candidate may have uploaded a PDF CV — use base_resume_text field which contains it
- Always reference both the CV content and JD keywords when building the resume
- Report progress clearly: ✅ Applied | ❌ Failed | ⏭ Already applied

Be concise. Report each job result on one line."""


# ─── Tools ────────────────────────────────────────────────────────────────────

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


# ─── State ────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]


# ─── LLM with fallback ────────────────────────────────────────────────────────

def build_llm():
    models = []

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
                "rate_errors": ["429", "quota", "resource exhausted"],
            })
        except Exception as e:
            logger.warning(f"Gemini unavailable: {e}")

    if settings.groq_api_key:
        try:
            from langchain_groq import ChatGroq
            models.append({
                "name": "Groq / llama-3.3-70b",
                "llm": ChatGroq(
                    model="llama-3.3-70b-versatile",
                    groq_api_key=settings.groq_api_key,
                    max_tokens=4096,
                    temperature=0.1,
                ).bind_tools(ALL_TOOLS),
                "rate_errors": ["rate_limit_exceeded", "429"],
            })
        except Exception as e:
            logger.warning(f"Groq unavailable: {e}")

    if not models:
        raise RuntimeError("No LLM configured! Set GOOGLE_API_KEY or GROQ_API_KEY")

    return models


async def invoke_with_fallback(models, messages):
    for i, m in enumerate(models):
        try:
            response = await m["llm"].ainvoke(messages)
            if i > 0:
                logger.info(f"Fell back to: {m['name']}")
            return response
        except Exception as e:
            err = str(e).lower()
            if any(r in err for r in m["rate_errors"]):
                logger.warning(f"Rate limit on {m['name']}, trying next...")
                await asyncio.sleep(0.5)
                continue
            raise e
    raise RuntimeError("All models exhausted")


# ─── Build Graph ──────────────────────────────────────────────────────────────

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


# ─── Auto Apply (Step 2) ─────────────────────────────────────────────────────

async def run_auto_apply(
    candidate: dict,
    job_ids: list[str],
    session_id: str,
    history: list = None,
) -> tuple[str, list]:
    """
    Apply to a pre-filtered list of jobs (already scored ≥80%).
    Fetches each job from DB, builds tailored resume referencing CV, applies.
    """
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
        return "No valid jobs to apply to.", history

    # Check if candidate has a PDF CV uploaded
    has_pdf_cv = candidate.get("base_resume_text", "").startswith("PDF:")

    prompt = f"""Apply to these {len(jobs)} pre-matched jobs for the candidate.

CANDIDATE PROFILE:
{json.dumps({k: v for k, v in candidate.items() if k != 'base_resume_text'}, indent=2)}

{"CANDIDATE HAS UPLOADED A PDF CV — use base_resume_text field when building resumes" if has_pdf_cv else "No PDF CV uploaded — use profile data only"}

JOBS TO APPLY (all have ≥80% match score already verified):
{json.dumps([{"id": j.get("id"), "title": j.get("title"), "company": j.get("company"),
              "portal": j.get("portal"), "apply_url": j.get("apply_url"),
              "description": (j.get("description") or "")[:500]} for j in jobs], indent=2)}

For each job:
1. check_already_applied first
2. get_portal_credentials for the portal
3. build_resume using candidate profile + JD keywords {"+ CV content from base_resume_text" if has_pdf_cv else ""}
4. apply_to_job
5. save credentials if new account created
6. record_application with result
7. save_resume_to_repo

Report each result clearly."""

    messages = [HumanMessage(content=prompt)]
    result = await job_agent.ainvoke({"messages": messages})
    response = result["messages"][-1].content

    updated_history = history + [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": response}
    ]
    return response, updated_history


# ─── Legacy full search+apply (kept for compatibility) ───────────────────────

async def run_job_search(
    candidate: dict,
    job_query: str,
    location: str = "India",
    history: list = None
) -> tuple[str, list]:
    """Original single-step search+apply flow (kept for backwards compat)."""
    import json

    history = history or []
    messages = [HumanMessage(content=m["content"]) if m["role"] == "user"
                else AIMessage(content=m["content"])
                for m in history]

    prompt = f"""Search and apply for {job_query} jobs in {location} for this candidate.
Only apply to jobs with match score >= {settings.min_match_score}%.

CANDIDATE:
{json.dumps(candidate, indent=2)}"""

    messages.append(HumanMessage(content=prompt))
    result = await job_agent.ainvoke({"messages": messages})
    response = result["messages"][-1].content

    updated_history = history + [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": response}
    ]
    return response, updated_history
