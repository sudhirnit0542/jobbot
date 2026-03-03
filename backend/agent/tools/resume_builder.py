"""
Resume Builder
Tailors candidate resume to match JD keywords, generates PDF using xhtml2pdf.
"""

from langchain_core.tools import tool
from loguru import logger
import json
import os
import uuid
import re

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
    matched_set = set(s.lower() for s in match_result.get("matched_must_have", []) + match_result.get("matched_nice_to_have", []))
    priority_skills = [s for s in all_skills if s.lower() in matched_set]
    other_skills = [s for s in all_skills if s.lower() not in matched_set]
    ordered_skills = (priority_skills + other_skills)[:20]

    skills_html = "".join(f'<span class="skill">{s}</span>' for s in ordered_skills)

    # Experience
    exp_html = ""
    for exp in candidate.get("experience", []):
        achievements = exp.get("achievements", [])
        ach_html = "".join(f"<li>{a}</li>" for a in achievements)
        exp_html += f"""
        <div class="exp-item">
            <div class="exp-header">
                <div class="exp-left">
                    <div class="exp-role">{exp.get('role', '')}</div>
                    <div class="exp-company">{exp.get('company', '')}</div>
                </div>
                <div class="exp-duration">{exp.get('duration', '')}</div>
            </div>
            <p class="exp-desc">{exp.get('description', '')}</p>
            {"<ul class='achievements'>" + ach_html + "</ul>" if ach_html else ""}
        </div>"""

    # Education
    edu_html = ""
    for edu in candidate.get("education", []):
        edu_html += f"""
        <div class="edu-item">
            <div class="edu-degree">{edu.get('degree', '')}</div>
            <div class="edu-inst">{edu.get('institution', '')} &mdash; {edu.get('year', '')}</div>
            {f"<div class='edu-grade'>Grade: {edu.get('grade', '')}</div>" if edu.get('grade') else ""}
        </div>"""

    # Certifications
    cert_items = "".join(f"<li>{c}</li>" for c in candidate.get("certifications", []))

    # Contact line
    contact_parts = []
    if phone: contact_parts.append(phone)
    if location: contact_parts.append(location)
    if linkedin: contact_parts.append(f'LinkedIn: {linkedin}')
    if github: contact_parts.append(f'GitHub: {github}')

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
  .section {{ margin-bottom: 14pt; }}
  .section-title {{ font-size: 11pt; font-weight: bold; color: #1a5276; text-transform: uppercase;
                    letter-spacing: 1pt; border-bottom: 0.75pt solid #aed6f1; padding-bottom: 2pt; margin-bottom: 7pt; }}
  .summary {{ color: #333; text-align: justify; }}
  .skills-wrap {{ }}
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

<div class="section">
  <div class="section-title">Technical Skills</div>
  <div class="skills-wrap">{skills_html}</div>
  <div class="clearfix"></div>
</div>

{"<div class='section'><div class='section-title'>Professional Experience</div>" + exp_html + "</div>" if exp_html else ""}

{"<div class='section'><div class='section-title'>Education</div>" + edu_html + "</div>" if edu_html else ""}

{"<div class='section'><div class='section-title'>Certifications</div><ul class='cert-list'>" + cert_items + "</ul></div>" if cert_items else ""}

</body>
</html>"""


def html_to_pdf(html_content: str, output_path: str) -> bool:
    """Convert HTML to PDF using xhtml2pdf."""
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
        logger.warning("xhtml2pdf not available — saving as HTML")
        html_path = output_path.replace(".pdf", ".html")
        with open(html_path, "w") as f:
            f.write(html_content)
        return False
    except Exception as e:
        logger.error(f"PDF generation error: {e}")
        # Fallback — save as HTML
        try:
            html_path = output_path.replace(".pdf", ".html")
            with open(html_path, "w") as f:
                f.write(html_content)
        except:
            pass
        return False


def generate_cover_letter(candidate: dict, job: dict, match_result: dict) -> str:
    name = candidate.get("name", "Candidate")
    company = job.get("company", "Company")
    role = job.get("title", "Role")
    matched = ", ".join(match_result.get("matched_must_have", [])[:5])
    exp_years = candidate.get("experience_years", 0)

    return f"""Dear Hiring Manager at {company},

I am writing to express my strong interest in the {role} position at {company}. With {exp_years} years of experience in {matched}, I am confident in my ability to make an immediate contribution to your team.

Throughout my career, I have developed deep expertise in the technologies that align with your requirements. I have consistently delivered results that drive both technical excellence and business value.

I would welcome the opportunity to discuss how my background can contribute to {company}'s success. Thank you for considering my application.

Best regards,
{name}
{candidate.get('email', '')}
{candidate.get('phone', '')}"""


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

        # Use full UUID for filename
        resume_id = str(uuid.uuid4())
        company_clean = re.sub(r'[^a-zA-Z0-9]', '_', job.get('company', 'company'))[:20]
        pdf_filename = f"{company_clean}_{resume_id[:8]}.pdf"
        pdf_path = os.path.join(RESUME_DIR, pdf_filename)

        html = build_tailored_resume_html(candidate, jd_keywords, match_result)
        success = html_to_pdf(html, pdf_path)

        actual_path = pdf_path if success else pdf_path.replace(".pdf", ".html")
        cover_letter = generate_cover_letter(candidate, job, match_result)

        return json.dumps({
            "success": success,
            "pdf_path": actual_path,
            "resume_id": resume_id,          # Full UUID
            "cover_letter": cover_letter,
            "matched_keywords_used": match_result.get("matched_must_have", []),
        })

    except Exception as e:
        logger.error(f"Resume build error: {e}")
        return json.dumps({"success": False, "error": str(e), "resume_id": str(uuid.uuid4())})
