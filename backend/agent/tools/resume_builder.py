"""
Resume Builder — JobBot
Builds a tailored PDF resume by:
1. Parsing the uploaded CV text (base_resume_text) into structured sections
2. Merging with profile data (contact, skills)
3. Reordering skills to match JD keywords for ATS optimisation
4. Generating a clean PDF with xhtml2pdf
"""

from langchain_core.tools import tool
from loguru import logger
import json, os, uuid, re

RESUME_DIR = "/tmp/resumes"
os.makedirs(RESUME_DIR, exist_ok=True)

# ─── Regex helpers ────────────────────────────────────────────────────────────

DATE_RE = re.compile(
    r'\b(?:19|20)\d{2}\b|'
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,]+20\d{2}|'
    r'\bPresent\b|\bCurrent\b|\btill\s+date\b',
    re.IGNORECASE
)

SECTION_MAP = [
    (r'summary|profile|objective|about|overview',              'summary'),
    (r'experience|employment|work.?history|career|positions?', 'experience'),
    (r'education|academic|qualification',                      'education'),
    (r'certif|license|credential|award|achievement',           'certifications'),
    (r'project|portfolio',                                     'projects'),
    (r'skill|technical|competenc|expertise|technolog',         'skills'),
]

def _classify_section(line: str):
    clean = re.sub(
        r'^(professional|technical|work|key|core|additional|relevant)\s+',
        '', line.strip(), flags=re.I
    ).rstrip(':').strip().lower()
    for pattern, name in SECTION_MAP:
        if re.match(pattern, clean):
            return name
    return None

def _is_section_header(line: str) -> bool:
    s = line.strip().rstrip(':').strip()
    if not s or len(s) > 70:
        return False
    words = [w for w in s.split() if w.isalpha()]
    if words and all(w.isupper() for w in words):
        return True
    return bool(_classify_section(s))

def _year(text: str) -> str:
    m = re.findall(r'\b(?:19|20)\d{2}\b', text)
    return m[-1] if m else ''


# ─── Section parsers ──────────────────────────────────────────────────────────

def _parse_experience(lines: list) -> list:
    roles, current = [], None

    def _save():
        if current and (current.get('role') or current.get('company')):
            roles.append(current)

    for line in lines:
        s = line.strip()
        if not s:
            continue

        is_bullet = s[0] in '-*'
        has_date  = bool(DATE_RE.search(s))
        has_pipe  = '|' in s

        # Detect new role header
        new_role = False
        if has_pipe and has_date:
            new_role = True
        elif re.search(r'\s+(?:at|@)\s+', s, re.I) and has_date:
            new_role = True
        elif has_date and not is_bullet and len(s) < 120:
            # "Company | Jan 2020 - Present" after a title-only line
            if current and not current.get('duration'):
                current['duration'] = DATE_RE.search(s).group(0) if DATE_RE.search(s) else s
                if has_pipe:
                    parts = [p.strip() for p in s.split('|')]
                    if not current.get('company'):
                        current['company'] = parts[0]
                    current['duration'] = ' '.join(parts[1:]).strip()
                continue

        title_only = (
            not is_bullet and not has_date and not has_pipe
            and len(s) < 80 and s[0].isupper()
        )

        if new_role:
            _save()
            current = {'role': '', 'company': '', 'duration': '', 'description': '', 'achievements': []}
            if has_pipe:
                parts = [p.strip() for p in s.split('|')]
                current['role']     = parts[0]
                current['company']  = parts[1] if len(parts) > 1 else ''
                current['duration'] = parts[2] if len(parts) > 2 else (parts[-1] if len(parts) > 1 else '')
            else:
                m = re.match(r'(.+?)\s+(?:at|@)\s+(.+?)(?:\s*[|\u2013\u2014\-]\s*(.+))?$', s, re.I)
                if m:
                    current['role'], current['company'] = m.group(1).strip(), m.group(2).strip()
                    current['duration'] = (m.group(3) or '').strip()
                else:
                    current['role'] = s
        elif title_only and current is None:
            current = {'role': s, 'company': '', 'duration': '', 'description': '', 'achievements': []}
        elif is_bullet and current is not None:
            current['achievements'].append(re.sub(r'^[-*]\s*', '', s))
        elif current is not None:
            if not current.get('company') and not has_date:
                current['company'] = s
            elif not current.get('description'):
                current['description'] = s
            else:
                current['description'] += ' ' + s

    _save()
    return roles


