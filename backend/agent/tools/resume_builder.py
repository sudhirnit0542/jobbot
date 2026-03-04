"""
Resume Builder
Builds tailored PDF resume by:
1. Parsing the uploaded CV (base_resume_text) to extract full work history, education, projects
2. Merging with structured profile data (skills, contact info)
3. Reordering skills to match JD keywords for ATS
4. Generating clean PDF with xhtml2pdf
"""

from langchain_core.tools import tool
from loguru import logger
import json
import os
import uuid
import re

RESUME_DIR = "/tmp/resumes"
os.makedirs(RESUME_DIR, exist_ok=True)


# ─── CV Text Parser ───────────────────────────────────────────────────────────

def parse_cv_text(cv_text: str) -> dict:
    """
    Parse raw CV/resume text into structured sections.
    Handles most common resume formats.
    Returns: {summary, experience, education, certifications, projects, skills_raw}
    """
    if not cv_text:
        return {}

    # Strip the PDF: prefix added during upload
    text = cv_text.replace("PDF:", "", 1).strip()
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    parsed = {
        "raw_text": text,
        "summary": "",
        "experience": [],
        "education": [],
        "certifications": [],
        "projects": [],
        "skills_raw": [],
    }

    # Section header patterns
    SECTION_PATTERNS = {
        "summary":        r"(summary|profile|objective|about|overview)",
        "experience":     r"(experience|employment|work history|career|positions?)",
        "education":      r"(education|academic|qualification|degree)",
        "certifications": r"(certif|license|credential|award)",
        "projects":       r"(project|portfolio|work sample)",
        "skills":         r"(skill|technical|competenc|expertise|technology)",
    }

    current_section = None
    current_block = []

    def flush_block():
        if not current_block or not current_section:
            return
        block_text = "\n".join(current_block).strip()
        if current_section == "summary":
            parsed["summary"] = block_text
        elif current_section == "experience":
            parsed["experience"].append(block_text)
        elif current_section == "education":
            parsed["education"].append(block_text)
        elif current_section in ("certifications", "projects"):
            items = [l for l in current_block if l]
            parsed[current_section].extend(items)
        elif current_section == "skills":
            # Extract individual skills from comma/bullet separated text
            skills_text = " ".join(current_block)
            skills = re.split(r"[,•·|/\n\t]+", skills_text)
            parsed["skills_raw"].extend([s.strip() for s in skills if 2 < len(s.strip()) < 40])

    for line in lines:
        line_lower = line.lower().strip(":#- ")

        # Check if this line is a section header
        matched_section = None
        for sec, pattern in SECTION_PATTERNS.items():
            if re.match(pattern, line_lower) and len(line) < 50:
                matched_section = sec
                break

        if matched_section:
            flush_block()
            current_section = matched_section
            current_block = []
        elif current_section:
            current_block.append(line)

    flush_block()

    # Parse experience blocks into structured dicts
    structured_exp = []
    for exp_block in parsed["experience"]:
        exp_lines = [l.strip() for l in exp_block.split("\n") if l.strip()]
        if not exp_lines:
            continue

        exp_entry = {
            "role": "",
            "company": "",
            "duration": "",
            "description": "",
            "achievements": [],
        }

        # First line usually: "Role at Company" or "Role | Company | Duration"
        if exp_lines:
            first = exp_lines[0]
            # Try "Role at Company — Duration" pattern
            at_match = re.match(r"(.+?)\s+(?:at|@|,)\s+(.+?)(?:\s+[|–—-]\s+(.+))?$", first, re.I)
            pipe_match = re.match(r"(.+?)\s*[|/]\s*(.+?)\s*[|/]\s*(.+)", first)
            if at_match:
                exp_entry["role"] = at_match.group(1).strip()
                exp_entry["company"] = at_match.group(2).strip()
                exp_entry["duration"] = (at_match.group(3) or "").strip()
            elif pipe_match:
                exp_entry["role"] = pipe_match.group(1).strip()
                exp_entry["company"] = pipe_match.group(2).strip()
                exp_entry["duration"] = pipe_match.group(3).strip()
            else:
                exp_entry["role"] = first

        # Remaining lines → description and achievements
        remaining = exp_lines[1:]
        bullets = [l for l in remaining if l.startswith(("•", "-", "*", "·")) or l[0:1].isupper()]
        non_bullets = [l for l in remaining if l not in bullets]

        exp_entry["description"] = " ".join(non_bullets[:2])
        exp_entry["achievements"] = [
            re.sub(r"^[•\-\*·]\s*", "", b) for b in bullets[:6]
        ]

        if exp_entry["role"] or exp_entry["company"]:
            structured_exp.append(exp_entry)

    parsed["experience_structured"] = structured_exp

    # Parse education blocks
    structured_edu = []
    for edu_block in parsed["education"]:
        edu_lines = [l.strip() for l in edu_block.split("\n") if l.strip()]
        if not edu_lines:
            continue
        entry = {"degree": edu_lines[0] if edu_lines else "",
                 "institution": edu_lines[1] if len(edu_lines) > 1 else "",
                 "year": "", "grade": ""}
        # Look for year pattern
        for line in edu_lines:
            year_match = re.search(r"\b(19|20)\d{2}\b", line)
            if year_match:
                entry["year"] = year_match.group(0)
            grade_match = re.search(r"\b(\d+\.?\d*\s*(?:GPA|CGPA|%|grade)|\b[A-F][+-]?\b)", line, re.I)
            if grade_match:
                entry["grade"] = grade_match.group(0)
        structured_edu.append(entry)
    parsed["education_structured"] = structured_edu

    return parsed


