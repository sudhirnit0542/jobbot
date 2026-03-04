"""
JobBot FastAPI Backend
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from loguru import logger
from datetime import datetime
import json
import io
import jwt as pyjwt

from config import get_settings
from agent.graph import run_auto_apply
from db.supabase_client import (
    upsert_candidate, get_candidate, get_candidate_by_email,
    get_applications, create_session, complete_session, save_job,
    supabase, now_iso
)

settings = get_settings()

# ─── Auth ─────────────────────────────────────────────────────────────────────

security = HTTPBearer()

# Cache JWKS keys so we don't fetch on every request
_jwks_cache: dict = {}

def _get_jwks() -> dict:
    """Fetch Supabase public JWKS (cached in memory)."""
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache
    import urllib.request
    jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    try:
        with urllib.request.urlopen(jwks_url, timeout=5) as r:
            _jwks_cache = json.loads(r.read())
            logger.info(f"JWKS loaded: {len(_jwks_cache.get('keys', []))} keys")
            return _jwks_cache
    except Exception as e:
        logger.error(f"Failed to fetch JWKS from {jwks_url}: {e}")
        return {}

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    Validate Supabase JWT — supports both ES256 (new projects) and HS256 (legacy).
    Returns decoded payload {sub, email, ...}
    """
    token = credentials.credentials

    # Peek at header to get algorithm and kid
    try:
        header = pyjwt.get_unverified_header(token)
        alg = header.get("alg", "HS256")
        kid = header.get("kid")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token header: {e}")

    try:
        if alg == "HS256":
            # Legacy Supabase projects — symmetric secret
            payload = pyjwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
        else:
            # Modern Supabase projects — ES256 with JWKS
            jwks = _get_jwks()
            keys = jwks.get("keys", [])
            if not keys:
                raise HTTPException(status_code=500, detail="Could not load auth public keys")

            # Find matching key by kid
            signing_key = None
            for k in keys:
                if not kid or k.get("kid") == kid:
                    signing_key = pyjwt.algorithms.ECAlgorithm.from_jwk(json.dumps(k))
                    break

            if not signing_key:
                # Retry with fresh JWKS in case keys rotated
                global _jwks_cache
                _jwks_cache = {}
                jwks = _get_jwks()
                for k in jwks.get("keys", []):
                    if not kid or k.get("kid") == kid:
                        signing_key = pyjwt.algorithms.ECAlgorithm.from_jwk(json.dumps(k))
                        break

            if not signing_key:
                raise HTTPException(status_code=401, detail=f"No matching public key for kid={kid}")

            payload = pyjwt.decode(
                token,
                signing_key,
                algorithms=["ES256"],
                options={"verify_aud": False},
            )

        return payload

    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired — please log in again")
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth error: {e}")
        raise HTTPException(status_code=401, detail=f"Auth failed: {e}")

def get_candidate_id_for_user(user: dict) -> str:
    """Get or create candidate record for authenticated user."""
    user_id = user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid user token")
    try:
        r = supabase.table("candidates").select("id").eq("user_id", user_id).single().execute()
        if r.data:
            return r.data["id"]
    except:
        pass
    # Auto-create candidate row if missing (e.g. trigger didn't fire)
    email = user.get("email", "")
    name = user.get("user_metadata", {}).get("full_name") or email.split("@")[0]
    result = supabase.table("candidates").insert({
        "user_id": user_id, "name": name, "email": email
    }).execute()
    if result.data:
        return result.data[0]["id"]
    raise HTTPException(status_code=500, detail="Could not create candidate record")


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
async def save_candidate(profile: CandidateProfile, user: dict = Depends(get_current_user)):
    """Save or update candidate profile."""
    data = profile.dict()
    data["user_id"] = user.get("sub")  # Link to Supabase auth user

    # Build base_resume_text from profile fields
    skills_text = ", ".join(data.get("skills", []))
    exp_text = " | ".join([
        f"{e.get('role', '')} at {e.get('company', '')} ({e.get('duration', '')}): "
        f"{e.get('description', '')} {' '.join(e.get('achievements', []))}"
        for e in data.get("experience", [])
    ])

    # Don't overwrite PDF CV if already uploaded
    existing = get_candidate_by_email(data["email"])
    if not existing or not (existing.get("base_resume_text") or "").startswith("PDF:"):
        data["base_resume_text"] = f"{data['summary']}\nSkills: {skills_text}\nExperience: {exp_text}"

    saved = upsert_candidate(data)
    return {"success": True, "candidate": saved}


