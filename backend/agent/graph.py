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

SYSTEM_PROMPT = """You are JobBot — an AI agent that automatically finds and applies to jobs on behalf of candidates.

## YOUR WORKFLOW (follow this order strictly):

### STEP 1 — SEARCH JOBS
- Use search_jobs with candidate's skills as query
- Search all portals: naukri, linkedin, indeed, instahyre, adzuna
- Save each found job with save_job_to_repo

### STEP 2 — ANALYSE EACH JOB
- Use fetch_full_jd to get complete job description
- Use analyse_jd to extract keywords, skills, requirements

### STEP 3 — MATCH CANDIDATE
- Use match_candidate_to_jd to score candidate vs JD
- ONLY PROCEED if score >= 80
- If score < 80, record as SKIPPED and move to next job

### STEP 4 — BUILD RESUME
- Use build_resume to create a tailored PDF resume
- Resume will have JD keywords injected and skills reordered
- Save resume with save_resume_to_repo

### STEP 5 — CHECK & APPLY
- Use check_already_applied to avoid duplicates
- Use get_portal_credentials to find existing account
- Use apply_to_job to submit application
- If new account created, save with save_portal_credentials

### STEP 6 — RECORD
- Use record_application to save result (APPLIED or FAILED)
- Continue to next job

## RULES:
- NEVER apply if match score < 80
- NEVER apply to same job twice (check_already_applied)
- ALWAYS save every job found (even if not applied)
- ALWAYS save credentials when new account created
- Tell user progress: "Searching... Found X jobs... Matched Y... Applied to Z"

## STYLE: Be concise, report progress clearly, use ✅ ❌ ⏭ for status."""

# ─── Tools ────────────────────────────────────────────────────────────────────

ALL_TOOLS = [
    search_jobs,
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
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
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


# ─── Chat Interface ───────────────────────────────────────────────────────────

async def run_job_search(
    candidate: dict,
    job_query: str,
    location: str = "India",
    history: list = None
) -> tuple[str, list]:
    """
    Run the full job search and application workflow.

    Args:
        candidate: Full candidate profile dict
        job_query: e.g. "Python Developer", "React Frontend Engineer"
        location: Location preference
        history: Conversation history

    Returns:
        Final response text and updated history
    """
    import json

    history = history or []
    messages = [HumanMessage(content=m["content"]) if m["role"] == "user"
                else AIMessage(content=m["content"])
                for m in history]

    prompt = f"""Start the job search workflow for this candidate:

CANDIDATE PROFILE:
{json.dumps(candidate, indent=2)}

SEARCH QUERY: {job_query}
LOCATION: {location}
MIN MATCH SCORE: {settings.min_match_score}%

Please:
1. Search for {job_query} jobs in {location} across all portals
2. For each job, analyse JD, score match, skip if < {settings.min_match_score}%
3. For matching jobs, build tailored resume and apply
4. Report progress at each step
5. Give final summary: X jobs found, Y matched, Z applied"""

    messages.append(HumanMessage(content=prompt))

    result = await job_agent.ainvoke({"messages": messages})
    response = result["messages"][-1].content

    updated_history = history + [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": response}
    ]
    return response, updated_history