def merge_candidate_with_cv(candidate: dict, jd_keywords: dict, match_result: dict) -> dict:
    """
    Merge structured profile data with parsed CV text.
    CV text is the source of truth for experience/education.
    Profile data is used for contact info and skills.
    JD keywords are used to reorder/augment skills.
    """
    merged = dict(candidate)

    cv_text = candidate.get("base_resume_text", "")
    if cv_text and len(cv_text) > 100:
        logger.info(f"Parsing CV text ({len(cv_text)} chars) to extract full work history")
        cv_data = parse_cv_text(cv_text)

        # Use CV experience if richer than profile
        cv_exp = cv_data.get("experience_structured", [])
        profile_exp = candidate.get("experience", [])
        if len(cv_exp) >= len(profile_exp):
            merged["experience"] = cv_exp
            logger.info(f"Using CV experience: {len(cv_exp)} roles extracted")
        else:
            logger.info(f"Using profile experience: {len(profile_exp)} roles")

        # Use CV education if richer
        cv_edu = cv_data.get("education_structured", [])
        profile_edu = candidate.get("education", [])
        if len(cv_edu) >= len(profile_edu):
            merged["education"] = cv_edu

        # Use CV summary if profile has none
        if not merged.get("summary") and cv_data.get("summary"):
            merged["summary"] = cv_data["summary"]

        # Merge skills: profile skills + CV-extracted skills, deduplicated
        profile_skills = candidate.get("skills", [])
        cv_skills = cv_data.get("skills_raw", [])
        all_skills = list(dict.fromkeys(  # preserves order, deduplicates
            [s for s in profile_skills] +
            [s for s in cv_skills if s not in profile_skills]
        ))
        merged["skills"] = all_skills[:40]  # Cap at 40 before JD reordering

        # Merge certifications
        profile_certs = candidate.get("certifications", [])
        cv_certs = cv_data.get("certifications", [])
        merged["certifications"] = list(dict.fromkeys(profile_certs + cv_certs))

        # Merge projects
        cv_projects = cv_data.get("projects", [])
        merged["projects"] = cv_projects

    # Reorder skills: JD-matched first, then rest
    jd_must = set(s.lower() for s in jd_keywords.get("must_have", []))
    jd_nice = set(s.lower() for s in jd_keywords.get("nice_to_have", []))
    matched_keys = set(s.lower() for s in (
        match_result.get("matched_must_have", []) +
        match_result.get("matched_nice_to_have", [])
    ))

    all_skills = merged.get("skills", [])
    # Priority 1: matched JD must-haves
    tier1 = [s for s in all_skills if s.lower() in jd_must or s.lower() in matched_keys]
    # Priority 2: matched nice-to-haves
    tier2 = [s for s in all_skills if s.lower() in jd_nice and s not in tier1]
    # Priority 3: rest
    tier3 = [s for s in all_skills if s not in tier1 and s not in tier2]
    merged["skills"] = (tier1 + tier2 + tier3)[:25]

    logger.info(
        f"Skills ordered: {len(tier1)} JD-matched | {len(tier2)} nice-to-have | {len(tier3)} other"
    )

    return merged


