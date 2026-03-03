"""
JobBot FastAPI Backend
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from loguru import logger
from datetime import datetime
import json
import io

from config import get_settings
from agent.graph import run_job_search, run_auto_apply
from agent.tools.job_search import search_jobs as search_jobs_tool
from agent.tools.matcher import analyse_jd, match_candidate_to_jd
from db.supabase_client import (
    upsert_candidate, get_candidate,
    get_applications, create_session, complete_session, save_job
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

class ApplyRequest(BaseModel):
    candidate_id: str
    session_id: str
    job_ids: list[str] = []


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ─── Candidate ────────────────────────────────────────────────────────────────

@app.post("/candidate")
async def save_candidate(profile: CandidateProfile):
    """Save or update candidate profile."""
    data = profile.dict()
    skills_text = ", ".join(data.get("skills", []))
    exp_text = " | ".join([
        f"{e.get('role', '')} at {e.get('company', '')} ({e.get('duration', '')}): "
        f"{e.get('description', '')} {' '.join(e.get('achievements', []))}"
        for e in data.get("experience", [])
    ])
    # Only overwrite base_resume_text if no PDF has been uploaded yet
    existing = await get_candidate_by_email(data["email"])
    if not existing or not existing.get("base_resume_text", "").startswith("PDF:"):
        data["base_resume_text"] = f"{data['summary']}\nSkills: {skills_text}\nExperience: {exp_text}"
    saved = await upsert_candidate(data)
    return {"success": True, "candidate": saved}


@app.get("/candidate/{candidate_id}")
async def get_candidate_profile(candidate_id: str):
    candidate = await get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


@app.post("/candidate/{candidate_id}/upload-cv")
async def upload_cv(candidate_id: str, file: UploadFile = File(...)):
    """
    Upload candidate CV as PDF.
    Extracts text, skills, and summary using AI.
    Stores full PDF text as base_resume_text for future job matching.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted")

    candidate = await get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    try:
        # Read PDF bytes
        pdf_bytes = await file.read()

        # Extract text from PDF
        pdf_text = extract_pdf_text(pdf_bytes)

        if not pdf_text or len(pdf_text) < 100:
            raise HTTPException(status_code=400, detail="Could not extract text from PDF. Make sure it's a text-based PDF, not a scanned image.")

        # Use AI to extract skills and summary from CV text
        extracted = await extract_skills_from_cv(pdf_text)

        # Save to candidate — prefix with "PDF:" so we know it came from upload
        update_data = {
            "id": candidate_id,
            "base_resume_text": f"PDF:{pdf_text[:8000]}",  # Store up to 8000 chars
        }

        # Only update skills if we extracted them and candidate has fewer
        if extracted.get("skills") and len(extracted["skills"]) > len(candidate.get("skills", [])):
            update_data["skills"] = extracted["skills"]

        if extracted.get("summary") and not candidate.get("summary"):
            update_data["summary"] = extracted["summary"]

        if extracted.get("experience_years") and not candidate.get("experience_years"):
            update_data["experience_years"] = extracted["experience_years"]

        await upsert_candidate(update_data)

        return {
            "success": True,
            "message": "CV uploaded and text extracted",
            "extracted_skills": extracted.get("skills", []),
            "extracted_summary": extracted.get("summary", ""),
            "text_length": len(pdf_text),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"CV upload error: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract plain text from PDF bytes."""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            return text.strip()
    except ImportError:
        pass

    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return text.strip()
    except ImportError:
        pass

    raise HTTPException(status_code=500, detail="PDF parsing library not available. Add pdfplumber to requirements.txt")


async def extract_skills_from_cv(cv_text: str) -> dict:
    """Use AI to extract structured info from CV text."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from langchain_groq import ChatGroq
        from langchain_core.messages import HumanMessage

        prompt = f"""Extract structured information from this CV/Resume text.
Return ONLY a JSON object with these fields:
{{
  "skills": ["skill1", "skill2", ...],  // all technical skills mentioned
  "summary": "2-3 sentence professional summary",
  "experience_years": 5  // total years of experience as integer
}}

CV TEXT:
{cv_text[:4000]}

Return only the JSON, no other text."""

        # Try Gemini first, then Groq
        llm = None
        if settings.google_api_key:
            llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", google_api_key=settings.google_api_key, temperature=0)
        elif settings.groq_api_key:
            llm = ChatGroq(model="llama-3.3-70b-versatile", groq_api_key=settings.groq_api_key, temperature=0)

        if llm:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            text = response.content.strip()
            # Strip markdown fences if present
            text = text.replace("```json", "").replace("```", "").strip()
            return json.loads(text)
    except Exception as e:
        logger.warning(f"AI extraction failed, using fallback: {e}")

    # Fallback — basic keyword extraction
    from agent.tools.matcher import COMMON_TECH_SKILLS
    text_lower = cv_text.lower()
    skills = [s for s in COMMON_TECH_SKILLS if s in text_lower]
    return {"skills": skills, "summary": "", "experience_years": 0}


async def get_candidate_by_email(email: str) -> dict | None:
    """Helper to find candidate by email."""
    try:
        from db.supabase_client import supabase
        r = supabase.table("candidates").select("*").eq("email", email).execute()
        return r.data[0] if r.data else None
    except:
        return None


# ─── Search (Step 1) ──────────────────────────────────────────────────────────

@app.post("/search/jobs")
async def search_and_score_jobs(req: SearchRequest):
    """
    Step 1: Search jobs and score each against candidate profile.
    Returns list of all jobs with match scores — does NOT apply yet.
    User reviews results then calls /search/apply to trigger auto-apply.
    """
    candidate = await get_candidate(req.candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    session = await create_session(
        req.candidate_id, req.job_query,
        ["naukri", "linkedin", "indeed", "instahyre", "adzuna"]
    )
    session_id = session.get("id", "")

    try:
        # Search all portals
        import json as json_mod
        from agent.tools.job_search import (
            search_adzuna, search_naukri, search_indeed,
            search_instahyre, search_linkedin, fetch_job_description
        )
        from agent.tools.matcher import extract_keywords_from_jd, score_match

        all_jobs = []
        all_jobs.extend(search_adzuna(req.job_query, req.location))
        all_jobs.extend(search_naukri(req.job_query, req.location))
        all_jobs.extend(search_indeed(req.job_query, req.location))
        all_jobs.extend(search_instahyre(req.job_query, req.location))
        all_jobs.extend(search_linkedin(req.job_query, req.location))

        # Deduplicate
        seen = set()
        unique_jobs = []
        for job in all_jobs:
            key = f"{job['title'].lower()}_{job['company'].lower()}"
            if key not in seen:
                seen.add(key)
                unique_jobs.append(job)

        # Score each job against candidate
        candidate_json_str = json_mod.dumps(candidate)
        scored_jobs = []

        for job in unique_jobs[:40]:  # Score top 40
            try:
                # Get JD text — use description if available, else fetch
                jd_text = job.get("description", "")
                if len(jd_text) < 200 and job.get("apply_url"):
                    jd_text = fetch_job_description(job["apply_url"], job["portal"])

                # Extract keywords and score
                kw = extract_keywords_from_jd(jd_text or job.get("title", ""))
                match = score_match(candidate, kw)

                # Save job to DB
                saved = await save_job(job)
                job_id = saved.get("id", "")

                scored_jobs.append({
                    **job,
                    "job_id": job_id,
                    "match_score": match["score"],
                    "matched_keywords": match["matched_must_have"],
                    "missing_keywords": match["missing_must_have"],
                    "recommendation": match["recommendation"],
                })
            except Exception as e:
                logger.warning(f"Scoring failed for {job.get('title')}: {e}")
                scored_jobs.append({**job, "job_id": "", "match_score": 0, "recommendation": "SKIP"})

        # Sort by score desc
        scored_jobs.sort(key=lambda x: x["match_score"], reverse=True)

        matched_count = len([j for j in scored_jobs if j["match_score"] >= 80])

        return {
            "session_id": session_id,
            "total_found": len(scored_jobs),
            "matched_count": matched_count,
            "query": req.job_query,
            "location": req.location,
            "jobs": scored_jobs,
        }

    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Auto Apply (Step 2) ──────────────────────────────────────────────────────

@app.post("/search/apply")
async def auto_apply_to_jobs(req: ApplyRequest, background_tasks: BackgroundTasks):
    """
    Step 2: Auto-apply to matched jobs in background.
    Only applies to job_ids provided (frontend sends ≥80% matched ones).
    """
    candidate = await get_candidate(req.candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    async def run_apply():
        try:
            response, _ = await run_auto_apply(
                candidate=candidate,
                job_ids=req.job_ids,
                session_id=req.session_id,
            )
            await complete_session(req.session_id, {
                "status": "COMPLETED",
                "jobs_applied": len(req.job_ids),
                "notes": response[:500]
            })
        except Exception as e:
            logger.error(f"Auto-apply failed: {e}")
            await complete_session(req.session_id, {"status": "FAILED", "notes": str(e)})

    background_tasks.add_task(run_apply)

    return {
        "success": True,
        "session_id": req.session_id,
        "jobs_to_apply": len(req.job_ids),
        "message": f"Auto-applying to {len(req.job_ids)} jobs in background"
    }


# ─── Applications Dashboard ───────────────────────────────────────────────────

@app.get("/applications/{candidate_id}")
async def get_candidate_applications(candidate_id: str):
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
