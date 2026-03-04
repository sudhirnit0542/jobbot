"""
Application Agent — Playwright Browser Automation

Handles two application paths:
A) Easy Apply  — portal has a built-in apply flow (LinkedIn Easy Apply, Naukri Quick Apply)
B) External Apply — job links to company's own careers page
   - Navigates to the company careers page
   - Creates account if needed (email + password)
   - Uploads resume PDF
   - Auto-fills form fields from candidate profile
   - Handles multi-step forms
   - Detects and reports blockers (CAPTCHA, OTP, verification)
"""

from langchain_core.tools import tool
from loguru import logger
import json
import asyncio
import secrets
import string
import base64
import re
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from config import get_settings

settings = get_settings()


# ─── Crypto helpers ───────────────────────────────────────────────────────────

def _get_fernet() -> Fernet:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=b"jobbot_v1", iterations=100000)
    key = base64.urlsafe_b64encode(kdf.derive(settings.secret_key.encode()))
    return Fernet(key)

def encrypt_password(pw: str) -> str: return _get_fernet().encrypt(pw.encode()).decode()
def decrypt_password(tok: str) -> str: return _get_fernet().decrypt(tok.encode()).decode()

def generate_password(length: int = 14) -> str:
    chars = string.ascii_letters + string.digits + "!@#$"
    pwd = (secrets.choice(string.ascii_uppercase) + secrets.choice(string.digits) +
           secrets.choice("!@#$") + "".join(secrets.choice(chars) for _ in range(length - 3)))
    return "".join(secrets.SystemRandom().sample(pwd, len(pwd)))


# ─── Shared page helpers ──────────────────────────────────────────────────────

async def _has(page, selector: str) -> bool:
    try:
        el = await page.query_selector(selector)
        return el is not None
    except:
        return False

async def _fill_if_empty(page, selector: str, value: str):
    """Fill a field only if it's currently empty."""
    try:
        el = await page.query_selector(selector)
        if el and value:
            current = await el.input_value()
            if not current:
                await el.fill(value)
                await asyncio.sleep(0.3)
    except:
        pass

async def _fill(page, selector: str, value: str):
    """Fill a field (overwrite existing value)."""
    try:
        el = await page.query_selector(selector)
        if el and value:
            await el.fill(value)
            await asyncio.sleep(0.2)
    except:
        pass

async def _click(page, selector: str) -> bool:
    try:
        el = await page.query_selector(selector)
        if el:
            await el.click()
            return True
    except:
        pass
    return False

async def detect_blocker(page) -> str | None:
    """Detect common blockers — returns description or None."""
    url = page.url.lower()
    if any(x in url for x in ["captcha", "blocked", "robot", "challenge"]):
        return f"Anti-bot page detected: {page.url}"
    if await _has(page, "iframe[src*='recaptcha'], div.g-recaptcha, div[class*='captcha']"):
        return "CAPTCHA detected — cannot automate"
    if await _has(page, "input[name*='otp'], input[placeholder*='OTP'], input[id*='otp']"):
        return "OTP / phone verification required — cannot automate"
    if await _has(page, "input[name*='pin'], #input__email_verification_pin"):
        return "Email PIN verification required — cannot automate"
    return None


# ─── Generic form filler ──────────────────────────────────────────────────────

