"""
Repository Tool
Tracks all jobs found, resumes created, applications submitted, portal accounts.
"""

from langchain_core.tools import tool
from loguru import logger
import json
import uuid
import asyncio
import re
from db.supabase_client import (
    save_job, save_resume, save_application, update_application_status,
    save_portal_account, get_portal_account, get_applications,
    already_applied, create_session, complete_session
)

UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)


def valid_uuid(value: str) -> str | None:
    """Return value if it's a valid UUID, else None."""
    if not value:
        return None
    # Accept full UUID or truncated hex (e.g. "235a3287") — pad to full UUID
    if UUID_RE.match(value.strip()):
        return value.strip()
    return None


def ensure_uuid(value: str, label: str = "id") -> str:
    """Return value if valid UUID, else generate a new one and log a warning."""
    checked = valid_uuid(value)
    if checked:
        return checked
    new_id = str(uuid.uuid4())
    logger.warning(f"⚠️ Invalid {label} '{value}' — generated fallback UUID: {new_id}")
    return new_id


def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@tool
def save_job_to_repo(job_json: str) -> str:
    """
    Save a job found during search to the repository.

    Args:
        job_json: Job details JSON

    Returns:
        Saved job with database ID
    """
    try:
        job = json.loads(job_json) if isinstance(job_json, str) else job_json
        saved = run_async(save_job(job))
        return json.dumps({"success": True, "job_id": saved.get("id"), "job": saved})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool
def save_resume_to_repo(
    candidate_id: str,
    job_id: str,
    match_score: float,
    matched_keywords: str,
    missing_keywords: str,
    resume_text: str,
    pdf_path: str,
    cover_letter: str
) -> str:
    """
    Save a tailored resume to the repository.

    Args:
        candidate_id: Candidate UUID
        job_id: Job UUID
        match_score: Match score 0-100
        matched_keywords: JSON list of matched keywords
        missing_keywords: JSON list of missing keywords
        resume_text: Full resume as plain text
        pdf_path: Path to generated PDF
        cover_letter: Generated cover letter text

    Returns:
        Saved resume with database ID (use this as resume_id in record_application)
    """
    try:
        # Validate UUIDs
        cid = ensure_uuid(candidate_id, "candidate_id")
        jid = ensure_uuid(job_id, "job_id")

        data = {
            "candidate_id": cid,
            "job_id": jid,
            "match_score": float(match_score) if match_score else 0.0,
            "matched_keywords": json.loads(matched_keywords) if isinstance(matched_keywords, str) and matched_keywords.startswith("[") else (matched_keywords if isinstance(matched_keywords, list) else []),
            "missing_keywords": json.loads(missing_keywords) if isinstance(missing_keywords, str) and missing_keywords.startswith("[") else (missing_keywords if isinstance(missing_keywords, list) else []),
            "resume_text": resume_text or "",
            "pdf_path": pdf_path or "",
            "cover_letter": cover_letter or "",
        }
        saved = run_async(save_resume(data))
        resume_id = saved.get("id", str(uuid.uuid4()))
        logger.info(f"✅ Resume saved: {resume_id} for job {jid}")
        return json.dumps({"success": True, "resume_id": resume_id})
    except Exception as e:
        logger.error(f"save_resume_to_repo error: {e}")
        return json.dumps({"success": False, "error": str(e), "resume_id": str(uuid.uuid4())})


