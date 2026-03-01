"""
Job Search Tool
Searches jobs from: Adzuna API (free) + Naukri + LinkedIn + Indeed + Instahyre
"""

from langchain_core.tools import tool
from loguru import logger
import httpx
import json
import re
from config import get_settings

settings = get_settings()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


# ─── Adzuna API (Free — 1M calls/month) ──────────────────────────────────────

def search_adzuna(query: str, location: str = "india", pages: int = 3) -> list:
    """Search jobs via Adzuna free API."""
    if not settings.adzuna_app_id or not settings.adzuna_api_key:
        logger.warning("Adzuna API keys not set — skipping")
        return []

    jobs = []
    try:
        with httpx.Client(timeout=15) as client:
            for page in range(1, pages + 1):
                url = f"https://api.adzuna.com/v1/api/jobs/in/search/{page}"
                params = {
                    "app_id": settings.adzuna_app_id,
                    "app_key": settings.adzuna_api_key,
                    "what": query,
                    "where": location,
                    "results_per_page": 20,
                    "content-type": "application/json",
                }
                r = client.get(url, params=params)
                if r.status_code == 200:
                    data = r.json()
                    for job in data.get("results", []):
                        jobs.append({
                            "external_id": job.get("id", ""),
                            "portal": "adzuna",
                            "title": job.get("title", ""),
                            "company": job.get("company", {}).get("display_name", "Unknown"),
                            "location": job.get("location", {}).get("display_name", ""),
                            "description": job.get("description", ""),
                            "salary_min": job.get("salary_min"),
                            "salary_max": job.get("salary_max"),
                            "apply_url": job.get("redirect_url", ""),
                            "posted_date": job.get("created", ""),
                            "job_type": "full-time",
                        })
        logger.info(f"Adzuna: found {len(jobs)} jobs for '{query}'")
    except Exception as e:
        logger.error(f"Adzuna search error: {e}")
    return jobs


# ─── Naukri Scraper ───────────────────────────────────────────────────────────

def search_naukri(query: str, location: str = "") -> list:
    """Search Naukri.com jobs via their internal API."""
    jobs = []
    try:
        # Naukri has an internal search API
        url = "https://www.naukri.com/jobapi/v3/search"
        params = {
            "noOfResults": 20,
            "urlType": "search_by_keyword",
            "searchType": "adv",
            "keyword": query,
            "location": location,
            "pageNo": 1,
            "k": query,
            "l": location,
            "seoKey": query.lower().replace(" ", "-"),
            "src": "jobsearchDesk",
        }
        headers = {
            **HEADERS,
            "appid": "109",
            "systemid": "Naukri",
            "Referer": "https://www.naukri.com/",
        }
        with httpx.Client(timeout=15, headers=headers) as client:
            r = client.get(url, params=params)
            if r.status_code == 200:
                data = r.json()
                for job in data.get("jobDetails", []):
                    jobs.append({
                        "external_id": job.get("jobId", ""),
                        "portal": "naukri",
                        "title": job.get("title", ""),
                        "company": job.get("companyName", "Unknown"),
                        "location": ", ".join(job.get("placeholders", [{}])[0].get("label", "").split(",")[:2]),
                        "description": job.get("jobDescription", ""),
                        "experience_required": job.get("experienceText", ""),
                        "salary_min": None,
                        "salary_max": None,
                        "apply_url": f"https://www.naukri.com{job.get('jdURL', '')}",
                        "posted_date": job.get("createdDate", ""),
                        "job_type": "full-time",
                        "skills_required": job.get("tagsAndSkills", "").split(", ") if job.get("tagsAndSkills") else [],
                    })
        logger.info(f"Naukri: found {len(jobs)} jobs for '{query}'")
    except Exception as e:
        logger.error(f"Naukri search error: {e}")
    return jobs


# ─── Indeed Scraper ───────────────────────────────────────────────────────────

def search_indeed(query: str, location: str = "India") -> list:
    """Search Indeed India jobs."""
    jobs = []
    try:
        url = "https://in.indeed.com/jobs"
        params = {"q": query, "l": location, "format": "json"}
        with httpx.Client(timeout=15, headers=HEADERS, follow_redirects=True) as client:
            r = client.get(url, params=params)
            if r.status_code == 200:
                html = r.text
                # Extract job cards from HTML
                pattern = r'"jobkey":"([^"]+)".*?"displayTitle":"([^"]+)".*?"company":"([^"]+)".*?"formattedLocation":"([^"]+)"'
                matches = re.findall(pattern, html)
                for match in matches[:20]:
                    job_key, title, company, location_str = match
                    jobs.append({
                        "external_id": job_key,
                        "portal": "indeed",
                        "title": title,
                        "company": company,
                        "location": location_str,
                        "description": "",
                        "apply_url": f"https://in.indeed.com/viewjob?jk={job_key}",
                        "job_type": "full-time",
                    })
        logger.info(f"Indeed: found {len(jobs)} jobs for '{query}'")
    except Exception as e:
        logger.error(f"Indeed search error: {e}")
    return jobs


# ─── Instahyre Scraper ────────────────────────────────────────────────────────