async def fill_application_form(page, candidate: dict, pdf_path: str, cover_letter: str = "") -> dict:
    """
    Generic form filler for any company application page.
    Tries common field selectors for name, email, phone, etc.
    Uploads resume if file input found.
    Returns {"filled": int, "uploaded": bool}
    """
    name_parts = (candidate.get("name") or "").split()
    first = name_parts[0] if name_parts else ""
    last  = name_parts[-1] if len(name_parts) > 1 else ""
    email = candidate.get("email", "")
    phone = candidate.get("phone", "")
    location = candidate.get("location", "")
    linkedin = candidate.get("linkedin_url", "")
    summary  = candidate.get("summary", "")
    exp_years = str(candidate.get("experience_years", ""))

    filled = 0

    # Name fields
    for sel, val in [
        ("input[name*='firstName' i], input[id*='firstName' i], input[placeholder*='First name' i]", first),
        ("input[name*='lastName' i],  input[id*='lastName' i],  input[placeholder*='Last name' i]",  last),
        ("input[name*='fullName' i],  input[id*='fullName' i],  input[placeholder*='Full name' i]",  candidate.get("name","")),
        ("input[name='name'],         input[id='name'],         input[placeholder='Name']",           candidate.get("name","")),
        ("input[type='email'],        input[name*='email' i]",  email),
        ("input[type='tel'],          input[name*='phone' i],   input[placeholder*='phone' i]",      phone),
        ("input[name*='location' i],  input[placeholder*='location' i], input[placeholder*='city' i]", location),
        ("input[name*='linkedin' i],  input[placeholder*='linkedin' i]", linkedin),
        ("input[name*='experience' i],input[placeholder*='years' i]",   exp_years),
    ]:
        for s in sel.split(","):
            s = s.strip()
            if await _has(page, s):
                await _fill_if_empty(page, s, val)
                filled += 1
                break

    # Summary / cover letter textarea
    for sel in [
        "textarea[name*='cover' i]", "textarea[name*='letter' i]",
        "textarea[name*='summary' i]", "textarea[placeholder*='cover' i]",
        "textarea[placeholder*='tell us' i]", "textarea[placeholder*='about you' i]",
    ]:
        if await _has(page, sel):
            await _fill_if_empty(page, sel, cover_letter or summary)
            filled += 1
            break

    # Resume upload
    uploaded = False
    if pdf_path and os.path.exists(pdf_path):
        for sel in ["input[type='file'][accept*='pdf' i]", "input[type='file'][name*='resume' i]",
                    "input[type='file'][name*='cv' i]", "input[type='file']"]:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.set_input_files(pdf_path)
                    await asyncio.sleep(1.5)
                    uploaded = True
                    logger.info(f"Resume uploaded via {sel}")
                    break
            except Exception as e:
                logger.warning(f"File upload failed with {sel}: {e}")

    return {"filled": filled, "uploaded": uploaded}

import os


# ─── Account creation on company portals ─────────────────────────────────────

async def create_account_on_page(page, email: str, name: str, password: str) -> dict:
    """
    Try to create an account on the current page (company careers portal).
    Looks for registration/signup forms.
    """
    name_parts = name.split()
    first = name_parts[0] if name_parts else name
    last  = name_parts[-1] if len(name_parts) > 1 else ""

    # Common sign-up field patterns
    fields = [
        ("input[name*='firstName' i], input[placeholder*='first' i]", first),
        ("input[name*='lastName' i],  input[placeholder*='last' i]",  last),
        ("input[name='name'],         input[placeholder='Name']",       name),
        ("input[type='email'],        input[name*='email' i]",         email),
        ("input[type='password'],     input[name*='password' i]",      password),
        ("input[name*='confirm' i],   input[placeholder*='confirm' i]", password),
    ]

    filled = 0
    for sel, val in fields:
        for s in sel.split(","):
            s = s.strip()
            if await _has(page, s):
                await _fill(page, s, val)
                filled += 1
                break

    if filled < 2:
        return {"success": False, "error": "Could not find registration form fields"}

    # Submit
    for sel in ["button[type='submit']", "button:has-text('Sign up')",
                "button:has-text('Register')", "button:has-text('Create account')",
                "input[type='submit']"]:
        if await _click(page, sel):
            await asyncio.sleep(3)
            blocker = await detect_blocker(page)
            if blocker:
                return {"success": False, "error": f"Blocker after registration: {blocker}"}
            logger.info(f"Account created for {email}")
            return {"success": True, "username": email, "password": password,
                    "password_enc": encrypt_password(password)}

    return {"success": False, "error": "Registration submit button not found"}


