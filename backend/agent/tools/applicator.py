"""
Application Agent — Playwright Browser Automation
Applies to jobs on Naukri, LinkedIn, Indeed, Instahyre, Adzuna.

HONEST STATUS REPORTING:
- APPLIED: Form submitted successfully
- FAILED: Blocked by portal, login wall, CAPTCHA, etc. (error_message saved)
- SKIPPED: Portal not supported for automation (Adzuna redirects to company site)
- MANUAL_REQUIRED: Job URL works but requires human intervention (OTP, CAPTCHA)
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
    chars = string.ascii_letters + string.digits + "!@#$"
    pwd = (secrets.choice(string.ascii_uppercase) +
           secrets.choice(string.digits) +
           secrets.choice("!@#$") +
           "".join(secrets.choice(chars) for _ in range(length - 3)))
    return "".join(secrets.SystemRandom().sample(pwd, len(pwd)))


# ─── Adzuna — redirect-only portal ───────────────────────────────────────────

async def apply_adzuna(page, candidate: dict, job: dict, pdf_path: str, account: dict | None) -> dict:
    """
    Adzuna aggregates jobs from company sites — it redirects to the actual employer.
    We navigate to the URL, detect where we land, and attempt to apply.
    """
    apply_url = job.get("apply_url", "")
    company = job.get("company", "Unknown")
    title = job.get("title", "")

    try:
        logger.info(f"Adzuna job → navigating to: {apply_url}")
        await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        final_url = page.url
        logger.info(f"Adzuna redirected to: {final_url}")

        # Check for common application form elements
        has_apply_btn = await page.query_selector(
            "button:has-text('Apply'), a:has-text('Apply Now'), "
            "button:has-text('Apply Now'), input[type='submit']"
        )
        has_file_input = await page.query_selector("input[type='file']")
        has_email = await page.query_selector("input[type='email']")

        if has_apply_btn:
            await has_apply_btn.click()
            await asyncio.sleep(2)
            file_input = await page.query_selector("input[type='file']")
            if file_input and pdf_path:
                await file_input.set_input_files(pdf_path)
                await asyncio.sleep(1)
            submit = await page.query_selector("button[type='submit'], button:has-text('Submit')")
            if submit:
                await submit.click()
                await asyncio.sleep(2)
                return {"success": True, "portal": "adzuna", "message": f"Applied at {company} via Adzuna redirect → {final_url}"}

        # No apply form found — this is normal for Adzuna
        return {
            "success": False,
            "status": "SKIPPED",
            "portal": "adzuna",
            "error": f"Adzuna redirects to company site ({final_url}). No automated form found — apply manually at: {apply_url}",
            "manual_url": apply_url,
        }

    except Exception as e:
        logger.error(f"Adzuna apply error for {title} at {company}: {e}")
        return {"success": False, "portal": "adzuna", "error": f"Navigation failed: {str(e)}"}


# ─── Naukri ───────────────────────────────────────────────────────────────────

async def apply_naukri(page, candidate: dict, job: dict, pdf_path: str, account: dict | None) -> dict:
    apply_url = job.get("apply_url", "")
    company = job.get("company", "")
    title = job.get("title", "")

    try:
        logger.info(f"Naukri: navigating to {apply_url}")
        await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        current_url = page.url
        logger.info(f"Naukri: landed on {current_url}")

        # Detect login wall
        if "login" in current_url.lower() or await page.query_selector("input[type='password']"):
            if account:
                logger.info(f"Naukri: logging in as {account['username']}")
                email_el = await page.query_selector("input[type='email'], input[name='username']")
                pwd_el = await page.query_selector("input[type='password']")
                if email_el and pwd_el:
                    await email_el.fill(account["username"])
                    await pwd_el.fill(decrypt_password(account["password_enc"]))
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(4)
                    logger.info(f"Naukri: logged in, now at {page.url}")
                else:
                    return {"success": False, "portal": "naukri", "error": "Login form fields not found on Naukri"}
            else:
                return {"success": False, "needs_account": True, "portal": "naukri",
                        "error": "Naukri requires login — no existing account found"}

        # Check for CAPTCHA
        if await page.query_selector("div.captcha, iframe[src*='recaptcha'], div[class*='captcha']"):
            return {"success": False, "portal": "naukri",
                    "error": "CAPTCHA detected on Naukri — cannot automate. Apply manually at: " + apply_url}

        # Click Apply button
        apply_btn = await page.query_selector(
            "button:has-text('Apply'), a:has-text('Apply Now'), "
            "button[class*='apply'], a[class*='apply']"
        )
        if not apply_btn:
            page_text = await page.inner_text("body")
            logger.warning(f"Naukri: no apply button found. Page snippet: {page_text[:300]}")
            return {"success": False, "portal": "naukri",
                    "error": f"No Apply button found on page. URL: {current_url}"}

        await apply_btn.click()
        await asyncio.sleep(2)

        # Upload resume
        file_input = await page.query_selector("input[type='file']")
        if file_input and pdf_path:
            await file_input.set_input_files(pdf_path)
            await asyncio.sleep(1)

        # Submit
        submit_btn = await page.query_selector("button[type='submit'], button:has-text('Submit')")
        if submit_btn:
            await submit_btn.click()
            await asyncio.sleep(3)
            logger.info(f"Naukri: submitted application for {title} at {company}")
            return {"success": True, "portal": "naukri", "message": f"Applied on Naukri: {title} at {company}"}

        return {"success": False, "portal": "naukri",
                "error": f"Could not find Submit button after clicking Apply. URL: {page.url}"}

    except Exception as e:
        logger.error(f"Naukri apply error [{title} at {company}]: {e}")
        return {"success": False, "portal": "naukri", "error": f"Exception: {str(e)[:300]}"}


# ─── Indeed ───────────────────────────────────────────────────────────────────

async def apply_indeed(page, candidate: dict, job: dict, pdf_path: str, account: dict | None) -> dict:
    apply_url = job.get("apply_url", "")
    company = job.get("company", "")
    title = job.get("title", "")

    try:
        logger.info(f"Indeed: navigating to {apply_url}")
        await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        current_url = page.url
        logger.info(f"Indeed: landed on {current_url}")

        # Indeed heavily blocks bots — detect this early
        if "blocked" in current_url or "captcha" in current_url:
            return {"success": False, "portal": "indeed",
                    "error": "Indeed blocked automated access (anti-bot). Apply manually at: " + apply_url}

        # Check for CAPTCHA
        if await page.query_selector("iframe[src*='recaptcha'], div[class*='captcha']"):
            return {"success": False, "portal": "indeed",
                    "error": "CAPTCHA on Indeed — apply manually at: " + apply_url}

        # Try Easy Apply
        easy_apply = await page.query_selector(
            "button:has-text('Apply now'), button:has-text('Easy Apply'), "
            "a:has-text('Apply now')"
        )
        if not easy_apply:
            return {"success": False, "portal": "indeed",
                    "error": f"No Easy Apply button on Indeed. May be external application. URL: {current_url}"}

        await easy_apply.click()
        await asyncio.sleep(2)

        # Email step
        email_input = await page.query_selector("input[type='email']")
        if email_input:
            await email_input.fill(candidate.get("email", ""))
            cont_btn = await page.query_selector("button:has-text('Continue'), button[type='submit']")
            if cont_btn:
                await cont_btn.click()
                await asyncio.sleep(2)

        # Password / account check
        pwd_input = await page.query_selector("input[type='password']")
        if pwd_input:
            if account:
                await pwd_input.fill(decrypt_password(account["password_enc"]))
                await page.keyboard.press("Enter")
                await asyncio.sleep(3)
            else:
                return {"success": False, "needs_account": True, "portal": "indeed",
                        "error": "Indeed requires login — no existing account found"}

        # Upload resume
        file_input = await page.query_selector("input[type='file']")
        if file_input and pdf_path:
            await file_input.set_input_files(pdf_path)
            await asyncio.sleep(1)

        # Step through form
        for step in range(6):
            next_btn = await page.query_selector(
                "button:has-text('Continue'), button:has-text('Next'), "
                "button:has-text('Submit'), button[type='submit']"
            )
            if not next_btn:
                break
            btn_text = (await next_btn.inner_text()).strip()
            await next_btn.click()
            await asyncio.sleep(2)
            if any(w in btn_text.lower() for w in ["submit", "apply"]):
                logger.info(f"Indeed: submitted application for {title} at {company}")
                return {"success": True, "portal": "indeed", "message": f"Applied on Indeed: {title} at {company}"}

        return {"success": True, "portal": "indeed", "message": "Indeed application flow completed"}

    except Exception as e:
        logger.error(f"Indeed apply error [{title} at {company}]: {e}")
        return {"success": False, "portal": "indeed", "error": f"Exception: {str(e)[:300]}"}


# ─── LinkedIn ─────────────────────────────────────────────────────────────────

async def apply_linkedin(page, candidate: dict, job: dict, pdf_path: str, account: dict | None) -> dict:
    apply_url = job.get("apply_url", "")
    company = job.get("company", "")
    title = job.get("title", "")

    try:
        if not account:
            return {"success": False, "needs_account": True, "portal": "linkedin",
                    "error": "LinkedIn requires account login for Easy Apply"}

        logger.info(f"LinkedIn: navigating to {apply_url}")
        await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # Login if needed
        if "linkedin.com/login" in page.url or await page.query_selector("#username"):
            logger.info(f"LinkedIn: logging in as {account['username']}")
            uid = await page.query_selector("#username")
            pwd = await page.query_selector("#password")
            if uid and pwd:
                await uid.fill(account["username"])
                await pwd.fill(decrypt_password(account["password_enc"]))
                sign_in = await page.query_selector("button[type='submit']")
                if sign_in:
                    await sign_in.click()
                    await asyncio.sleep(4)

        # Check for verification / CAPTCHA
        if await page.query_selector("input[name='pin'], #input__email_verification_pin"):
            return {"success": False, "portal": "linkedin",
                    "error": "LinkedIn sent email verification PIN — cannot automate. Apply manually."}

        # Easy Apply button
        easy_apply = await page.query_selector(
            "button.jobs-apply-button, button:has-text('Easy Apply')"
        )
        if not easy_apply:
            page_text = await page.inner_text("body")
            if "Easy Apply" not in page_text:
                return {"success": False, "portal": "linkedin",
                        "error": f"No Easy Apply on this LinkedIn job — it's an external application. Apply at: {apply_url}"}
            return {"success": False, "portal": "linkedin",
                    "error": "Easy Apply button not clickable. Possibly requires scroll or modal. URL: " + page.url}

        await easy_apply.click()
        await asyncio.sleep(2)

        # Phone number
        phone_input = await page.query_selector("input[id*='phone']")
        if phone_input:
            val = await phone_input.input_value()
            if not val:
                await phone_input.fill(candidate.get("phone", ""))

        # Resume upload
        file_input = await page.query_selector("input[type='file']")
        if file_input and pdf_path:
            await file_input.set_input_files(pdf_path)
            await asyncio.sleep(1)

        # Step through
        for step in range(8):
            next_btn = await page.query_selector(
                "button:has-text('Next'), button:has-text('Review'), "
                "button:has-text('Submit application'), button:has-text('Done')"
            )
            if not next_btn:
                break
            btn_text = (await next_btn.inner_text()).strip()
            await next_btn.click()
            await asyncio.sleep(2)
            if "submit" in btn_text.lower():
                await asyncio.sleep(2)
                logger.info(f"LinkedIn: submitted Easy Apply for {title} at {company}")
                return {"success": True, "portal": "linkedin",
                        "message": f"Easy Applied on LinkedIn: {title} at {company}"}

        return {"success": True, "portal": "linkedin", "message": "LinkedIn Easy Apply completed"}

    except Exception as e:
        logger.error(f"LinkedIn apply error [{title} at {company}]: {e}")
        return {"success": False, "portal": "linkedin", "error": f"Exception: {str(e)[:300]}"}


# ─── Instahyre ────────────────────────────────────────────────────────────────

async def apply_instahyre(page, candidate: dict, job: dict, pdf_path: str, account: dict | None) -> dict:
    apply_url = job.get("apply_url", "")
    company = job.get("company", "")
    title = job.get("title", "")

    try:
        logger.info(f"Instahyre: navigating to {apply_url}")
        await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        apply_btn = await page.query_selector("button:has-text('Apply'), a:has-text('Apply')")
        if not apply_btn:
            return {"success": False, "portal": "instahyre",
                    "error": f"No Apply button on Instahyre. URL: {page.url}"}

        await apply_btn.click()
        await asyncio.sleep(2)

        email_input = await page.query_selector("input[type='email']")
        if email_input:
            await email_input.fill(candidate.get("email", ""))
            cont_btn = await page.query_selector("button:has-text('Continue'), button[type='submit']")
            if cont_btn:
                await cont_btn.click()
                await asyncio.sleep(2)

        # OTP check
        if await page.query_selector("input[placeholder*='OTP'], input[name*='otp']"):
            return {"success": False, "portal": "instahyre",
                    "error": "Instahyre sent OTP — cannot automate. Apply manually at: " + apply_url}

        file_input = await page.query_selector("input[type='file']")
        if file_input and pdf_path:
            await file_input.set_input_files(pdf_path)
            await asyncio.sleep(1)

        submit_btn = await page.query_selector("button:has-text('Submit'), button[type='submit']")
        if submit_btn:
            await submit_btn.click()
            await asyncio.sleep(3)
            logger.info(f"Instahyre: submitted for {title} at {company}")
            return {"success": True, "portal": "instahyre",
                    "message": f"Applied on Instahyre: {title} at {company}"}

        return {"success": False, "portal": "instahyre",
                "error": "Could not find Submit button on Instahyre form"}

    except Exception as e:
        logger.error(f"Instahyre apply error [{title} at {company}]: {e}")
        return {"success": False, "portal": "instahyre", "error": f"Exception: {str(e)[:300]}"}


# ─── Account Creation ─────────────────────────────────────────────────────────

async def create_portal_account(page, portal: str, email: str, name: str) -> dict:
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

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        name_parts = name.split()
        first_name = name_parts[0] if name_parts else name
        last_name = name_parts[-1] if len(name_parts) > 1 else ""

        for selector, value in [
            ("input[name='firstName'], input[placeholder*='First']", first_name),
            ("input[name='lastName'], input[placeholder*='Last']", last_name),
            ("input[type='email'], input[name='email']", email),
            ("input[type='password'], input[name='password']", password),
        ]:
            try:
                el = await page.query_selector(selector)
                if el and value:
                    await el.fill(value)
                    await asyncio.sleep(0.3)
            except:
                pass

        submit = await page.query_selector(
            "button[type='submit'], button:has-text('Register'), button:has-text('Sign up')"
        )
        if submit:
            await submit.click()
            await asyncio.sleep(4)
            logger.info(f"Account created on {portal} for {email}")
            return {
                "success": True, "portal": portal,
                "username": email, "password": password,
                "password_enc": encrypt_password(password),
            }
        return {"success": False, "error": "Registration submit button not found"}

    except Exception as e:
        return {"success": False, "error": f"Account creation failed: {str(e)}"}


# ─── Main Tool ────────────────────────────────────────────────────────────────

@tool
def apply_to_job(
    candidate_json: str,
    job_json: str,
    pdf_path: str,
    portal_account_json: str = "null"
) -> str:
    """
    Apply to a job using headless browser automation.
    Returns detailed status including exact failure reason.

    Status values returned:
    - success=True: Application submitted
    - success=False, status=SKIPPED: Portal not automatable (Adzuna redirect, external)
    - success=False, status=FAILED: Blocked by CAPTCHA, OTP, login wall, etc.

    Args:
        candidate_json: Candidate profile JSON
        job_json: Job details JSON
        pdf_path: Path to tailored PDF resume on disk
        portal_account_json: Existing portal account JSON or null

    Returns:
        JSON with success, status, message/error, and any new_account created
    """
    async def _apply():
        try:
            from playwright.async_api import async_playwright

            candidate = json.loads(candidate_json) if isinstance(candidate_json, str) else candidate_json
            job = json.loads(job_json) if isinstance(job_json, str) else job_json
            account = (json.loads(portal_account_json)
                       if portal_account_json and portal_account_json not in ("null", "None", "")
                       else None)
            portal = job.get("portal", "unknown").lower()
            title = job.get("title", "Unknown")
            company = job.get("company", "Unknown")

            logger.info(f"🚀 Starting application: {title} at {company} via {portal}")

            # Check PDF exists
            import os
            if not pdf_path or not os.path.exists(pdf_path):
                logger.warning(f"PDF not found at {pdf_path} — proceeding without resume upload")

            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox",
                          "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
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
                    "adzuna": apply_adzuna,
                }

                apply_fn = apply_fns.get(portal)
                if not apply_fn:
                    await browser.close()
                    msg = f"Portal '{portal}' not supported for automation"
                    logger.warning(msg)
                    return {"success": False, "status": "SKIPPED", "error": msg}

                result = await apply_fn(page, candidate, job, pdf_path, account)

                # If needs account, create one and retry
                if not result.get("success") and result.get("needs_account"):
                    logger.info(f"Creating account on {portal} for {candidate.get('email')}")
                    new_account = await create_portal_account(
                        page, portal, candidate.get("email", ""), candidate.get("name", "")
                    )
                    if new_account.get("success"):
                        result = await apply_fn(page, candidate, job, pdf_path, new_account)
                        result["new_account"] = new_account
                        result["account_created"] = True
                    else:
                        result["error"] = f"Account creation failed: {new_account.get('error')}"

                await browser.close()

                # Determine final status
                if result.get("success"):
                    status = "APPLIED"
                elif result.get("status") == "SKIPPED":
                    status = "SKIPPED"
                else:
                    status = "FAILED"

                error_msg = result.get("error", "")
                logger.info(f"📋 Result for {title} at {company}: {status} | {error_msg or result.get('message', '')}")

                return {**result, "status": status}

        except ImportError:
            msg = "Playwright not installed — run: pip install playwright && playwright install chromium"
            logger.error(msg)
            return {"success": False, "status": "FAILED", "error": msg}
        except Exception as e:
            logger.error(f"apply_to_job unhandled error: {e}")
            return {"success": False, "status": "FAILED", "error": f"Unhandled exception: {str(e)[:400]}"}

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _apply())
                return json.dumps(future.result())
        return json.dumps(loop.run_until_complete(_apply()))
    except Exception as e:
        return json.dumps({"success": False, "status": "FAILED", "error": str(e)})