@tool
def record_application(
    candidate_id: str,
    job_id: str,
    resume_id: str,
    portal: str,
    status: str,
    account_created: bool = False,
    application_ref: str = "",
    notes: str = "",
    error_message: str = ""
) -> str:
    """
    Record a job application in the repository.
    Status must be: APPLIED | FAILED | SKIPPED | PENDING

    Args:
        candidate_id: Candidate UUID
        job_id: Job UUID from the jobs table
        resume_id: Resume UUID from save_resume_to_repo result (must be full UUID)
        portal: Portal name (naukri/linkedin/indeed/instahyre/adzuna)
        status: Application status — APPLIED, FAILED, SKIPPED, or PENDING
        account_created: Whether a new portal account was created
        application_ref: Confirmation reference from portal (optional)
        notes: Any notes about the application (optional)
        error_message: Error message if failed (optional)

    Returns:
        Saved application record with application_id
    """
    try:
        # Validate all UUIDs — generate fallbacks if empty or malformed
        cid = ensure_uuid(candidate_id, "candidate_id")
        jid = ensure_uuid(job_id, "job_id")

        valid_statuses = {"APPLIED", "FAILED", "SKIPPED", "PENDING", "INTERVIEW", "OFFER"}
        clean_status = status.upper() if status else "FAILED"
        if clean_status not in valid_statuses:
            logger.warning(f"Unknown status '{status}' — defaulting to FAILED")
            clean_status = "FAILED"

        # Verify resume exists in DB before using as FK — if not, save a placeholder
        rid = valid_uuid(resume_id)
        if rid:
            from db.supabase_client import supabase as _supa
            try:
                check = _supa.table("resumes").select("id").eq("id", rid).execute()
                if not check.data:
                    logger.warning(f"resume_id {rid} not in DB yet — saving placeholder resume")
                    placeholder = run_async(save_resume({
                        "id": rid,
                        "candidate_id": cid,
                        "job_id": jid,
                        "match_score": 0,
                        "pdf_path": "",
                        "resume_text": "",
                        "cover_letter": "",
                        "matched_keywords": [],
                        "missing_keywords": [],
                    }))
                    if not placeholder.get("id"):
                        rid = None  # Give up on resume_id, save without it
            except Exception as e:
                logger.warning(f"Could not verify resume_id: {e}")
                rid = None
        else:
            logger.warning(f"Invalid resume_id '{resume_id}' — saving application without it")
            rid = None

        data = {
            "candidate_id": cid,
            "job_id": jid,
            "portal": portal or "unknown",
            "status": clean_status,
            "account_created": bool(account_created),
            "application_ref": str(application_ref or ""),
            "notes": str(notes or ""),
            "error_message": str(error_message or ""),
        }
        if rid:
            data["resume_id"] = rid

        saved = run_async(save_application(data))
        app_id = saved.get("id", "")
        logger.info(f"✅ Application recorded: {clean_status} | job={jid} | app={app_id}")
        return json.dumps({"success": True, "application_id": app_id, "status": clean_status})

    except Exception as e:
        logger.error(f"record_application error: {e}")
        return json.dumps({"success": False, "error": str(e)})


@tool
def save_portal_credentials(
    candidate_id: str,
    portal: str,
    username: str,
    password_enc: str
) -> str:
    """
    Save portal account credentials (encrypted) to repository.

    Args:
        candidate_id: Candidate UUID
        portal: Portal name
        username: Login username (usually email)
        password_enc: AES encrypted password

    Returns:
        Saved account record
    """
    try:
        cid = ensure_uuid(candidate_id, "candidate_id")
        data = {
            "candidate_id": cid,
            "portal": portal,
            "username": username,
            "password_enc": password_enc,
        }
        saved = run_async(save_portal_account(data))
        return json.dumps({"success": True, "account_id": saved.get("id")})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@tool
def get_portal_credentials(candidate_id: str, portal: str) -> str:
    """
    Get existing portal account credentials for a candidate.

    Args:
        candidate_id: Candidate UUID
        portal: Portal name

    Returns:
        Account credentials or null if not found
    """
    try:
        cid = ensure_uuid(candidate_id, "candidate_id")
        account = run_async(get_portal_account(cid, portal))
        if account:
            return json.dumps({"found": True, "account": account})
        return json.dumps({"found": False, "account": None})
    except Exception as e:
        return json.dumps({"found": False, "error": str(e)})


@tool
def check_already_applied(candidate_id: str, job_id: str) -> str:
    """
    Check if candidate has already applied to a job.

    Args:
        candidate_id: Candidate UUID
        job_id: Job UUID

    Returns:
        Boolean indicating if already applied
    """
    try:
        cid = ensure_uuid(candidate_id, "candidate_id")
        jid = valid_uuid(job_id)
        if not jid:
            return json.dumps({"already_applied": False})
        applied = run_async(already_applied(cid, jid))
        return json.dumps({"already_applied": applied})
    except Exception as e:
        return json.dumps({"already_applied": False, "error": str(e)})


@tool
def get_application_dashboard(candidate_id: str) -> str:
    """
    Get full application dashboard for a candidate.
    Shows all jobs applied, statuses, match scores.

    Args:
        candidate_id: Candidate UUID

    Returns:
        All applications with job details and resume match scores
    """
    try:
        cid = ensure_uuid(candidate_id, "candidate_id")
        apps = run_async(get_applications(cid))
        summary = {
            "total": len(apps),
            "applied": len([a for a in apps if a["status"] == "APPLIED"]),
            "failed": len([a for a in apps if a["status"] == "FAILED"]),
            "skipped": len([a for a in apps if a["status"] == "SKIPPED"]),
            "interview": len([a for a in apps if a["status"] == "INTERVIEW"]),
        }
        return json.dumps({"summary": summary, "applications": apps})
    except Exception as e:
        return json.dumps({"error": str(e), "applications": []})
