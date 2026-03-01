"""
JD Analyser + Candidate Matcher
Extracts keywords from JD and scores against candidate profile.
"""

from langchain_core.tools import tool
from loguru import logger
import json
import re


# ─── Keyword Extraction ───────────────────────────────────────────────────────

COMMON_TECH_SKILLS = {
    # Languages
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "rust",
    "kotlin", "swift", "ruby", "php", "scala", "r", "matlab",
    # Frontend
    "react", "vue", "angular", "nextjs", "html", "css", "tailwind",
    "redux", "graphql", "webpack",
    # Backend
    "fastapi", "django", "flask", "nodejs", "express", "spring", "rails",
    "rest api", "microservices", "grpc",
    # Cloud & DevOps
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "ci/cd",
    "jenkins", "github actions", "linux", "nginx",
    # Databases
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "supabase",
    "dynamodb", "cassandra", "sqlite",
    # AI/ML
    "machine learning", "deep learning", "nlp", "pytorch", "tensorflow",
    "scikit-learn", "langchain", "llm", "openai", "transformers",
    # Tools
    "git", "jira", "agile", "scrum", "figma",
}

SOFT_SKILLS = {
    "communication", "leadership", "teamwork", "problem solving",
    "analytical", "collaboration", "presentation", "mentoring",
}


def extract_keywords_from_jd(jd_text: str) -> dict:
    """Extract structured keywords and requirements from JD text."""
    text_lower = jd_text.lower()

    # Extract tech skills
    tech_skills = [skill for skill in COMMON_TECH_SKILLS if skill in text_lower]

    # Extract experience requirement
    exp_pattern = r'(\d+)\s*[\+\-]?\s*(?:to\s*(\d+))?\s*years?\s*(?:of\s+)?(?:experience|exp)'
    exp_matches = re.findall(exp_pattern, text_lower)
    experience_required = None
    if exp_matches:
        min_exp = int(exp_matches[0][0])
        max_exp = int(exp_matches[0][1]) if exp_matches[0][1] else min_exp + 3
        experience_required = f"{min_exp}-{max_exp} years"

    # Extract must-have vs nice-to-have
    must_have = []
    nice_to_have = []

    lines = jd_text.split('\n')
    in_required = False
    in_preferred = False

    for line in lines:
        line_lower = line.lower()
        if any(k in line_lower for k in ["required", "must have", "mandatory", "essential", "you will need"]):
            in_required = True
            in_preferred = False
        elif any(k in line_lower for k in ["preferred", "nice to have", "good to have", "bonus", "plus"]):
            in_preferred = True
            in_required = False

        for skill in COMMON_TECH_SKILLS:
            if skill in line_lower:
                if in_preferred:
                    if skill not in nice_to_have:
                        nice_to_have.append(skill)
                else:
                    if skill not in must_have:
                        must_have.append(skill)

    # Fallback — all skills are must-have if no section headers
    if not must_have and not nice_to_have:
        must_have = tech_skills

    # Extract role level
    level = "mid"
    if any(k in text_lower for k in ["senior", "lead", "principal", "staff", "architect"]):
        level = "senior"
    elif any(k in text_lower for k in ["junior", "fresher", "entry", "associate", "trainee"]):
        level = "junior"
    elif any(k in text_lower for k in ["manager", "director", "vp", "head of"]):
        level = "manager"

    # Extract job type
    job_type = "full-time"
    if "remote" in text_lower:
        job_type = "remote"
    elif "hybrid" in text_lower:
        job_type = "hybrid"

    return {
        "all_skills": tech_skills,
        "must_have": must_have,
        "nice_to_have": nice_to_have,
        "experience_required": experience_required,
        "level": level,
        "job_type": job_type,
    }


def score_match(candidate: dict, jd_keywords: dict) -> dict:
    """
    Score how well a candidate matches a JD.
    Returns score 0-100 and breakdown.
    """
    candidate_skills = [s.lower() for s in candidate.get("skills", [])]
    candidate_exp = candidate.get("experience_years", 0)

    # Get all candidate text for broader matching
    experience_text = " ".join([
        f"{e.get('role', '')} {e.get('description', '')} {' '.join(e.get('achievements', []))}"
        for e in candidate.get("experience", [])
    ]).lower()
    full_text = f"{experience_text} {' '.join(candidate_skills)} {candidate.get('summary', '').lower()}"

    must_have = jd_keywords.get("must_have", [])
    nice_to_have = jd_keywords.get("nice_to_have", [])
    all_skills = jd_keywords.get("all_skills", [])

    # Match must-have skills (70% weight)
    matched_must = [s for s in must_have if s in full_text]
    matched_nice = [s for s in nice_to_have if s in full_text]
    missing_must = [s for s in must_have if s not in full_text]
    missing_nice = [s for s in nice_to_have if s not in full_text]

    must_score = (len(matched_must) / max(len(must_have), 1)) * 70
    nice_score = (len(matched_nice) / max(len(nice_to_have), 1)) * 20 if nice_to_have else 20

    # Experience score (10% weight)
    exp_req_text = jd_keywords.get("experience_required", "")
    exp_score = 10
    if exp_req_text:
        exp_match = re.search(r'(\d+)', exp_req_text)
        if exp_match:
            req_exp = int(exp_match.group(1))
            if candidate_exp >= req_exp:
                exp_score = 10
            elif candidate_exp >= req_exp - 1:
                exp_score = 7
            else:
                exp_score = 3

    total_score = round(must_score + nice_score + exp_score, 1)

    return {
        "score": min(total_score, 100),
        "matched_must_have": matched_must,
        "matched_nice_to_have": matched_nice,
        "missing_must_have": missing_must,
        "missing_nice_to_have": missing_nice,
        "experience_match": exp_score == 10,
        "recommendation": "APPLY" if total_score >= 80 else "SKIP" if total_score < 60 else "REVIEW",
    }


# ─── LangChain Tools ──────────────────────────────────────────────────────────

@tool
def analyse_jd(jd_text: str, job_title: str = "") -> str:
    """
    Analyse a job description and extract all keywords, required skills,
    experience requirements, and classify must-have vs nice-to-have.

    Args:
        jd_text: Full job description text
        job_title: Job title for context

    Returns:
        Structured keywords and requirements extracted from JD
    """
    result = extract_keywords_from_jd(jd_text)
    result["job_title"] = job_title
    logger.info(f"JD Analysis: {len(result['all_skills'])} skills found, level={result['level']}")
    return json.dumps(result)


@tool
def match_candidate_to_jd(
    candidate_json: str,
    jd_keywords_json: str
) -> str:
    """
    Score how well a candidate matches a job description.
    Returns match score 0-100 and detailed breakdown.
    Only scores >= 80 should be auto-applied.

    Args:
        candidate_json: JSON string of candidate profile
        jd_keywords_json: JSON string of JD keywords from analyse_jd

    Returns:
        Match score with breakdown — matched skills, missing skills, recommendation
    """
    try:
        candidate = json.loads(candidate_json) if isinstance(candidate_json, str) else candidate_json
        jd_keywords = json.loads(jd_keywords_json) if isinstance(jd_keywords_json, str) else jd_keywords_json
        result = score_match(candidate, jd_keywords)
        logger.info(f"Match score: {result['score']} — {result['recommendation']}")
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e), "score": 0, "recommendation": "SKIP"})