# ─── HTML Resume Builder ──────────────────────────────────────────────────────

def build_tailored_resume_html(candidate: dict, jd_keywords: dict, match_result: dict) -> str:
    """Build ATS-optimised HTML resume from merged candidate + CV data."""

    # Merge CV data into candidate profile
    merged = merge_candidate_with_cv(candidate, jd_keywords, match_result)

    name       = merged.get("name", "")
    email      = merged.get("email", "")
    phone      = merged.get("phone", "")
    location   = merged.get("location", "")
    linkedin   = merged.get("linkedin_url", "")
    github     = merged.get("github_url", "")
    summary    = merged.get("summary", "")
    skills     = merged.get("skills", [])
    experience = merged.get("experience", [])
    education  = merged.get("education", [])
    certs      = merged.get("certifications", [])
    projects   = merged.get("projects", [])

    skills_html = "".join(f'<span class="skill">{s}</span>' for s in skills)

    # Experience HTML
    exp_html = ""
    for exp in experience:
        if isinstance(exp, str):
            # Raw text block from CV parser fallback
            exp_html += f'<div class="exp-item"><p class="exp-desc">{exp}</p></div>'
            continue
        achievements = exp.get("achievements", [])
        ach_html = "".join(f"<li>{a}</li>" for a in achievements if a)
        exp_html += f"""
        <div class="exp-item">
          <div class="exp-header">
            <div class="exp-left">
              <div class="exp-role">{exp.get('role','')}</div>
              <div class="exp-company">{exp.get('company','')}</div>
            </div>
            <div class="exp-duration">{exp.get('duration','')}</div>
          </div>
          {"<p class='exp-desc'>" + exp.get('description','') + "</p>" if exp.get('description') else ""}
          {"<ul class='achievements'>" + ach_html + "</ul>" if ach_html else ""}
        </div>"""

    # Education HTML
    edu_html = ""
    for edu in education:
        if isinstance(edu, str):
            edu_html += f'<div class="edu-item"><div class="edu-degree">{edu}</div></div>'
            continue
        edu_html += f"""
        <div class="edu-item">
          <div class="edu-degree">{edu.get('degree','')}</div>
          <div class="edu-inst">{edu.get('institution','')} {('&mdash; ' + edu.get('year','')) if edu.get('year') else ''}</div>
          {f"<div class='edu-grade'>{edu.get('grade','')}</div>" if edu.get('grade') else ""}
        </div>"""

    cert_html = "".join(f"<li>{c}</li>" for c in certs if c)
    project_html = "".join(
        f'<div class="exp-item"><div class="exp-role">{p}</div></div>'
        if isinstance(p, str) else
        f'<div class="exp-item"><div class="exp-role">{p.get("name","")}</div><p class="exp-desc">{p.get("description","")}</p></div>'
        for p in projects
    )

    contact_parts = [x for x in [phone, location] if x]
    if linkedin: contact_parts.append(f"LinkedIn: {linkedin}")
    if github:   contact_parts.append(f"GitHub: {github}")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"/>
