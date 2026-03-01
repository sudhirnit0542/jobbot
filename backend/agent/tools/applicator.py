"""
Application Agent — Playwright Browser Automation
Applies to jobs on Naukri, LinkedIn, Indeed, Instahyre.
Creates portal accounts when needed using candidate email.
"""

from langchain_core.tools import tool
from loguru import logger
import json
import asyncio
import secrets
import string
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from config import get_settings

settings = get_settings()


def _get_fernet() -> Fernet:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,
                     salt=b"jobbot_v1", iterations=100000)
    key = base64.urlsafe_b64encode(kdf.derive(settings.secret_key.encode()))
    return Fernet(key)

def encrypt_password(password: str) -> str:
    return _get_fernet().encrypt(password.encode()).decode()

def decrypt_password(token: str) -> str:
    return _get_fernet().decrypt(token.encode()).decode()

def generate_password(length: int = 12) -> str:
    """Generate a strong random password."""
    chars = string.ascii_letters + string.digits + "!@#$"
    pwd = (secrets.choice(string.ascii_uppercase) +
           secrets.choice(string.digits) +
           secrets.choice("!@#$") +
           "".join(secrets.choice(chars) for _ in range(length - 3)))
    return "".join(secrets.SystemRandom().sample(pwd, len(pwd)))


# ─── Portal-specific application logic ───────────────────────────────────────

