from supabase import create_client, Client
from config import get_settings
from loguru import logger
from datetime import datetime, timezone

settings = get_settings()
supabase: Client = create_client(settings.supabase_url, settings.supabase_service_key)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Candidates ───────────────────────────────────────────────────────────────

async def get_candidate(candidate_id: str) -> dict | None:
    try:
        r = supabase.table("candidates").select("*").eq("id", candidate_id).single().execute()
        return r.data
    except Exception as e:
        logger.error(f"get_candidate error: {e}")
        return None

async def upsert_candidate(data: dict) -> dict:
    try:
        data["updated_at"] = now_iso()
        r = supabase.table("candidates").upsert(data).execute()
        return r.data[0] if r.data else {}
    except Exception as e:
        logger.error(f"upsert_candidate error: {e}")
        return {}


# ─── Jobs ─────────────────────────────────────────────────────────────────────

async def save_job(data: dict) -> dict:
    try:
        r = supabase.table("jobs").upsert(data, on_conflict="portal,external_id").execute()
        return r.data[0] if r.data else {}
    except Exception as e:
        logger.error(f"save_job error: {e}")
        return {}

async def get_jobs(candidate_id: str) -> list:
    try:
        r = supabase.table("jobs").select("*").eq("is_active", True).execute()
        return r.data or []
    except Exception as e:
        logger.error(f"get_jobs error: {e}")
        return []


# ─── Resumes ──────────────────────────────────────────────────────────────────

async def save_resume(data: dict) -> dict:
    try:
        r = supabase.table("resumes").insert(data).execute()
        return r.data[0] if r.data else {}
    except Exception as e:
        logger.error(f"save_resume error: {e}")
        return {}

async def get_resume(resume_id: str) -> dict | None:
    try:
        r = supabase.table("resumes").select("*").eq("id", resume_id).single().execute()
        return r.data
    except:
        return None


# ─── Applications ─────────────────────────────────────────────────────────────

async def save_application(data: dict) -> dict:
    try:
        if data.get("applied_at") == "NOW()":
            data["applied_at"] = now_iso()
        data["last_updated"] = now_iso()
        r = supabase.table("applications").upsert(data).execute()
        return r.data[0] if r.data else {}
    except Exception as e:
        logger.error(f"save_application error: {e}")
        return {}

async def update_application_status(app_id: str, status: str, notes: str = None, error: str = None):
    try:
        data = {"status": status, "last_updated": now_iso()}
        if notes:
            data["notes"] = notes
        if error:
            data["error_message"] = error
        if status == "APPLIED":
            data["applied_at"] = now_iso()
        supabase.table("applications").update(data).eq("id", app_id).execute()
    except Exception as e:
        logger.error(f"update_application_status error: {e}")

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
    try:
        r = supabase.table("portal_accounts").upsert(
            data, on_conflict="candidate_id,portal"
        ).execute()
        return r.data[0] if r.data else {}
    except Exception as e:
        logger.error(f"save_portal_account error: {e}")
        return {}

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
    try:
        r = supabase.table("search_sessions").insert({
            "candidate_id": candidate_id,
            "search_query": query,
            "portals": portals,
            "status": "RUNNING",
            "started_at": now_iso(),
        }).execute()
        return r.data[0] if r.data else {}
    except Exception as e:
        logger.error(f"create_session error: {e}")
        return {}

async def update_session(session_id: str, data: dict) -> None:
    try:
        supabase.table("search_sessions").update(data).eq("id", session_id).execute()
    except Exception as e:
        logger.error(f"update_session error: {e}")

async def complete_session(session_id: str, stats: dict) -> None:
    try:
        update_data = {k: v for k, v in stats.items() if v != "NOW()"}
        update_data["completed_at"] = now_iso()
        update_data["status"] = stats.get("status", "COMPLETED")
        if "notes" in stats:
            update_data["notes"] = str(stats["notes"])[:500]
        supabase.table("search_sessions").update(update_data).eq("id", session_id).execute()
    except Exception as e:
        logger.error(f"complete_session error: {e}")
