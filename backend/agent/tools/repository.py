"""
Repository Tool
Tracks all jobs found, resumes created, applications submitted, portal accounts.
"""

from langchain_core.tools import tool
from loguru import logger
import json
import asyncio
from db.supabase_client import (
    save_job, save_resume, save_application, update_application_status,
    save_portal_account, get_portal_account, get_applications,
    already_applied, create_session, complete_session
)


def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
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
        Saved resume with database ID
    """
    try:
        data = {
            "candidate_id": candidate_id,
            "job_id": job_id,
            "match_score": match_score,
            "matched_keywords": json.loads(matched_keywords) if isinstance(matched_keywords, str) else matched_keywords,
            "missing_keywords": json.loads(missing_keywords) if isinstance(missing_keywords, str) else missing_keywords,
            "resume_text": resume_text,
            "pdf_path": pdf_path,
            "cover_letter": cover_letter,
        }
        saved = run_async(save_resume(data))
        return json.dumps({"success": True, "resume_id": saved.get("id")})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


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
    Status: APPLIED | FAILED | SKIPPED | PENDING

    Args:
        candidate_id: Candidate UUID
        job_id: Job UUID
        resume_id: Resume UUID used
        portal: Portal name (naukri/linkedin/indeed/instahyre)
        status: Application status
        account_created: Whether a new portal account was created
        application_ref: Confirmation reference from portal
        notes: Any notes about the application
        error_message: Error if failed

    Returns:
        Saved application record
    """
    try:
        data = {
            "candidate_id": candidate_id,
            "job_id": job_id,
            "resume_id": resume_id,
            "portal": portal,
            "status": status,
            "account_created": account_created,
            "application_ref": application_ref,
            "notes": notes,
            "error_message": error_message,
        }
        if status == "APPLIED":
            data["applied_at"] = "NOW()"
        saved = run_async(save_application(data))
        return json.dumps({"success": True, "application_id": saved.get("id")})
    except Exception as e:
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
        data = {
            "candidate_id": candidate_id,
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
        Account credentials (encrypted password) or null if not found
    """
    try:
        account = run_async(get_portal_account(candidate_id, portal))
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
        applied = run_async(already_applied(candidate_id, job_id))
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
        apps = run_async(get_applications(candidate_id))
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