def _parse_education(lines: list) -> list:
    entries, current = [], None

    for line in lines:
        s = line.strip()
        if not s or s[0] in '-*':
            continue

        year = _year(s)
        has_grade = bool(re.search(r'\b(?:GPA|CGPA|grade|percentage|%|score|marks)\b', s, re.I))

        if has_grade:
            if current:
                current['grade'] = s
            continue

        if current and not current.get('institution') and not year:
            current['institution'] = s
        elif current and year and not current.get('year'):
            current['year'] = year
            inst = re.sub(DATE_RE, '', s).strip(' |\u2013\u2014-,')
            if inst and not current.get('institution'):
                current['institution'] = inst
        else:
            if current:
                entries.append(current)
            current = {'degree': s, 'institution': '', 'year': year or '', 'grade': ''}

    if current:
        entries.append(current)
    return entries


# ─── Main CV parser ───────────────────────────────────────────────────────────

def parse_cv_text(cv_text: str) -> dict:
    """Parse raw CV/resume text into structured sections."""
    if not cv_text:
        return {}

    text  = re.sub(r'^PDF:', '', cv_text.strip(), flags=re.I).strip()
    lines = text.split('\n')

    result = {
        'raw_text': text, 'name': '', 'summary': '',
        'experience_structured': [], 'education_structured': [],
        'certifications': [], 'projects': [], 'skills_raw': [],
    }

    # Identify section boundaries
    sections = []
    for i, line in enumerate(lines):
        if _is_section_header(line):
            sec = _classify_section(line)
            if sec and (not sections or sections[-1][0] != sec):
                sections.append((sec, i))

    if not sections:
        result['experience_structured'] = _parse_experience(lines)
        return result

    # Pre-section = name + contact
    pre = [l.strip() for l in lines[:sections[0][1]] if l.strip()]
    if pre:
        result['name'] = pre[0]

    for idx, (sec, start) in enumerate(sections):
        end       = sections[idx + 1][1] if idx + 1 < len(sections) else len(lines)
        body      = lines[start + 1 : end]
        non_empty = [l for l in body if l.strip()]

        if sec == 'summary':
            result['summary'] = ' '.join(l.strip() for l in non_empty)

        elif sec == 'skills':
            raw = ' '.join(l.strip() for l in non_empty)
            result['skills_raw'] = [
                s.strip().strip('*-')
                for s in re.split(r'[,|\t]+', raw)
                if 2 < len(s.strip()) < 50
            ]

        elif sec in ('certifications', 'projects'):
            result[sec] = [
                re.sub(r'^[-*]\s*', '', l.strip())
                for l in non_empty if l.strip()
            ]

        elif sec == 'experience':
            result['experience_structured'] = _parse_experience(non_empty)

        elif sec == 'education':
            result['education_structured'] = _parse_education(non_empty)

    return result


# ─── Merge CV + profile ───────────────────────────────────────────────────────