async def login_on_page(page, account: dict) -> bool:
    """Try to log in using existing account credentials on the current page."""
    username = account.get("username", "")
    password = decrypt_password(account.get("password_enc", ""))
    if not username or not password:
        return False

    for email_sel in ["input[type='email']", "input[name*='email' i]", "input[name='username']", "#username"]:
        if await _has(page, email_sel):
            await _fill(page, email_sel, username)
            break

    for pwd_sel in ["input[type='password']", "input[name*='password' i]", "#password"]:
        if await _has(page, pwd_sel):
            await _fill(page, pwd_sel, password)
            break

    for submit_sel in ["button[type='submit']", "button:has-text('Log in')",
                       "button:has-text('Sign in')", "input[type='submit']"]:
        if await _click(page, submit_sel):
            await asyncio.sleep(3)
            return True

    return False


# ─── Submit form helper ───────────────────────────────────────────────────────

async def try_submit_form(page) -> dict:
    """Step through multi-page application form and submit."""
    for step in range(8):
        await asyncio.sleep(1)
        blocker = await detect_blocker(page)
        if blocker:
            return {"success": False, "error": blocker}

        # Look for Next / Continue / Submit in order of priority
        for sel, is_final in [
            ("button:has-text('Submit application')", True),
            ("button:has-text('Submit Application')", True),
            ("button:has-text('Submit')",             True),
            ("input[value*='Submit' i]",              True),
            ("button:has-text('Apply')",              False),
            ("button:has-text('Next')",               False),
            ("button:has-text('Continue')",           False),
            ("button:has-text('Review')",             False),
            ("button[type='submit']",                 False),
        ]:
            el = await page.query_selector(sel)
            if el:
                try:
                    is_visible = await el.is_visible()
                    is_enabled = await el.is_enabled()
                    if is_visible and is_enabled:
                        await el.click()
                        await asyncio.sleep(2)
                        if is_final:
                            logger.info(f"Form submitted at step {step+1}")
                            return {"success": True, "steps": step + 1}
                        break
                except:
                    pass
        else:
            # No button found — might already be done
            break

    # Check for success indicators
    body_text = (await page.inner_text("body")).lower()
    success_phrases = ["application submitted", "thank you for applying",
                       "application received", "you have applied", "successfully applied"]
    if any(p in body_text for p in success_phrases):
        return {"success": True, "message": "Success confirmation detected on page"}

    return {"success": False, "error": "Could not find submit button or confirm success"}


# ─── Portal-specific handlers ─────────────────────────────────────────────────

