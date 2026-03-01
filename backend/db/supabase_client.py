from supabase import create_client, Client
from config import get_settings
from loguru import logger

settings = get_settings()
supabase: Client = create_client(settings.supabase_url, settings.supabase_service_key)


# ─── Candidates ───────────────────────────────────────────────────────────────

async def get_candidate(candidate_id: str) -> dict | None:
    try:
        r = supabase.table("candidates").select("*").eq("id", candidate_id).single().execute()
        return r.data
    except Exception as e:
        logger.error(f"get_candidate error: {e}")
        return None

async def upsert_candidate(data: dict) -> dict:
    r = supabase.table("candidates").upsert(data).execute()
    return r.data[0] if r.data else {}


# ─── Jobs ─────────────────────────────────────────────────────────────────────

async def save_job(data: dict) -> dict:
    try:
        r = supabase.table("jobs").upsert(data, on_conflict="portal,external_id").execute()
        return r.data[0] if r.data else {}
    except Exception as e:
        logger.error(f"save_job error: {e}")
        return {}

async def get_jobs(candidate_id: str, status: str = None) -> list:
    try:
        q = supabase.table("jobs").select("*, applications(status)").eq("is_active", True)
        r = q.execute()
        return r.data or []
    except Exception as e:
        logger.error(f"get_jobs error: {e}")
        return []


# ─── Resumes ──────────────────────────────────────────────────────────────────

async def save_resume(data: dict) -> dict:
    r = supabase.table("resumes").insert(data).execute()
    return r.data[0] if r.data else {}

async def get_resume(resume_id: str) -> dict | None:
    try:
        r = supabase.table("resumes").select("*").eq("id", resume_id).single().execute()
        return r.data
    except:
        return None


# ─── Applications ─────────────────────────────────────────────────────────────

async def save_application(data: dict) -> dict:
    r = supabase.table("applications").upsert(data).execute()
    return r.data[0] if r.data else {}

async def update_application_status(app_id: str, status: str, notes: str = None, error: str = None):
    data = {"status": status, "last_updated": "NOW()"}
    if notes:
        data["notes"] = notes
    if error:
        data["error_message"] = error
    if status == "APPLIED":
        data["applied_at"] = "NOW()"
    supabase.table("applications").update(data).eq("id", app_id).execute()

async def get_applications(candidate_id: str) -> list:
    try:
        r = supabase.table("applications").select(
            "*, jobs(title, company, portal, apply_url), resumes(match_score, pdf_path)"
        ).eq("candidate_id", candidate_id).order("last_updated", desc=True).execute()
        return r.data or []
    except Exception as e:
        logger.error(f"get_applications error: {e}")
        return []

async def already_applied(candidate_id: str, job_id: str) -> bool:
    try:
        r = supabase.table("applications").select("id").eq(
            "candidate_id", candidate_id
        ).eq("job_id", job_id).execute()
        return len(r.data) > 0
    except:
        return False


# ─── Portal Accounts ──────────────────────────────────────────────────────────

async def save_portal_account(data: dict) -> dict:
    r = supabase.table("portal_accounts").upsert(
        data, on_conflict="candidate_id,portal"
    ).execute()
    return r.data[0] if r.data else {}

async def get_portal_account(candidate_id: str, portal: str) -> dict | None:
    try:
        r = supabase.table("portal_accounts").select("*").eq(
            "candidate_id", candidate_id
        ).eq("portal", portal).single().execute()
        return r.data
    except:
        return None


# ─── Search Sessions ──────────────────────────────────────────────────────────

async def create_session(candidate_id: str, query: str, portals: list) -> dict:
    r = supabase.table("search_sessions").insert({
        "candidate_id": candidate_id,
        "search_query": query,
        "portals": portals,
        "status": "RUNNING"
    }).execute()
    return r.data[0] if r.data else {}

async def update_session(session_id: str, data: dict):
    supabase.table("search_sessions").update(data).eq("id", session_id).execute()

async def complete_session(session_id: str, stats: dict):
    supabase.table("search_sessions").update({
        **stats,
        "status": "COMPLETED",
        "completed_at": "NOW()"
    }).eq("id", session_id).execute()