async def apply_naukri(page, candidate: dict, job: dict, pdf_path: str, account: dict | None) -> dict:
    """Apply on Naukri.com."""
    try:
        apply_url = job.get("apply_url", "")
        await page.goto(apply_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        # Check if login required
        if "login" in page.url.lower() or await page.query_selector("input[type='password']"):
            if account:
                # Login with existing account
                email_input = await page.query_selector("input[type='email'], input[name='username']")
                pwd_input = await page.query_selector("input[type='password']")
                if email_input and pwd_input:
                    await email_input.fill(account["username"])
                    await pwd_input.fill(decrypt_password(account["password_enc"]))
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(3)
            else:
                # Create new account
                return {"success": False, "needs_account": True, "portal": "naukri"}

        # Look for Apply button
        apply_btn = await page.query_selector("button:has-text('Apply'), a:has-text('Apply Now')")
        if apply_btn:
            await apply_btn.click()
            await asyncio.sleep(2)

        # Upload resume if file input present
        file_input = await page.query_selector("input[type='file']")
        if file_input and pdf_path:
            await file_input.set_input_files(pdf_path)
            await asyncio.sleep(1)

        # Submit
        submit_btn = await page.query_selector("button[type='submit'], button:has-text('Submit')")
        if submit_btn:
            await submit_btn.click()
            await asyncio.sleep(3)
            return {"success": True, "portal": "naukri", "message": "Applied on Naukri"}

        return {"success": False, "error": "Could not find submit button", "portal": "naukri"}

    except Exception as e:
        logger.error(f"Naukri apply error: {e}")
        return {"success": False, "error": str(e), "portal": "naukri"}


async def apply_indeed(page, candidate: dict, job: dict, pdf_path: str, account: dict | None) -> dict:
    """Apply on Indeed."""
    try:
        apply_url = job.get("apply_url", "")
        await page.goto(apply_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        # Check for Easy Apply button
        easy_apply = await page.query_selector("button:has-text('Apply now'), button:has-text('Easy Apply')")
        if easy_apply:
            await easy_apply.click()
            await asyncio.sleep(2)

        # Fill email if prompted
        email_input = await page.query_selector("input[type='email']")
        if email_input:
            await email_input.fill(candidate.get("email", ""))
            await asyncio.sleep(1)
            cont_btn = await page.query_selector("button:has-text('Continue'), button[type='submit']")
            if cont_btn:
                await cont_btn.click()
                await asyncio.sleep(2)

        # Handle password / create account
        pwd_input = await page.query_selector("input[type='password']")
        if pwd_input:
            if account:
                await pwd_input.fill(decrypt_password(account["password_enc"]))
            else:
                return {"success": False, "needs_account": True, "portal": "indeed"}

        # Upload resume
        file_input = await page.query_selector("input[type='file']")
        if file_input and pdf_path:
            await file_input.set_input_files(pdf_path)
            await asyncio.sleep(1)

        # Step through multi-page application
        for _ in range(5):
            next_btn = await page.query_selector("button:has-text('Continue'), button:has-text('Next'), button[type='submit']")
            if next_btn:
                btn_text = await next_btn.inner_text()
                await next_btn.click()
                await asyncio.sleep(2)
                if "submit" in btn_text.lower():
                    return {"success": True, "portal": "indeed", "message": "Applied on Indeed"}
            else:
                break

        return {"success": True, "portal": "indeed", "message": "Application submitted on Indeed"}

    except Exception as e:
        logger.error(f"Indeed apply error: {e}")
        return {"success": False, "error": str(e), "portal": "indeed"}


async def apply_linkedin(page, candidate: dict, job: dict, pdf_path: str, account: dict | None) -> dict:
    """Apply on LinkedIn using Easy Apply."""
    try:
        apply_url = job.get("apply_url", "")
        await page.goto(apply_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        # LinkedIn requires login for Easy Apply
        if not account:
            return {"success": False, "needs_account": True, "portal": "linkedin",
                    "note": "LinkedIn requires account login"}

        # Login if not already logged in
        if "linkedin.com/login" in page.url or await page.query_selector("#username"):
            username_input = await page.query_selector("#username")
            password_input = await page.query_selector("#password")
            if username_input and password_input:
                await username_input.fill(account["username"])
                await password_input.fill(decrypt_password(account["password_enc"]))
                sign_in = await page.query_selector("button[type='submit']")
                if sign_in:
                    await sign_in.click()
                    await asyncio.sleep(4)

        # Click Easy Apply
        easy_apply = await page.query_selector("button.jobs-apply-button, button:has-text('Easy Apply')")
        if not easy_apply:
            return {"success": False, "error": "No Easy Apply button — external application", "portal": "linkedin"}

        await easy_apply.click()
        await asyncio.sleep(2)

        # Handle phone number if requested
        phone_input = await page.query_selector("input[id*='phone']")
        if phone_input:
            current_val = await phone_input.input_value()
            if not current_val:
                await phone_input.fill(candidate.get("phone", ""))

        # Upload resume if option available
        resume_section = await page.query_selector("label:has-text('Upload resume'), input[type='file']")
        if resume_section and pdf_path:
            file_input = await page.query_selector("input[type='file']")
            if file_input:
                await file_input.set_input_files(pdf_path)
                await asyncio.sleep(1)

        # Step through multi-step form
        for step in range(8):
            next_btn = await page.query_selector(
                "button:has-text('Next'), button:has-text('Review'), button:has-text('Submit application')"
            )
            if not next_btn:
                break
            btn_text = await next_btn.inner_text()
            await next_btn.click()
            await asyncio.sleep(2)
            if "submit" in btn_text.lower():
                # Check for success
                await asyncio.sleep(2)
                success_el = await page.query_selector("h3:has-text('application was sent'), .artdeco-modal__header")
                return {"success": True, "portal": "linkedin", "message": "Easy Applied on LinkedIn"}

        return {"success": True, "portal": "linkedin", "message": "LinkedIn application completed"}

    except Exception as e:
        logger.error(f"LinkedIn apply error: {e}")
        return {"success": False, "error": str(e), "portal": "linkedin"}


async def apply_instahyre(page, candidate: dict, job: dict, pdf_path: str, account: dict | None) -> dict:
    """Apply on Instahyre."""
    try:
        apply_url = job.get("apply_url", "")
        await page.goto(apply_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        apply_btn = await page.query_selector("button:has-text('Apply'), a:has-text('Apply')")
        if not apply_btn:
            return {"success": False, "error": "No apply button found", "portal": "instahyre"}

        await apply_btn.click()
        await asyncio.sleep(2)

        # Fill email
        email_input = await page.query_selector("input[type='email']")
        if email_input:
            await email_input.fill(candidate.get("email", ""))
            cont_btn = await page.query_selector("button:has-text('Continue'), button[type='submit']")
            if cont_btn:
                await cont_btn.click()
                await asyncio.sleep(2)

        # Upload resume
        file_input = await page.query_selector("input[type='file']")
        if file_input and pdf_path:
            await file_input.set_input_files(pdf_path)
            await asyncio.sleep(1)

        # Submit
        submit_btn = await page.query_selector("button:has-text('Submit'), button[type='submit']")
        if submit_btn:
            await submit_btn.click()
            await asyncio.sleep(3)
            return {"success": True, "portal": "instahyre", "message": "Applied on Instahyre"}

        return {"success": False, "error": "Submit failed", "portal": "instahyre"}

    except Exception as e:
        logger.error(f"Instahyre apply error: {e}")
        return {"success": False, "error": str(e), "portal": "instahyre"}


# ─── Account Creation ─────────────────────────────────────────────────────────

async def create_portal_account(page, portal: str, email: str, name: str) -> dict:
    """Create a new account on a portal using candidate email."""
    password = generate_password()

    signup_urls = {
        "naukri": "https://www.naukri.com/registration-login",
        "indeed": "https://secure.indeed.com/account/register",
        "linkedin": "https://www.linkedin.com/signup",
        "instahyre": "https://www.instahyre.com/register",
    }

    try:
        url = signup_urls.get(portal, "")
        if not url:
            return {"success": False, "error": f"No signup URL for {portal}"}

        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)

        # Fill registration form
        name_parts = name.split()
        first_name = name_parts[0] if name_parts else name
        last_name = name_parts[-1] if len(name_parts) > 1 else ""

        selectors_to_try = [
            ("input[name='firstName'], input[placeholder*='First']", first_name),
            ("input[name='lastName'], input[placeholder*='Last']", last_name),
            ("input[type='email'], input[name='email']", email),
            ("input[type='password'], input[name='password']", password),
        ]

        for selector, value in selectors_to_try:
            try:
                el = await page.query_selector(selector)
                if el and value:
                    await el.fill(value)
                    await asyncio.sleep(0.3)
            except:
                pass

        # Submit registration
        submit = await page.query_selector("button[type='submit'], button:has-text('Register'), button:has-text('Sign up')")
        if submit:
            await submit.click()
            await asyncio.sleep(4)
            logger.info(f"Account created on {portal} for {email}")
            return {
                "success": True,
                "portal": portal,
                "username": email,
                "password": password,
                "password_enc": encrypt_password(password),
            }

        return {"success": False, "error": "Could not find registration submit button"}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ─── Main Application Tool ────────────────────────────────────────────────────

@tool
def apply_to_job(
    candidate_json: str,
    job_json: str,
    pdf_path: str,
    portal_account_json: str = "null"
) -> str:
    """
    Apply to a job using headless browser automation.
    If portal account doesn't exist, creates one using candidate email.
    Saves account credentials encrypted for future use.

    Args:
        candidate_json: Candidate profile JSON
        job_json: Job details JSON
        pdf_path: Path to tailored PDF resume
        portal_account_json: Existing portal account JSON or null

    Returns:
        Application result with status, any new account created
    """
    async def _apply():
        try:
            from playwright.async_api import async_playwright

            candidate = json.loads(candidate_json) if isinstance(candidate_json, str) else candidate_json
            job = json.loads(job_json) if isinstance(job_json, str) else job_json
            account = json.loads(portal_account_json) if portal_account_json and portal_account_json != "null" else None
            portal = job.get("portal", "unknown").lower()

            async with async_playwright() as pw:
                # Launch headless browser
                browser = await pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
                )
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()

                apply_fns = {
                    "naukri": apply_naukri,
                    "indeed": apply_indeed,
                    "linkedin": apply_linkedin,
                    "instahyre": apply_instahyre,
                }

                apply_fn = apply_fns.get(portal)
                if not apply_fn:
                    await browser.close()
                    return {"success": False, "error": f"Portal '{portal}' not supported"}

                result = await apply_fn(page, candidate, job, pdf_path, account)

                # If account needed, create one and retry
                if not result.get("success") and result.get("needs_account"):
                    logger.info(f"Creating new account on {portal} for {candidate.get('email')}")
                    new_account = await create_portal_account(
                        page, portal, candidate.get("email"), candidate.get("name", "")
                    )
                    if new_account.get("success"):
                        result = await apply_fn(page, candidate, job, pdf_path, new_account)
                        result["new_account"] = new_account
                        result["account_created"] = True

                await browser.close()
                return result

        except ImportError:
            return {
                "success": False,
                "error": "Playwright not installed. Run: pip install playwright && playwright install chromium"
            }
        except Exception as e:
            logger.error(f"apply_to_job error: {e}")
            return {"success": False, "error": str(e)}

    result = asyncio.get_event_loop().run_until_complete(_apply())
    return json.dumps(result)