<style>
  @page {{ margin: 1.8cm 2cm; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: Arial, Helvetica, sans-serif; font-size: 10.5pt; color: #1a1a1a; line-height: 1.45; }}
  .header {{ border-bottom: 2.5pt solid #1a5276; padding-bottom: 10pt; margin-bottom: 14pt; }}
  .name {{ font-size: 20pt; font-weight: bold; color: #1a5276; letter-spacing: 0.5pt; }}
  .contact {{ margin-top: 4pt; color: #444; font-size: 9.5pt; }}
  .email {{ margin-top: 2pt; color: #444; font-size: 9.5pt; }}
  .section {{ margin-bottom: 14pt; page-break-inside: avoid; }}
  .section-title {{ font-size: 11pt; font-weight: bold; color: #1a5276; text-transform: uppercase;
                    letter-spacing: 1pt; border-bottom: 0.75pt solid #aed6f1;
                    padding-bottom: 2pt; margin-bottom: 7pt; }}
  .summary {{ color: #333; text-align: justify; }}
  .skill {{ display: inline-block; background: #eaf4fb; border: 0.5pt solid #aed6f1;
            border-radius: 2pt; padding: 1.5pt 7pt; font-size: 9pt; color: #1a5276; margin: 2pt 3pt 2pt 0; }}
  .exp-item {{ margin-bottom: 10pt; }}
  .exp-header {{ overflow: hidden; margin-bottom: 2pt; }}
  .exp-left {{ float: left; }}
  .exp-role {{ font-weight: bold; font-size: 11pt; }}
  .exp-company {{ color: #555; font-style: italic; font-size: 10pt; }}
  .exp-duration {{ float: right; color: #555; font-size: 9.5pt; }}
  .exp-desc {{ color: #444; margin: 3pt 0; clear: both; }}
  .achievements {{ padding-left: 16pt; color: #333; margin-top: 3pt; }}
  .achievements li {{ margin-bottom: 2pt; }}
  .edu-item {{ margin-bottom: 7pt; }}
  .edu-degree {{ font-weight: bold; }}
  .edu-inst {{ color: #555; font-size: 10pt; }}
  .edu-grade {{ color: #666; font-size: 9.5pt; }}
  ul.cert-list {{ padding-left: 16pt; }}
  ul.cert-list li {{ margin-bottom: 2pt; }}
  .clearfix {{ clear: both; }}
</style>
</head>
<body>

<div class="header">
  <div class="name">{name}</div>
  <div class="contact">{" &nbsp;|&nbsp; ".join(contact_parts)}</div>
  <div class="email">{email}</div>
</div>

{"<div class='section'><div class='section-title'>Professional Summary</div><p class='summary'>" + summary + "</p></div>" if summary else ""}

{"<div class='section'><div class='section-title'>Technical Skills</div><div>" + skills_html + "</div><div class='clearfix'></div></div>" if skills else ""}

{"<div class='section'><div class='section-title'>Professional Experience</div>" + exp_html + "</div>" if exp_html else ""}

{"<div class='section'><div class='section-title'>Projects</div>" + project_html + "</div>" if project_html else ""}

{"<div class='section'><div class='section-title'>Education</div>" + edu_html + "</div>" if edu_html else ""}

{"<div class='section'><div class='section-title'>Certifications</div><ul class='cert-list'>" + cert_html + "</ul></div>" if cert_html else ""}

</body>
</html>"""


def html_to_pdf(html_content: str, output_path: str) -> bool:
    try:
        from xhtml2pdf import pisa
        with open(output_path, "wb") as f:
            result = pisa.CreatePDF(html_content, dest=f)
        if result.err:
            logger.error(f"xhtml2pdf errors: {result.err}")
            return False
        logger.info(f"PDF created: {output_path}")
        return True
    except ImportError:
        logger.warning("xhtml2pdf not available — saving HTML fallback")
    except Exception as e:
        logger.error(f"PDF generation error: {e}")
    # HTML fallback
    try:
        html_path = output_path.replace(".pdf", ".html")
        with open(html_path, "w") as f:
            f.write(html_content)
    except:
        pass
    return False


def generate_cover_letter(candidate: dict, job: dict, match_result: dict) -> str:
    name    = candidate.get("name", "Candidate")
    company = job.get("company", "Company")
    role    = job.get("title", "Role")
    matched = ", ".join(match_result.get("matched_must_have", [])[:5])
    years   = candidate.get("experience_years", 0)
    return f"""Dear Hiring Manager at {company},

I am excited to apply for the {role} position at {company}. With {years} years of hands-on experience in {matched}, I bring both technical depth and a proven track record of delivering results.

My background closely aligns with your requirements — I have worked extensively with the skills and technologies your team uses, and I am confident I can contribute meaningfully from day one.

I would love the opportunity to discuss how my experience can support {company}'s goals. Thank you for your time and consideration.

Best regards,
{name}
{candidate.get('email', '')}
{candidate.get('phone', '')}"""


# ─── Main Tool ────────────────────────────────────────────────────────────────

@tool
def build_resume(
    candidate_json: str,
    job_json: str,
    jd_keywords_json: str,
    match_result_json: str
) -> str:
    """
    Build a tailored PDF resume for a specific job.

    Sources used (in priority order):
    1. Uploaded CV text (base_resume_text) — full work history, education, projects
    2. Structured profile data — contact info, skills, certifications
    3. JD keywords — used to reorder skills for ATS optimisation

    Args:
        candidate_json: Full candidate profile JSON (must include base_resume_text if CV uploaded)
        job_json: Job details (title, company, portal, apply_url)
        jd_keywords_json: Keywords extracted from JD {"must_have": [], "nice_to_have": []}
        match_result_json: Match result {"matched_must_have": [], "matched_nice_to_have": []}

    Returns:
        JSON with pdf_path, resume_id (full UUID), cover_letter, matched_keywords_used
    """
    try:
        candidate    = json.loads(candidate_json)    if isinstance(candidate_json, str)    else candidate_json
        job          = json.loads(job_json)          if isinstance(job_json, str)          else job_json
        jd_keywords  = json.loads(jd_keywords_json)  if isinstance(jd_keywords_json, str)  else jd_keywords_json
        match_result = json.loads(match_result_json) if isinstance(match_result_json, str) else match_result_json

        has_cv = bool(candidate.get("base_resume_text", ""))
        logger.info(
            f"Building resume for {job.get('title')} at {job.get('company')} | "
            f"CV uploaded: {has_cv} | "
            f"Profile skills: {len(candidate.get('skills', []))} | "
            f"Profile experience: {len(candidate.get('experience', []))} roles"
        )

        resume_id    = str(uuid.uuid4())
        company_safe = re.sub(r"[^a-zA-Z0-9]", "_", job.get("company", "company"))[:20]
        pdf_path     = os.path.join(RESUME_DIR, f"{company_safe}_{resume_id[:8]}.pdf")

        html    = build_tailored_resume_html(candidate, jd_keywords, match_result)
        success = html_to_pdf(html, pdf_path)
        actual_path = pdf_path if success else pdf_path.replace(".pdf", ".html")

        cover_letter = generate_cover_letter(candidate, job, match_result)
        matched_kws  = match_result.get("matched_must_have", [])

        logger.info(f"Resume built: {actual_path} | keywords used: {matched_kws[:5]}")

        return json.dumps({
            "success":              success,
            "pdf_path":             actual_path,
            "resume_id":            resume_id,
            "cover_letter":         cover_letter,
            "matched_keywords_used": matched_kws,
            "cv_used":              has_cv,
            "sections_included":    {
                "experience": len(candidate.get("experience", [])),
                "education":  len(candidate.get("education", [])),
                "skills":     len(candidate.get("skills", [])),
            },
        })

    except Exception as e:
        logger.error(f"build_resume error: {e}")
        return json.dumps({"success": False, "error": str(e), "resume_id": str(uuid.uuid4())})