def search_instahyre(query: str, location: str = "") -> list:
    """Search Instahyre jobs via their API."""
    jobs = []
    try:
        url = "https://www.instahyre.com/api/v1/opportunity/"
        params = {
            "format": "json",
            "search": query,
            "location": location,
            "page": 1,
        }
        with httpx.Client(timeout=15, headers=HEADERS) as client:
            r = client.get(url, params=params)
            if r.status_code == 200:
                data = r.json()
                for job in data.get("results", []):
                    employer = job.get("employer", {})
                    jobs.append({
                        "external_id": str(job.get("id", "")),
                        "portal": "instahyre",
                        "title": job.get("designation", ""),
                        "company": employer.get("name", "Unknown"),
                        "location": job.get("location", ""),
                        "description": job.get("description", ""),
                        "experience_required": f"{job.get('min_experience', 0)}-{job.get('max_experience', 10)} years",
                        "salary_min": job.get("min_ctc"),
                        "salary_max": job.get("max_ctc"),
                        "skills_required": [s.get("name") for s in job.get("skills", [])],
                        "apply_url": f"https://www.instahyre.com/jobs/{job.get('id', '')}",
                        "job_type": "full-time",
                    })
        logger.info(f"Instahyre: found {len(jobs)} jobs for '{query}'")
    except Exception as e:
        logger.error(f"Instahyre search error: {e}")
    return jobs


# ─── LinkedIn Scraper ─────────────────────────────────────────────────────────

def search_linkedin(query: str, location: str = "India") -> list:
    """Search LinkedIn public job listings."""
    jobs = []
    try:
        url = "https://www.linkedin.com/jobs/search/"
        params = {
            "keywords": query,
            "location": location,
            "f_TPR": "r86400",  # Last 24 hours
            "position": 1,
            "pageNum": 0,
        }
        with httpx.Client(timeout=15, headers=HEADERS, follow_redirects=True) as client:
            r = client.get(url, params=params)
            if r.status_code == 200:
                html = r.text
                # Extract job IDs from LinkedIn HTML
                job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
                titles = re.findall(r'class="base-search-card__title"[^>]*>\s*([^<]+)', html)
                companies = re.findall(r'class="base-search-card__subtitle"[^>]*>\s*<[^>]+>\s*([^<]+)', html)
                locations = re.findall(r'class="job-search-card__location"[^>]*>\s*([^<]+)', html)

                for i, job_id in enumerate(job_ids[:20]):
                    jobs.append({
                        "external_id": job_id,
                        "portal": "linkedin",
                        "title": titles[i].strip() if i < len(titles) else "Unknown",
                        "company": companies[i].strip() if i < len(companies) else "Unknown",
                        "location": locations[i].strip() if i < len(locations) else location,
                        "description": "",
                        "apply_url": f"https://www.linkedin.com/jobs/view/{job_id}",
                        "job_type": "full-time",
                    })
        logger.info(f"LinkedIn: found {len(jobs)} jobs for '{query}'")
    except Exception as e:
        logger.error(f"LinkedIn search error: {e}")
    return jobs


# ─── Fetch Full Job Description ───────────────────────────────────────────────

def fetch_job_description(apply_url: str, portal: str) -> str:
    """Fetch full JD from job URL."""
    try:
        with httpx.Client(timeout=15, headers=HEADERS, follow_redirects=True) as client:
            r = client.get(apply_url)
            if r.status_code == 200:
                html = r.text
                # Strip HTML tags
                text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
                text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
                text = re.sub(r'<[^>]+>', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                return text[:5000]  # First 5000 chars
    except Exception as e:
        logger.warning(f"Could not fetch JD from {apply_url}: {e}")
    return ""


# ─── LangChain Tool ───────────────────────────────────────────────────────────

@tool
def search_jobs(
    query: str,
    location: str = "India",
    portals: str = "naukri,linkedin,indeed,instahyre,adzuna"
) -> str:
    """
    Search for jobs across multiple portals based on skills/role query.

    Args:
        query: Job title or skills e.g. 'Python Developer', 'React Frontend Engineer'
        location: Location filter e.g. 'Bangalore', 'Mumbai', 'Remote'
        portals: Comma-separated portals to search

    Returns:
        JSON list of jobs found with titles, companies, URLs
    """
    portal_list = [p.strip().lower() for p in portals.split(",")]
    all_jobs = []

    if "adzuna" in portal_list:
        all_jobs.extend(search_adzuna(query, location))
    if "naukri" in portal_list:
        all_jobs.extend(search_naukri(query, location))
    if "indeed" in portal_list:
        all_jobs.extend(search_indeed(query, location))
    if "instahyre" in portal_list:
        all_jobs.extend(search_instahyre(query, location))
    if "linkedin" in portal_list:
        all_jobs.extend(search_linkedin(query, location))

    # Deduplicate by title+company
    seen = set()
    unique_jobs = []
    for job in all_jobs:
        key = f"{job['title'].lower()}_{job['company'].lower()}"
        if key not in seen:
            seen.add(key)
            unique_jobs.append(job)

    logger.info(f"Total unique jobs found: {len(unique_jobs)}")
    return json.dumps({
        "query": query,
        "location": location,
        "total_found": len(unique_jobs),
        "jobs": unique_jobs[:50]  # Return top 50
    })


@tool
def fetch_full_jd(apply_url: str, portal: str = "unknown") -> str:
    """
    Fetch the complete job description from a job URL.

    Args:
        apply_url: Full URL of the job posting
        portal: Portal name for context

    Returns:
        Full job description text
    """
    jd = fetch_job_description(apply_url, portal)
    return json.dumps({
        "url": apply_url,
        "jd_text": jd,
        "length": len(jd)
    })