def merge_candidate_with_cv(candidate: dict, jd_keywords: dict, match_result: dict) -> dict:
    merged = dict(candidate)
    cv_text = candidate.get('base_resume_text', '')

    if cv_text and len(cv_text) > 100:
        logger.info(f"Parsing CV ({len(cv_text)} chars)")
        cv = parse_cv_text(cv_text)

        cv_exp  = cv.get('experience_structured', [])
        cv_edu  = cv.get('education_structured', [])
        cv_cert = cv.get('certifications', [])
        cv_proj = cv.get('projects', [])
        cv_skls = cv.get('skills_raw', [])

        if cv_exp:
            merged['experience'] = cv_exp
            logger.info(f"CV: {len(cv_exp)} roles, {len(cv_edu)} edu, {len(cv_cert)} certs")
        if cv_edu:
            merged['education'] = cv_edu
        if not merged.get('summary') and cv.get('summary'):
            merged['summary'] = cv['summary']
        if cv_cert:
            existing = merged.get('certifications', [])
            merged['certifications'] = list(dict.fromkeys(existing + cv_cert))
        if cv_proj:
            merged['projects'] = cv_proj

        profile_skills = candidate.get('skills', [])
        merged['skills'] = list(dict.fromkeys(
            [s for s in profile_skills] +
            [s for s in cv_skls if s not in profile_skills]
        ))[:40]
    else:
        logger.info("No CV text — using profile data only")

    # Reorder skills: JD-matched first
    jd_must = {s.lower() for s in jd_keywords.get('must_have', [])}
    jd_nice = {s.lower() for s in jd_keywords.get('nice_to_have', [])}
    matched  = {s.lower() for s in (
        match_result.get('matched_must_have', []) +
        match_result.get('matched_nice_to_have', [])
    )}
    all_s = merged.get('skills', [])
    t1 = [s for s in all_s if s.lower() in jd_must or s.lower() in matched]
    t2 = [s for s in all_s if s.lower() in jd_nice and s not in t1]
    t3 = [s for s in all_s if s not in t1 and s not in t2]
    merged['skills'] = (t1 + t2 + t3)[:25]
    logger.info(f"Skills ordered: {len(t1)} matched | {len(t2)} nice | {len(t3)} other")
    return merged


# ─── HTML template ────────────────────────────────────────────────────────────