@app.get("/candidate/me")
async def get_candidate_profile(user: dict = Depends(get_current_user)):
    candidate_id = get_candidate_id_for_user(user)
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


@app.post("/candidate/me/upload-cv")
async def upload_cv(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """
    Upload candidate CV as PDF.
    Extracts text and skills using AI.
    Updates ONLY base_resume_text + skills on the existing candidate record.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted")

    candidate = get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    try:
        pdf_bytes = await file.read()
        pdf_text = extract_pdf_text(pdf_bytes)

        if not pdf_text or len(pdf_text) < 50:
            raise HTTPException(
                status_code=400,
                detail="Could not extract text from PDF. Make sure it's a text-based PDF, not a scanned image."
            )

        # Extract skills using AI
        extracted = await extract_skills_from_cv(pdf_text)

        # Direct UPDATE — only touch cv-related fields, never touch name/email
        update_data = {
            "base_resume_text": f"PDF:{pdf_text[:8000]}",
            "updated_at": now_iso(),
        }

        # Only update skills if we extracted more than candidate already has
        existing_skills = candidate.get("skills") or []
        new_skills = extracted.get("skills", [])
        if len(new_skills) > len(existing_skills):
            update_data["skills"] = new_skills

        # Only update summary if candidate has none
        if extracted.get("summary") and not candidate.get("summary"):
            update_data["summary"] = extracted["summary"]

        if extracted.get("experience_years") and not candidate.get("experience_years"):
            update_data["experience_years"] = extracted["experience_years"]

        # Direct update by ID — no upsert, no insert
        supabase.table("candidates").update(update_data).eq("id", candidate_id).execute()

        return {
            "success": True,
            "message": "CV uploaded and text extracted successfully",
            "extracted_skills": new_skills,
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

    raise HTTPException(
        status_code=500,
        detail="PDF parsing library not available. Add pdfplumber to requirements.txt"
    )


async def extract_skills_from_cv(cv_text: str) -> dict:
    """Use AI to extract structured info from CV text."""
    try:
        from langchain_core.messages import HumanMessage

        prompt = f"""Extract information from this CV/Resume.
Return ONLY valid JSON with no markdown, no explanation:
{{
  "skills": ["skill1", "skill2"],
  "summary": "2-3 sentence professional summary",
  "experience_years": 5
}}

CV TEXT:
{cv_text[:4000]}"""

        llm = None
        if settings.google_api_key:
            from langchain_google_genai import ChatGoogleGenerativeAI
            llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash-lite",
                google_api_key=settings.google_api_key,
                temperature=0
            )
        elif settings.groq_api_key:
            from langchain_groq import ChatGroq
            llm = ChatGroq(
                model="llama-3.3-70b-versatile",
                groq_api_key=settings.groq_api_key,
                temperature=0
            )

        if llm:
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            text = response.content.strip().replace("```json", "").replace("```", "").strip()
            return json.loads(text)

    except Exception as e:
        logger.warning(f"AI extraction failed, using keyword fallback: {e}")

    # Fallback — basic keyword extraction
    from agent.tools.matcher import COMMON_TECH_SKILLS
    text_lower = cv_text.lower()
    skills = [s for s in COMMON_TECH_SKILLS if s in text_lower]
    return {"skills": skills, "summary": "", "experience_years": 0}


# ─── Search Jobs (Step 1) ─────────────────────────────────────────────────────

@app.post("/search/jobs")
async def search_and_score_jobs(req: SearchRequest):
    """
    Step 1 — Search jobs across all portals and score each against candidate.
    Returns all jobs with match scores. Does NOT apply yet.
    User reviews, then calls /search/apply.
    """
    candidate = get_candidate(req.candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    session = create_session(
        req.candidate_id, req.job_query,
        ["naukri", "linkedin", "indeed", "instahyre", "adzuna"]
    )
    session_id = session.get("id", "")

    try:
        from agent.tools.job_search import (
            search_adzuna, search_naukri, search_indeed,
            search_instahyre, search_linkedin, fetch_job_description
        )
        from agent.tools.matcher import extract_keywords_from_jd, score_match

        # Search all portals
        all_jobs = []
        all_jobs.extend(search_adzuna(req.job_query, req.location))
        all_jobs.extend(search_naukri(req.job_query, req.location))
        all_jobs.extend(search_indeed(req.job_query, req.location))
        all_jobs.extend(search_instahyre(req.job_query, req.location))
        all_jobs.extend(search_linkedin(req.job_query, req.location))

        # Deduplicate by title + company
        seen = set()
        unique_jobs = []
        for job in all_jobs:
            key = f"{job['title'].lower()}_{job['company'].lower()}"
            if key not in seen:
                seen.add(key)
                unique_jobs.append(job)

        logger.info(f"Total unique jobs: {len(unique_jobs)}")

        # Score each job against candidate (top 40)
        scored_jobs = []
        for job in unique_jobs[:40]:
            try:
                jd_text = job.get("description", "")
                if len(jd_text) < 200 and job.get("apply_url"):
                    jd_text = fetch_job_description(job["apply_url"], job["portal"])

                kw = extract_keywords_from_jd(jd_text or job.get("title", ""))
                match = score_match(candidate, kw)

                # Save job to DB
                saved = save_job(job)
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
                scored_jobs.append({
                    **job,
                    "job_id": "",
                    "match_score": 0,
                    "recommendation": "SKIP"
                })

        # Sort by score descending
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
    Step 2 — Auto-apply to the matched job IDs in background.
    """
    candidate = get_candidate(req.candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    async def run_apply():
        try:
            response, _ = await run_auto_apply(
                candidate=candidate,
                job_ids=req.job_ids,
                session_id=req.session_id,
            )
            complete_session(req.session_id, {
                "status": "COMPLETED",
                "jobs_applied": len(req.job_ids),
                "notes": response[:500]
            })
        except Exception as e:
            logger.error(f"Auto-apply failed: {e}")
            complete_session(req.session_id, {
                "status": "FAILED",
                "notes": str(e)[:500]
            })

    background_tasks.add_task(run_apply)

    return {
        "success": True,
        "session_id": req.session_id,
        "jobs_to_apply": len(req.job_ids),
        "message": f"Auto-applying to {len(req.job_ids)} jobs in background"
    }


# ─── Applications Dashboard ───────────────────────────────────────────────────

@app.get("/applications/me")
async def get_candidate_applications(user: dict = Depends(get_current_user)):
    candidate_id = get_candidate_id_for_user(user)
    apps = get_applications(candidate_id)
    summary = {
        "total": len(apps),
        "applied": len([a for a in apps if a["status"] == "APPLIED"]),
        "failed": len([a for a in apps if a["status"] == "FAILED"]),
        "skipped": len([a for a in apps if a["status"] == "SKIPPED"]),
        "interview": len([a for a in apps if a["status"] == "INTERVIEW"]),
    }
    return {"summary": summary, "applications": apps}



# ─── Resume Download ──────────────────────────────────────────────────────────

@app.get("/resume/{resume_id}/download")
async def download_resume(resume_id: str):
    """Download a generated resume PDF by resume ID."""
    from fastapi.responses import FileResponse
    from db.supabase_client import get_resume
    import os

    resume = get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    pdf_path = resume.get("pdf_path", "")
    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(
            status_code=404,
            detail=f"PDF file not found on disk. Note: files are lost on Render redeploy — re-run auto-apply to regenerate."
        )

    filename = os.path.basename(pdf_path)
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.get("/resume/{resume_id}/view")
async def view_resume(resume_id: str):
    """View a resume PDF inline in browser."""
    from fastapi.responses import FileResponse
    from db.supabase_client import get_resume
    import os

    resume = get_resume(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    pdf_path = resume.get("pdf_path", "")
    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF file not on disk — re-run auto-apply to regenerate")

    filename = os.path.basename(pdf_path)
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=filename,
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )


@app.get("/resumes/me")
async def list_resumes(user: dict = Depends(get_current_user)):
    """List all resumes for a candidate with download links."""
    import os
    candidate_id = get_candidate_id_for_user(user)
    try:
        r = supabase.table("resumes").select(
            "id, job_id, match_score, pdf_path, created_at, jobs(title, company, portal)"
        ).eq("candidate_id", candidate_id).order("created_at", desc=True).execute()

        resumes = []
        for resume in (r.data or []):
            pdf_path = resume.get("pdf_path", "")
            resumes.append({
                **resume,
                "file_exists": bool(pdf_path and os.path.exists(pdf_path)),
                "download_url": f"/resume/{resume['id']}/download",
                "view_url": f"/resume/{resume['id']}/view",
            })

        return {"resumes": resumes, "total": len(resumes)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
