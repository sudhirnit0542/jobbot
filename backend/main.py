"""
JobBot FastAPI Backend
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from loguru import logger
from datetime import datetime

from config import get_settings
from agent.graph import run_job_search
from db.supabase_client import (
    upsert_candidate, get_candidate,
    get_applications, create_session, complete_session
)

settings = get_settings()

app = FastAPI(title="JobBot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Models ───────────────────────────────────────────────────────────────────

class CandidateProfile(BaseModel):
    name: str
    email: str
    phone: str = ""
    location: str = ""
    linkedin_url: str = ""
    github_url: str = ""
    skills: list[str] = []
    experience_years: int = 0
    experience: list[dict] = []
    education: list[dict] = []
    certifications: list[str] = []
    summary: str = ""

class SearchRequest(BaseModel):
    candidate_id: str
    job_query: str
    location: str = "India"

class SearchStatus(BaseModel):
    session_id: str


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/candidate")
async def save_candidate(profile: CandidateProfile):
    """Save or update candidate profile."""
    data = profile.dict()
    # Build base_resume_text for AI matching
    skills_text = ", ".join(data.get("skills", []))
    exp_text = " | ".join([
        f"{e.get('role', '')} at {e.get('company', '')} ({e.get('duration', '')}): {e.get('description', '')}"
        for e in data.get("experience", [])
    ])
    data["base_resume_text"] = f"{data['summary']}\nSkills: {skills_text}\nExperience: {exp_text}"
    saved = await upsert_candidate(data)
    return {"success": True, "candidate": saved}


@app.get("/candidate/{candidate_id}")
async def get_candidate_profile(candidate_id: str):
    candidate = await get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


@app.post("/search/start")
async def start_job_search(req: SearchRequest, background_tasks: BackgroundTasks):
    """
    Start automated job search and application workflow.
    Runs in background — poll /search/status for updates.
    """
    candidate = await get_candidate(req.candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    session = await create_session(
        req.candidate_id, req.job_query,
        ["naukri", "linkedin", "indeed", "instahyre", "adzuna"]
    )
    session_id = session.get("id")

    async def run_search():
        try:
            response, _ = await run_job_search(
                candidate=candidate,
                job_query=req.job_query,
                location=req.location,
            )
            await complete_session(session_id, {"status": "COMPLETED", "notes": response[:500]})
            logger.info(f"Search session {session_id} completed")
        except Exception as e:
            logger.error(f"Search session {session_id} failed: {e}")
            await complete_session(session_id, {"status": "FAILED", "notes": str(e)})

    background_tasks.add_task(run_search)

    return {
        "success": True,
        "session_id": session_id,
        "message": f"Job search started for '{req.job_query}' in {req.location}",
        "note": "This runs in background. Check /applications/{candidate_id} for results."
    }


@app.get("/applications/{candidate_id}")
async def get_candidate_applications(candidate_id: str):
    """Get all applications for a candidate."""
    apps = await get_applications(candidate_id)
    summary = {
        "total": len(apps),
        "applied": len([a for a in apps if a["status"] == "APPLIED"]),
        "failed": len([a for a in apps if a["status"] == "FAILED"]),
        "skipped": len([a for a in apps if a["status"] == "SKIPPED"]),
        "interview": len([a for a in apps if a["status"] == "INTERVIEW"]),
    }
    return {"summary": summary, "applications": apps}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