def _build_html(candidate: dict, jd_keywords: dict, match_result: dict) -> str:
    d = merge_candidate_with_cv(candidate, jd_keywords, match_result)

    name     = d.get('name', '')
    email    = d.get('email', '')
    phone    = d.get('phone', '')
    location = d.get('location', '')
    linkedin = d.get('linkedin_url', '')
    github   = d.get('github_url', '')
    summary  = d.get('summary', '')
    skills   = d.get('skills', [])
    exps     = d.get('experience', [])
    edus     = d.get('education', [])
    certs    = d.get('certifications', [])
    projects = d.get('projects', [])

    def skills_html():
        return ''.join(f'<span class="skill">{s}</span>' for s in skills)

    def exp_html():
        h = ''
        for e in exps:
            if isinstance(e, str):
                h += f'<div class="exp-item"><p class="exp-desc">{e}</p></div>'
                continue
            ach = ''.join(f'<li>{a}</li>' for a in e.get('achievements', []) if a)
            h += f"""
            <div class="exp-item">
              <div class="exp-header">
                <div class="exp-left">
                  <div class="exp-role">{e.get('role','')}</div>
                  <div class="exp-company">{e.get('company','')}</div>
                </div>
                <div class="exp-duration">{e.get('duration','')}</div>
              </div>
              {"<p class='exp-desc'>" + e.get('description','') + "</p>" if e.get('description') else ""}
              {"<ul class='achievements'>" + ach + "</ul>" if ach else ""}
            </div>"""
        return h

    def edu_html():
        h = ''
        for e in edus:
            if isinstance(e, str):
                h += f'<div class="edu-item"><div class="edu-degree">{e}</div></div>'
                continue
            h += f"""
            <div class="edu-item">
              <div class="edu-degree">{e.get('degree','')}</div>
              <div class="edu-inst">{e.get('institution','')}{"&nbsp;&mdash;&nbsp;" + e.get('year','') if e.get('year') else ''}</div>
              {"<div class='edu-grade'>" + e.get('grade','') + "</div>" if e.get('grade') else ""}
            </div>"""
        return h

    cert_html = ''.join(f'<li>{c}</li>' for c in certs if c)
    proj_html = ''.join(
        f'<div class="exp-item"><p class="exp-desc">{p}</p></div>'
        if isinstance(p, str) else
        f'<div class="exp-item"><div class="exp-role">{p.get("name","")}</div>'
        f'<p class="exp-desc">{p.get("description","")}</p></div>'
        for p in projects
    )

    contact_line = ' &nbsp;|&nbsp; '.join(x for x in [phone, location] if x)
    links_line   = ' &nbsp;|&nbsp; '.join(x for x in [
        (f'LinkedIn: {linkedin}' if linkedin else ''),
        (f'GitHub: {github}'   if github   else ''),
    ] if x)

    exp_h  = exp_html()
    edu_h  = edu_html()
    skl_h  = skills_html()

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/>
<style>
  @page {{ margin: 1.8cm 2cm; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: Arial, Helvetica, sans-serif; font-size:10.5pt; color:#1a1a1a; line-height:1.45; }}
  .header {{ border-bottom: 2.5pt solid #1a5276; padding-bottom:10pt; margin-bottom:14pt; }}
  .name {{ font-size:20pt; font-weight:bold; color:#1a5276; letter-spacing:.5pt; }}
  .contact {{ margin-top:4pt; color:#444; font-size:9.5pt; }}
  .section {{ margin-bottom:14pt; page-break-inside:avoid; }}
  .section-title {{ font-size:11pt; font-weight:bold; color:#1a5276; text-transform:uppercase;
                    letter-spacing:1pt; border-bottom:.75pt solid #aed6f1; padding-bottom:2pt; margin-bottom:7pt; }}
  .summary {{ color:#333; text-align:justify; }}
  .skill {{ display:inline-block; background:#eaf4fb; border:.5pt solid #aed6f1; border-radius:2pt;
            padding:1.5pt 7pt; font-size:9pt; color:#1a5276; margin:2pt 3pt 2pt 0; }}
  .exp-item {{ margin-bottom:10pt; }}
  .exp-header {{ overflow:hidden; margin-bottom:2pt; }}
  .exp-left {{ float:left; }}
  .exp-role {{ font-weight:bold; font-size:11pt; }}
  .exp-company {{ color:#555; font-style:italic; font-size:10pt; }}
  .exp-duration {{ float:right; color:#555; font-size:9.5pt; }}
  .exp-desc {{ color:#444; margin:3pt 0; clear:both; }}
  .achievements {{ padding-left:16pt; color:#333; margin-top:3pt; }}
  .achievements li {{ margin-bottom:2pt; }}
  .edu-item {{ margin-bottom:7pt; }}
  .edu-degree {{ font-weight:bold; }}
  .edu-inst {{ color:#555; font-size:10pt; }}
  .edu-grade {{ color:#666; font-size:9.5pt; }}
  ul.cert-list {{ padding-left:16pt; }}
  ul.cert-list li {{ margin-bottom:2pt; }}
  .clearfix {{ clear:both; }}
</style></head><body>

<div class="header">
  <div class="name">{name}</div>
  {f'<div class="contact">{contact_line}</div>' if contact_line else ''}
  {f'<div class="contact">{links_line}</div>'   if links_line   else ''}
  <div class="contact">{email}</div>
</div>

{"<div class='section'><div class='section-title'>Professional Summary</div><p class='summary'>" + summary + "</p></div>" if summary else ""}

{"<div class='section'><div class='section-title'>Technical Skills</div><div>" + skl_h + "</div><div class='clearfix'></div></div>" if skl_h else ""}

{"<div class='section'><div class='section-title'>Professional Experience</div>" + exp_h + "</div>" if exp_h else ""}

{"<div class='section'><div class='section-title'>Projects</div>" + proj_html + "</div>" if proj_html else ""}

{"<div class='section'><div class='section-title'>Education</div>" + edu_h + "</div>" if edu_h else ""}

{"<div class='section'><div class='section-title'>Certifications</div><ul class='cert-list'>" + cert_html + "</ul></div>" if cert_html else ""}

</body></html>"""


def _html_to_pdf(html: str, path: str) -> bool:
    try:
        from xhtml2pdf import pisa
        with open(path, 'wb') as f:
            res = pisa.CreatePDF(html, dest=f)
        if res.err:
            logger.error(f"xhtml2pdf error: {res.err}")
            return False
        logger.info(f"PDF created: {path}")
        return True
    except ImportError:
        logger.warning("xhtml2pdf not installed")
    except Exception as e:
        logger.error(f"PDF error: {e}")
    try:
        with open(path.replace('.pdf', '.html'), 'w') as f:
            f.write(html)
    except:
        pass
    return False


def _cover_letter(candidate: dict, job: dict, match_result: dict) -> str:
    name    = candidate.get('name', 'Candidate')
    company = job.get('company', 'Company')
    role    = job.get('title', 'the role')
    matched = ', '.join(match_result.get('matched_must_have', [])[:5])
    years   = candidate.get('experience_years', 0)
    return (
        f"Dear Hiring Manager at {company},\n\n"
        f"I am excited to apply for the {role} position. With {years} years of experience "
        f"in {matched}, I bring both the technical depth and product mindset your team needs.\n\n"
        f"My background closely aligns with your requirements and I am confident in delivering "
        f"results from day one.\n\n"
        f"Best regards,\n{name}\n{candidate.get('email','')} | {candidate.get('phone','')}"
    )


# ─── Tool ─────────────────────────────────────────────────────────────────────

@tool
def build_resume(
    candidate_json: str,
    job_json: str,
    jd_keywords_json: str,
    match_result_json: str
) -> str:
    """
    Build a tailored PDF resume for a specific job.
    Parses uploaded CV (base_resume_text) for full work history and education.
    Merges with profile data. Reorders skills to match JD keywords.

    Args:
        candidate_json:    Full candidate profile (must include base_resume_text)
        job_json:          {title, company, portal, apply_url}
        jd_keywords_json:  {must_have: [], nice_to_have: []}
        match_result_json: {matched_must_have: [], matched_nice_to_have: []}

    Returns:
        JSON {success, pdf_path, resume_id, cover_letter, matched_keywords_used, cv_used}
    """
    try:
        candidate    = json.loads(candidate_json)    if isinstance(candidate_json,    str) else candidate_json
        job          = json.loads(job_json)          if isinstance(job_json,          str) else job_json
        jd_keywords  = json.loads(jd_keywords_json)  if isinstance(jd_keywords_json,  str) else jd_keywords_json
        match_result = json.loads(match_result_json) if isinstance(match_result_json, str) else match_result_json

        has_cv = bool(candidate.get('base_resume_text', ''))
        logger.info(
            f"build_resume: {job.get('title')} at {job.get('company')} | "
            f"CV={has_cv} skills={len(candidate.get('skills',[]))} exp={len(candidate.get('experience',[]))}"
        )

        resume_id = str(uuid.uuid4())
        co_safe   = re.sub(r'[^a-zA-Z0-9]', '_', job.get('company', 'co'))[:20]
        pdf_path  = os.path.join(RESUME_DIR, f"{co_safe}_{resume_id[:8]}.pdf")

        html    = _build_html(candidate, jd_keywords, match_result)
        success = _html_to_pdf(html, pdf_path)
        path    = pdf_path if success else pdf_path.replace('.pdf', '.html')

        return json.dumps({
            'success':               success,
            'pdf_path':              path,
            'resume_id':             resume_id,
            'cover_letter':          _cover_letter(candidate, job, match_result),
            'matched_keywords_used': match_result.get('matched_must_have', []),
            'cv_used':               has_cv,
        })
    except Exception as e:
        logger.error(f"build_resume error: {e}")
        return json.dumps({'success': False, 'error': str(e), 'resume_id': str(uuid.uuid4())})