async def apply_linkedin(page, candidate, job, pdf_path, cover_letter, account) -> dict:
    url = job.get("apply_url", "")
    title = job.get("title", "")
    company = job.get("company", "")

    if not account:
        return {"success": False, "needs_account": True, "portal": "linkedin",
                "error": "LinkedIn requires account login"}

    logger.info(f"LinkedIn: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)

    # Log in if needed
    if "linkedin.com/login" in page.url or await _has(page, "#username"):
        logger.info(f"LinkedIn: logging in as {account['username']}")
        await _fill(page, "#username", account["username"])
        await _fill(page, "#password", decrypt_password(account["password_enc"]))
        await _click(page, "button[type='submit']")
        await asyncio.sleep(4)

    blocker = await detect_blocker(page)
    if blocker:
        return {"success": False, "portal": "linkedin", "error": blocker}

    # ── Path A: Easy Apply ──
    easy_apply_el = await page.query_selector(
        "button.jobs-apply-button, button:has-text('Easy Apply')"
    )
    if easy_apply_el:
        logger.info("LinkedIn: Easy Apply found")
        await easy_apply_el.click()
        await asyncio.sleep(2)

        # Phone
        await _fill_if_empty(page, "input[id*='phone' i]", candidate.get("phone", ""))

        # Resume upload
        if pdf_path and await _has(page, "input[type='file']"):
            await page.query_selector("input[type='file']")
            try:
                fi = await page.query_selector("input[type='file']")
                if fi:
                    await fi.set_input_files(pdf_path)
                    await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"LinkedIn resume upload: {e}")

        result = await try_submit_form(page)
        if result.get("success"):
            return {"success": True, "portal": "linkedin",
                    "message": f"LinkedIn Easy Apply: {title} at {company}"}
        return {"success": False, "portal": "linkedin",
                "error": f"Easy Apply form failed: {result.get('error')}"}

    # ── Path B: External Apply link ──
    logger.info("LinkedIn: No Easy Apply — looking for external apply link")
    ext_link = await page.query_selector(
        "a:has-text('Apply'), a[href*='apply'], "
        "button:has-text('Apply on company website'), a:has-text('Apply on company')"
    )
    if ext_link:
        href = await ext_link.get_attribute("href") or ""
        logger.info(f"LinkedIn: external apply link → {href}")
        if href:
            await page.goto(href, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
            return await apply_external(page, candidate, job, pdf_path, cover_letter, account,
                                        source="linkedin_external")

    return {"success": False, "portal": "linkedin",
            "error": f"No Easy Apply or external link found. URL: {page.url}"}


async def apply_naukri(page, candidate, job, pdf_path, cover_letter, account) -> dict:
    url = job.get("apply_url", "")
    title = job.get("title", "")
    company = job.get("company", "")

    logger.info(f"Naukri: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)

    current_url = page.url
    blocker = await detect_blocker(page)
    if blocker:
        return {"success": False, "portal": "naukri", "error": blocker}

    # Login if needed
    if "login" in current_url.lower() or await _has(page, "input[type='password']"):
        if account:
            logger.info(f"Naukri: logging in as {account['username']}")
            await _fill(page, "input[type='email'], input[name='username']", account["username"])
            await _fill(page, "input[type='password']", decrypt_password(account["password_enc"]))
            await page.keyboard.press("Enter")
            await asyncio.sleep(4)
        else:
            return {"success": False, "needs_account": True, "portal": "naukri",
                    "error": "Naukri login required — no account found"}

    # Click Apply / Quick Apply
    apply_clicked = await _click(page, "button:has-text('Apply'), a:has-text('Apply Now'), "
                                       "button[class*='apply' i], a[class*='apply' i]")
    if not apply_clicked:
        return {"success": False, "portal": "naukri",
                "error": f"No Apply button found. URL: {current_url}"}

    await asyncio.sleep(2)
    blocker = await detect_blocker(page)
    if blocker:
        return {"success": False, "portal": "naukri", "error": blocker}

    # Upload resume
    if pdf_path and await _has(page, "input[type='file']"):
        fi = await page.query_selector("input[type='file']")
        if fi:
            await fi.set_input_files(pdf_path)
            await asyncio.sleep(1.5)

    result = await try_submit_form(page)
    if result.get("success"):
        return {"success": True, "portal": "naukri", "message": f"Applied on Naukri: {title} at {company}"}
    return {"success": False, "portal": "naukri", "error": result.get("error", "Submit failed")}


async def apply_indeed(page, candidate, job, pdf_path, cover_letter, account) -> dict:
    url = job.get("apply_url", "")
    title = job.get("title", "")
    company = job.get("company", "")

    logger.info(f"Indeed: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)

    blocker = await detect_blocker(page)
    if blocker:
        return {"success": False, "portal": "indeed", "error": blocker}

    # Indeed Easy Apply
    easy = await page.query_selector("button:has-text('Apply now'), button:has-text('Easy Apply')")
    if not easy:
        # May be external redirect
        logger.info("Indeed: no Easy Apply — trying external link")
        ext = await page.query_selector("a:has-text('Apply'), a[href*='apply']")
        if ext:
            href = await ext.get_attribute("href") or ""
            if href and href.startswith("http"):
                await page.goto(href, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                return await apply_external(page, candidate, job, pdf_path, cover_letter, account,
                                            source="indeed_external")
        return {"success": False, "portal": "indeed",
                "error": f"No Easy Apply found on Indeed. URL: {page.url}"}

    await easy.click()
    await asyncio.sleep(2)

    # Email step
    if await _has(page, "input[type='email']"):
        await _fill(page, "input[type='email']", candidate.get("email", ""))
        await _click(page, "button:has-text('Continue'), button[type='submit']")
        await asyncio.sleep(2)

    # Password
    if await _has(page, "input[type='password']"):
        if account:
            await _fill(page, "input[type='password']", decrypt_password(account["password_enc"]))
            await page.keyboard.press("Enter")
            await asyncio.sleep(3)
        else:
            return {"success": False, "needs_account": True, "portal": "indeed",
                    "error": "Indeed login required — no account found"}

    # Upload resume
    if pdf_path and await _has(page, "input[type='file']"):
        fi = await page.query_selector("input[type='file']")
        if fi:
            await fi.set_input_files(pdf_path)
            await asyncio.sleep(1.5)

    result = await try_submit_form(page)
    if result.get("success"):
        return {"success": True, "portal": "indeed", "message": f"Applied on Indeed: {title} at {company}"}
    return {"success": False, "portal": "indeed", "error": result.get("error", "Submit failed")}


async def apply_instahyre(page, candidate, job, pdf_path, cover_letter, account) -> dict:
    url = job.get("apply_url", "")
    title = job.get("title", "")
    company = job.get("company", "")

    logger.info(f"Instahyre: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)

    blocker = await detect_blocker(page)
    if blocker:
        return {"success": False, "portal": "instahyre", "error": blocker}

    if not await _click(page, "button:has-text('Apply'), a:has-text('Apply')"):
        return {"success": False, "portal": "instahyre",
                "error": f"No Apply button found. URL: {page.url}"}

    await asyncio.sleep(2)
    blocker = await detect_blocker(page)
    if blocker:
        return {"success": False, "portal": "instahyre", "error": blocker}

    if await _has(page, "input[type='email']"):
        await _fill(page, "input[type='email']", candidate.get("email", ""))
        await _click(page, "button:has-text('Continue'), button[type='submit']")
        await asyncio.sleep(2)

    blocker = await detect_blocker(page)
    if blocker:
        return {"success": False, "portal": "instahyre", "error": blocker}

    if pdf_path and await _has(page, "input[type='file']"):
        fi = await page.query_selector("input[type='file']")
        if fi:
            await fi.set_input_files(pdf_path)
            await asyncio.sleep(1.5)

    result = await try_submit_form(page)
    if result.get("success"):
        return {"success": True, "portal": "instahyre", "message": f"Applied on Instahyre: {title} at {company}"}
    return {"success": False, "portal": "instahyre", "error": result.get("error", "Submit failed")}


async def apply_adzuna(page, candidate, job, pdf_path, cover_letter, account) -> dict:
    url = job.get("apply_url", "")
    title = job.get("title", "")
    company = job.get("company", "")

    logger.info(f"Adzuna: navigating to {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await asyncio.sleep(3)

    final_url = page.url
    logger.info(f"Adzuna: redirected to {final_url}")

    # Adzuna always redirects to company/portal — treat as external
    return await apply_external(page, candidate, job, pdf_path, cover_letter, account,
                                source="adzuna_redirect")


# ─── External company portal apply ───────────────────────────────────────────

async def apply_external(page, candidate, job, pdf_path, cover_letter, account,
                         source="external") -> dict:
    """
    Apply on a company's own careers portal.
    Strategy:
    1. Look for an Apply button on the job page
    2. If login wall — try login, then create account if needed
    3. Fill the application form
    4. Upload resume
    5. Submit
    """
    title   = job.get("title", "")
    company = job.get("company", "")
    url     = page.url

    logger.info(f"External apply [{source}]: {url}")

    blocker = await detect_blocker(page)
    if blocker:
        return {"success": False, "status": "FAILED", "portal": source, "error": blocker}

    # Try clicking Apply button on the page
    for sel in ["button:has-text('Apply Now')", "button:has-text('Apply now')",
                "a:has-text('Apply Now')",    "a:has-text('Apply now')",
                "button:has-text('Apply')",   "a:has-text('Apply')",
                "input[value*='Apply' i]"]:
        if await _click(page, sel):
            await asyncio.sleep(2)
            logger.info(f"External: clicked Apply button")
            break

    blocker = await detect_blocker(page)
    if blocker:
        return {"success": False, "status": "FAILED", "portal": source, "error": blocker}

    # Handle login / sign-up wall
    needs_login = (
        await _has(page, "input[type='password']") or
        "login" in page.url.lower() or
        "signin" in page.url.lower() or
        "sign-in" in page.url.lower()
    )

    if needs_login:
        if account:
            logger.info(f"External: logging in as {account['username']}")
            logged_in = await login_on_page(page, account)
            if logged_in:
                await asyncio.sleep(3)
                blocker = await detect_blocker(page)
                if blocker:
                    return {"success": False, "status": "FAILED", "portal": source, "error": blocker}
            else:
                logger.warning("External: login attempt failed — trying account creation")
        else:
            logger.info(f"External: no account — attempting registration")

        # Check if there's a sign-up option
        has_signup = (
            await _has(page, "a:has-text('Sign up')") or
            await _has(page, "a:has-text('Register')") or
            await _has(page, "button:has-text('Create account')")
        )

        if has_signup or not account:
            pw = generate_password()
            # Try to navigate to sign up
            for sel in ["a:has-text('Sign up')", "a:has-text('Register')",
                        "button:has-text('Create account')", "a:has-text('Create account')"]:
                if await _click(page, sel):
                    await asyncio.sleep(2)
                    break

            new_account = await create_account_on_page(page, candidate.get("email",""),
                                                        candidate.get("name",""), pw)
            if new_account.get("success"):
                logger.info(f"External: new account created at {url}")
                account = new_account
                await asyncio.sleep(2)
            else:
                logger.warning(f"External: account creation failed: {new_account.get('error')}")
                # Continue anyway — form might not require login

    # Fill application form
    fill_result = await fill_application_form(page, candidate, pdf_path, cover_letter)
    logger.info(f"External: filled {fill_result['filled']} fields, uploaded: {fill_result['uploaded']}")

    # Submit
    result = await try_submit_form(page)

    if result.get("success"):
        msg = f"Applied at {company} ({source}): {title}"
        logger.info(f"✅ {msg}")
        r = {"success": True, "portal": source, "message": msg}
        if account and "password_enc" in account:
            r["new_account"] = account
            r["account_created"] = True
        return r

    # Final check — look at page text for confirmation
    try:
        body = (await page.inner_text("body")).lower()
        if any(p in body for p in ["application submitted", "thank you", "received your application",
                                    "successfully applied", "application complete"]):
            return {"success": True, "portal": source,
                    "message": f"Applied at {company} — confirmation text detected"}
    except:
        pass

    return {
        "success": False, "status": "FAILED", "portal": source,
        "error": f"Could not complete form at {url}. {result.get('error','')}. "
                 f"Apply manually at: {job.get('apply_url','')}",
    }


# ─── Main Tool ────────────────────────────────────────────────────────────────

@tool
def apply_to_job(
    candidate_json: str,
    job_json: str,
    pdf_path: str,
    portal_account_json: str = "null",
    cover_letter: str = ""
) -> str:
    """
    Apply to a job using headless browser automation.

    Handles two paths automatically:
    - Easy Apply (LinkedIn, Naukri quick apply, Indeed easy apply)
    - External apply (company careers portal — creates account, fills form, uploads resume)

    Args:
        candidate_json: Full candidate profile JSON
        job_json: Job details JSON (must include portal and apply_url)
        pdf_path: Absolute path to tailored PDF resume on disk
        portal_account_json: Existing portal credentials JSON or "null"
        cover_letter: Cover letter text for application forms

    Returns:
        JSON: {success, status, message/error, new_account?, account_created?}
        status = APPLIED | FAILED | SKIPPED
    """
    async def _run():
        try:
            from playwright.async_api import async_playwright

            candidate = json.loads(candidate_json) if isinstance(candidate_json, str) else candidate_json
            job       = json.loads(job_json)       if isinstance(job_json, str)       else job_json
            # Safely parse account — LLM sometimes passes malformed JSON or plain text
            account = None
            if portal_account_json and portal_account_json.strip() not in ("null", "None", "", "{}"):
                try:
                    parsed = json.loads(portal_account_json)
                    if isinstance(parsed, dict):
                        # Unwrap {"found": true, "account": {...}} wrapper
                        if parsed.get("account"):
                            account = parsed["account"]
                        elif parsed.get("found") is False:
                            account = None
                        elif parsed.get("username") or parsed.get("password_enc"):
                            account = parsed
                except (json.JSONDecodeError, ValueError) as je:
                    logger.warning(f"Could not parse portal_account_json: {je} — value: {str(portal_account_json)[:80]}")
                    account = None

            portal  = job.get("portal", "unknown").lower()
            title   = job.get("title", "Unknown")
            company = job.get("company", "Unknown")

            logger.info(f"🚀 Applying: {title} at {company} | portal={portal} | account={'yes' if account else 'no'}")

            if not pdf_path or not os.path.exists(pdf_path):
                logger.warning(f"PDF not found at '{pdf_path}' — will attempt apply without upload")

            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox",
                          "--disable-dev-shm-usage",
                          "--disable-blink-features=AutomationControlled"]
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()

                handlers = {
                    "linkedin":  apply_linkedin,
                    "naukri":    apply_naukri,
                    "indeed":    apply_indeed,
                    "instahyre": apply_instahyre,
                    "adzuna":    apply_adzuna,
                }

                handler = handlers.get(portal)
                if not handler:
                    logger.warning(f"No specific handler for '{portal}' — using generic external apply")
                    await page.goto(job.get("apply_url",""), wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(3)
                    result = await apply_external(page, candidate, job, pdf_path,
                                                  cover_letter, account, source=portal)
                else:
                    result = await handler(page, candidate, job, pdf_path, cover_letter, account)

                # If account needed and creation possible, retry
                if not result.get("success") and result.get("needs_account"):
                    logger.info(f"Creating new {portal} account for {candidate.get('email')}")
                    pw_new = generate_password()
                    await page.goto(
                        {"naukri":    "https://www.naukri.com/registration-login",
                         "indeed":    "https://secure.indeed.com/account/register",
                         "linkedin":  "https://www.linkedin.com/signup",
                         "instahyre": "https://www.instahyre.com/register",
                         }.get(portal, job.get("apply_url","")),
                        wait_until="domcontentloaded", timeout=30000
                    )
                    await asyncio.sleep(2)
                    new_acc = await create_account_on_page(
                        page, candidate.get("email",""), candidate.get("name",""), pw_new
                    )
                    if new_acc.get("success"):
                        result = await handler(page, candidate, job, pdf_path, cover_letter, new_acc)
                        result["new_account"]    = new_acc
                        result["account_created"] = True
                    else:
                        result["error"] = f"Account creation also failed: {new_acc.get('error')}"

                await browser.close()

                # Normalise status
                if result.get("success"):
                    status = "APPLIED"
                elif result.get("status") == "SKIPPED":
                    status = "SKIPPED"
                else:
                    status = "FAILED"

                err = result.get("error","")
                logger.info(f"📋 {status}: {title} at {company} | {err or result.get('message','')}")

                return {**result, "status": status}

        except ImportError:
            msg = "Playwright not installed — run: playwright install chromium"
            logger.error(msg)
            return {"success": False, "status": "FAILED", "error": msg}
        except Exception as e:
            logger.error(f"apply_to_job unhandled: {e}")
            return {"success": False, "status": "FAILED", "error": f"Exception: {str(e)[:400]}"}

    try:
        return json.dumps(asyncio.run(_run()))
    except Exception as e:
        logger.error(f"apply_to_job outer: {e}")
        return json.dumps({"success": False, "status": "FAILED", "error": str(e)})
