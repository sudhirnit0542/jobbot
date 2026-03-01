"""
Resume Builder
Tailors candidate resume to match JD keywords, generates PDF.
"""

from langchain_core.tools import tool
from loguru import logger
import json
import os
import uuid
from datetime import datetime


RESUME_DIR = "/tmp/resumes"
os.makedirs(RESUME_DIR, exist_ok=True)


def build_tailored_resume_html(candidate: dict, jd_keywords: dict, match_result: dict) -> str:
    """Build a tailored HTML resume optimized for ATS and keyword matching."""

    name = candidate.get("name", "")
    email = candidate.get("email", "")
    phone = candidate.get("phone", "")
    location = candidate.get("location", "")
    linkedin = candidate.get("linkedin_url", "")
    github = candidate.get("github_url", "")
    summary = candidate.get("summary", "")

    # Reorder skills — put matched keywords first
    all_skills = candidate.get("skills", [])
    matched = [s for s in match_result.get("matched_must_have", []) + match_result.get("matched_nice_to_have", [])]
    matched_set = set(s.lower() for s in matched)
    priority_skills = [s for s in all_skills if s.lower() in matched_set]
    other_skills = [s for s in all_skills if s.lower() not in matched_set]
    ordered_skills = priority_skills + other_skills

    # Inject missing keywords naturally into summary if they appear in experience
    jd_must = jd_keywords.get("must_have", [])
    missing = match_result.get("missing_must_have", [])

    # Build skills HTML
    skills_html = "".join(f'<span class="skill">{s}</span>' for s in ordered_skills[:20])

    # Build experience HTML
    exp_html = ""
    for exp in candidate.get("experience", []):
        achievements = exp.get("achievements", [])
        ach_html = "".join(f"<li>{a}</li>" for a in achievements)
        exp_html += f"""
        <div class="exp-item">
            <div class="exp-header">
                <div>
                    <div class="exp-role">{exp.get('role', '')}</div>
                    <div class="exp-company">{exp.get('company', '')}</div>
                </div>
                <div class="exp-duration">{exp.get('duration', '')}</div>
            </div>
            <p class="exp-desc">{exp.get('description', '')}</p>
            <ul class="achievements">{ach_html}</ul>
        </div>
        """

    # Build education HTML
    edu_html = ""
    for edu in candidate.get("education", []):
        edu_html += f"""
        <div class="edu-item">
            <div class="edu-degree">{edu.get('degree', '')}</div>
            <div class="edu-inst">{edu.get('institution', '')} — {edu.get('year', '')}</div>
            {f"<div class='edu-grade'>Grade: {edu.get('grade', '')}</div>" if edu.get('grade') else ""}
        </div>
        """

    # Certifications
    cert_html = ""
    for cert in candidate.get("certifications", []):
        cert_html += f"<li>{cert}</li>"

    contact_parts = []
    if phone:
        contact_parts.append(f"📞 {phone}")
    if location:
        contact_parts.append(f"📍 {location}")
    if linkedin:
        contact_parts.append(f'<a href="{linkedin}">LinkedIn</a>')
    if github:
        contact_parts.append(f'<a href="{github}">GitHub</a>')

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Calibri', Arial, sans-serif; font-size: 11pt; color: #1a1a1a; line-height: 1.4; padding: 30px 40px; }}
  .header {{ border-bottom: 2.5px solid #1a5276; padding-bottom: 12px; margin-bottom: 16px; }}
  .name {{ font-size: 22pt; font-weight: bold; color: #1a5276; letter-spacing: 1px; }}
  .contact {{ margin-top: 5px; color: #444; font-size: 10pt; }}
  .contact a {{ color: #1a5276; text-decoration: none; }}
  .contact span {{ margin: 0 8px; }}
  .section {{ margin-bottom: 16px; }}
  .section-title {{ font-size: 12pt; font-weight: bold; color: #1a5276; text-transform: uppercase;
                     letter-spacing: 1.5px; border-bottom: 1px solid #aed6f1; padding-bottom: 3px; margin-bottom: 8px; }}
  .summary {{ color: #333; text-align: justify; }}
  .skills-grid {{ display: flex; flex-wrap: wrap; gap: 5px; }}
  .skill {{ background: #eaf4fb; border: 1px solid #aed6f1; border-radius: 3px;
             padding: 2px 8px; font-size: 9.5pt; color: #1a5276; }}
  .exp-item {{ margin-bottom: 12px; }}
  .exp-header {{ display: flex; justify-content: space-between; align-items: flex-start; }}
  .exp-role {{ font-weight: bold; font-size: 11.5pt; }}
  .exp-company {{ color: #555; font-style: italic; }}
  .exp-duration {{ color: #555; font-size: 10pt; white-space: nowrap; }}
  .exp-desc {{ color: #444; margin: 4px 0; }}
  .achievements {{ padding-left: 18px; color: #333; }}
  .achievements li {{ margin-bottom: 2px; }}
  .edu-item {{ margin-bottom: 8px; }}
  .edu-degree {{ font-weight: bold; }}
  .edu-inst {{ color: #555; }}
  .edu-grade {{ color: #666; font-size: 10pt; }}
  .cert-list {{ padding-left: 18px; }}
  .cert-list li {{ margin-bottom: 3px; }}
  @page {{ margin: 0; }}
</style>
</head>
<body>

<div class="header">
  <div class="name">{name}</div>
  <div class="contact">{" &nbsp;|&nbsp; ".join(contact_parts)}</div>
  <div class="contact" style="margin-top:3px;">✉ {email}</div>
</div>

<div class="section">
  <div class="section-title">Professional Summary</div>
  <p class="summary">{summary}</p>
</div>

<div class="section">
  <div class="section-title">Technical Skills</div>
  <div class="skills-grid">{skills_html}</div>
</div>

<div class="section">
  <div class="section-title">Professional Experience</div>
  {exp_html}
</div>

<div class="section">
  <div class="section-title">Education</div>
  {edu_html}
</div>

{"<div class='section'><div class='section-title'>Certifications</div><ul class='cert-list'>" + cert_html + "</ul></div>" if cert_html else ""}

</body>
</html>"""


def html_to_pdf(html_content: str, output_path: str) -> bool:
    """Convert HTML to PDF using WeasyPrint."""
    try:
        from weasyprint import HTML
        HTML(string=html_content).write_pdf(output_path)
        logger.info(f"PDF created: {output_path}")
        return True
    except ImportError:
        # Fallback — save as HTML file
        html_path = output_path.replace(".pdf", ".html")
        with open(html_path, "w") as f:
            f.write(html_content)
        logger.warning("WeasyPrint not available — saved as HTML")
        return False
    except Exception as e:
        logger.error(f"PDF generation error: {e}")
        return False


def generate_cover_letter(candidate: dict, job: dict, match_result: dict) -> str:
    """Generate a tailored cover letter."""
    name = candidate.get("name", "Candidate")
    company = job.get("company", "Company")
    role = job.get("title", "Role")
    matched = ", ".join(match_result.get("matched_must_have", [])[:5])
    exp_years = candidate.get("experience_years", 0)

    return f"""Dear Hiring Manager at {company},

I am writing to express my strong interest in the {role} position at {company}. With {exp_years} years of hands-on experience in {matched}, I am confident in my ability to make an immediate and meaningful contribution to your team.

Throughout my career, I have developed deep expertise in the technologies and methodologies that align perfectly with your requirements. My experience spans {matched}, and I have consistently delivered results that drive both technical excellence and business value.

What particularly excites me about this opportunity at {company} is the chance to apply my skills in a dynamic environment where innovation is valued. I am eager to bring my problem-solving abilities and collaborative mindset to your team.

I would welcome the opportunity to discuss how my background and skills can contribute to {company}'s success. Thank you for considering my application.

Best regards,
{name}
{candidate.get('email', '')}
{candidate.get('phone', '')}"""


# ─── LangChain Tool ───────────────────────────────────────────────────────────

@tool
def build_resume(
    candidate_json: str,
    job_json: str,
    jd_keywords_json: str,
    match_result_json: str
) -> str:
    """
    Build a tailored PDF resume for a specific job.
    Reorders skills to match JD keywords, optimizes for ATS.
    Also generates a cover letter.

    Args:
        candidate_json: Full candidate profile as JSON
        job_json: Job details (title, company, etc.)
        jd_keywords_json: Keywords extracted from JD
        match_result_json: Match scoring result

    Returns:
        Paths to generated PDF and cover letter text
    """
    try:
        candidate = json.loads(candidate_json) if isinstance(candidate_json, str) else candidate_json
        job = json.loads(job_json) if isinstance(job_json, str) else job_json
        jd_keywords = json.loads(jd_keywords_json) if isinstance(jd_keywords_json, str) else jd_keywords_json
        match_result = json.loads(match_result_json) if isinstance(match_result_json, str) else match_result_json

        # Generate unique filename
        resume_id = str(uuid.uuid4())[:8]
        company_clean = re.sub(r'[^a-zA-Z0-9]', '_', job.get('company', 'company'))[:20]
        pdf_filename = f"{company_clean}_{resume_id}.pdf"
        pdf_path = os.path.join(RESUME_DIR, pdf_filename)

        # Build HTML resume
        html = build_tailored_resume_html(candidate, jd_keywords, match_result)

        # Convert to PDF
        success = html_to_pdf(html, pdf_path)

        # Generate cover letter
        cover_letter = generate_cover_letter(candidate, job, match_result)

        import re as re_module
        return json.dumps({
            "success": success,
            "pdf_path": pdf_path if success else pdf_path.replace(".pdf", ".html"),
            "resume_id": resume_id,
            "cover_letter": cover_letter,
            "matched_keywords_used": match_result.get("matched_must_have", []),
            "note": "Resume tailored with JD keywords. Skills reordered by match priority."
        })

    except Exception as e:
        logger.error(f"Resume build error: {e}")
        return json.dumps({"success": False, "error": str(e)})

import re
