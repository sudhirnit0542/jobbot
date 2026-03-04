# 🤖 JobBot — AI-Powered Automatic Job Application Agent

JobBot is a multi-user agentic AI system that automatically searches jobs across multiple portals, scores them against your profile, builds tailored resumes from your uploaded CV, and submits applications — all without manual effort.

> Built with LangGraph · FastAPI · React · Supabase · Playwright · 100% free AI models

---

## ✨ Features

- **Multi-user auth** — sign up / log in with email+password or Google OAuth (Supabase Auth)
- **Multi-portal job search** — Naukri, LinkedIn, Indeed, Instahyre, Adzuna
- **AI-powered match scoring** — scores each job 0–100% against your skills and experience
- **Auto-apply** — only applies to jobs with ≥80% match score
- **PDF CV upload** — upload your existing CV; AI parses every section (experience, education, certifications, projects, skills)
- **Tailored resumes** — builds a unique PDF per job with JD keywords injected and skills reordered for ATS
- **Cover letter generation** — AI-written cover letter per job
- **Two-path apply** — Easy Apply (LinkedIn, Naukri Quick Apply) AND external company portals (creates account, fills form, uploads PDF)
- **Portal account creation** — auto-creates accounts on job portals when needed
- **Encrypted credential storage** — portal passwords stored AES-encrypted per user
- **Application tracker** — live dashboard: Applied ✅ · Skipped ⏭ · Failed ❌ · Interview 🎯 with failure reasons
- **Resume download** — view or download every generated PDF from the tracker
- **Multi-model AI fallback** — Groq → Gemini → Zhipu → Groq 8B (auto-switches on rate limits)
- **Job batching** — processes up to 4 jobs per batch to avoid LangGraph recursion limits

---

## 🏗️ Architecture

```
User (Google OAuth / Email Login)
         ↓
    Supabase Auth  →  JWT (ES256)
         ↓
    FastAPI Backend  (validates JWT via JWKS)
         ↓
    LangGraph Agent
         ↓
   ┌─────────────────────────────────────┐
   │  Job Search                         │
   │  Naukri · LinkedIn · Indeed         │
   │  Instahyre · Adzuna                 │
   └──────────────┬──────────────────────┘
                  ↓
   ┌─────────────────────────────────────┐
   │  JD Analyser + Match Scorer         │
   │  Extract keywords · Score 0–100     │
   └──────────────┬──────────────────────┘
                  ↓  (≥80% only)
   ┌─────────────────────────────────────┐
   │  Resume Builder                     │
   │  Parse uploaded CV · Merge profile  │
   │  Inject JD keywords · Generate PDF  │
   └──────────────┬──────────────────────┘
                  ↓
   ┌─────────────────────────────────────┐
   │  Application Agent (Playwright)     │
   │  Path A: Easy Apply                 │
   │  Path B: External company portal    │
   │    → detect login wall              │
   │    → create account if needed       │
   │    → fill form fields               │
   │    → upload PDF resume              │
   │    → submit                         │
   └──────────────┬──────────────────────┘
                  ↓
   ┌─────────────────────────────────────┐
   │  Supabase PostgreSQL                │
   │  jobs · resumes · applications      │
   │  portal_accounts · search_sessions  │
   └─────────────────────────────────────┘
```

---

## 🤖 AI Model Fallback Chain

All models are **free**. JobBot auto-switches when any hits a rate limit:

| Priority | Model | Provider | Free Limits |
|---|---|---|---|
| 1st | `llama-3.3-70b-versatile` | [Groq](https://console.groq.com) | 6k RPD, best tool use |
| 2nd | `gemini-2.5-flash-lite` | [Google AI Studio](https://aistudio.google.com) | 1500 RPD |
| 3rd | `glm-4-flash` | [Zhipu AI](https://open.bigmodel.cn) | Generous free tier |
| 4th | `llama-3.1-8b-instant` | [Groq](https://console.groq.com) | Very high RPM, last resort |

---

## 📁 Project Structure

```
jobbot/
├── backend/
│   ├── main.py                    # FastAPI — all endpoints + JWT auth middleware
│   ├── config.py                  # Environment variables
│   ├── requirements.txt
│   ├── runtime.txt                # Python 3.11
│   ├── agent/
│   │   ├── graph.py               # LangGraph agent + model fallback chain
│   │   └── tools/
│   │       ├── job_search.py      # Search all 5 portals
│   │       ├── matcher.py         # JD keyword extraction + match scoring
│   │       ├── resume_builder.py  # CV parser + tailored PDF generation
│   │       ├── applicator.py      # Playwright — Easy Apply + external portal apply
│   │       └── repository.py      # Save/read all data from Supabase
│   └── db/
│       └── supabase_client.py     # All Supabase operations (sync)
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── vercel.json
│   └── src/
│       ├── main.jsx
│       └── App.jsx                # React SPA — Login · Profile · Search · Tracker
├── supabase/
│   └── schema.sql                 # Full schema + RLS policies + auth trigger
└── .gitignore
```

---

## 🚀 Setup & Deployment

### 1. Supabase — Database + Auth

1. Create a project at [supabase.com](https://supabase.com)
2. **SQL Editor** → paste `supabase/schema.sql` → **Run**
   - Creates all tables, RLS policies, and the `handle_new_user` trigger
3. **Authentication → Providers → Email** — enable (on by default)
4. **Authentication → Providers → Google** — enable, add OAuth credentials:
   - Get credentials at [console.cloud.google.com](https://console.cloud.google.com) → APIs & Services → Credentials → OAuth 2.0 Client ID
   - Authorized redirect URI: `https://<project-ref>.supabase.co/auth/v1/callback`
5. **Authentication → URL Configuration**:
   ```
   Site URL:       https://your-app.vercel.app
   Redirect URLs:  https://your-app.vercel.app
                   https://your-app.vercel.app/**
                   http://localhost:3000
                   http://localhost:3000/**
   ```
6. **Settings → API** → copy:
   - **Project URL** → `SUPABASE_URL`
   - **service_role secret** → `SUPABASE_SERVICE_KEY`
   - *(JWT Secret is no longer needed — backend uses JWKS auto-discovery)*

### 2. Get Free AI API Keys

| Service | URL | Notes |
|---|---|---|
| Groq | [console.groq.com](https://console.groq.com) | Free, high RPM |
| Google Gemini | [aistudio.google.com](https://aistudio.google.com) | Free tier |
| Zhipu AI | [open.bigmodel.cn](https://open.bigmodel.cn) | Free, register with email |
| Adzuna | [developer.adzuna.com](https://developer.adzuna.com) | Free, 1M calls/month |

### 3. Render — Backend

1. [render.com](https://render.com) → **New → Web Service** → connect your repo
2. Settings:
   - **Root Directory**: `backend`
   - **Build Command**: `pip install -r requirements.txt && playwright install chromium && playwright install-deps chromium`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
3. Environment Variables:

| Key | Value |
|---|---|
| `SUPABASE_URL` | `https://xxxx.supabase.co` |
| `SUPABASE_SERVICE_KEY` | `eyJ...` service_role key |
| `GROQ_API_KEY` | From console.groq.com |
| `GOOGLE_API_KEY` | From aistudio.google.com |
| `ZHIPU_API_KEY` | From open.bigmodel.cn |
| `ADZUNA_APP_ID` | From developer.adzuna.com |
| `ADZUNA_API_KEY` | From developer.adzuna.com |
| `SECRET_KEY` | Any random 32-char string (for encrypting portal passwords) |
| `ALLOWED_ORIGINS` | Your Vercel URL |
| `MIN_MATCH_SCORE` | `80.0` (optional, default 80) |

### 4. Vercel — Frontend

1. [vercel.com](https://vercel.com) → **New Project** → import repo
2. **Root Directory**: `frontend` · **Framework**: Vite
3. Environment Variables:

| Key | Value |
|---|---|
| `VITE_API_URL` | `https://your-jobbot-api.onrender.com` |
| `VITE_SUPABASE_URL` | `https://xxxx.supabase.co` |
| `VITE_SUPABASE_ANON_KEY` | `eyJ...` anon/public key from Supabase Settings → API |

4. After deploy, update `ALLOWED_ORIGINS` on Render with your Vercel URL

---

## 🔑 Local Development

### Backend `.env`

```env
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...

GROQ_API_KEY=gsk_...
GOOGLE_API_KEY=AIza...
ZHIPU_API_KEY=...
ADZUNA_APP_ID=...
ADZUNA_API_KEY=...

SECRET_KEY=your-random-32-char-secret-key!!
ALLOWED_ORIGINS=http://localhost:3000
MIN_MATCH_SCORE=80.0
```

### Frontend `.env`

```env
VITE_API_URL=http://localhost:8000
VITE_SUPABASE_URL=https://xxxx.supabase.co
VITE_SUPABASE_ANON_KEY=eyJ...
```

### Run locally

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
uvicorn main:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev -- --port 3000
```

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

---

## 📖 How It Works

### Step 1 — Sign Up / Log In
- Create an account with email + password, or click **Continue with Google**
- Each user's data is fully isolated (Supabase Row Level Security)

### Step 2 — Build Your Profile
- Fill in your name, phone, location, LinkedIn, skills, experience
- **Upload your CV as PDF** — AI parses every section:
  - Work history (role, company, duration, bullet achievements)
  - Education (degree, institution, year, grade)
  - Certifications and projects
  - Skills (merged and deduplicated with your profile)

### Step 3 — Search Jobs
- Enter a job title (e.g. "Product Manager", "Senior Python Developer")
- Select portals to search
- JobBot searches all selected portals and scores each job 0–100% against your profile
- Results grouped: **Strong Match ≥80%** / Review 60–79% / Low Match <60%

### Step 4 — Auto Apply
- Click **Auto Apply Now** for all ≥80% matched jobs
- For each job, JobBot:
  1. Builds a tailored PDF resume — CV data + JD keywords injected, skills reordered for ATS
  2. Generates a cover letter
  3. Opens a headless Chromium browser
  4. **Path A (Easy Apply)** — LinkedIn Easy Apply, Naukri Quick Apply, Indeed Easy Apply
  5. **Path B (External)** — navigates to company careers page, creates account if needed, fills every field, uploads PDF, submits
  6. Saves application result with status and failure reason if any

### Step 5 — Track Applications
- Switch to **Applications** tab to see live status
- Each row shows: company, role, portal, match score, status badge, failure reason, and **View/Download PDF** links
- Hover any failure reason to see the full error message

---

## 🔐 Authentication & Security

| Concern | Solution |
|---|---|
| User login | Supabase Auth (email+password, Google OAuth) |
| JWT algorithm | ES256 (elliptic curve) — verified via JWKS auto-discovery |
| Data isolation | Supabase Row Level Security — each user sees only their own data |
| Portal passwords | AES-encrypted with app `SECRET_KEY` before storing |
| API protection | All endpoints require `Authorization: Bearer <token>` |

> **Note:** The backend validates JWTs by fetching Supabase's public JWKS from  
> `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` — no JWT secret needed in env vars.

---

## 🗄️ Database Schema

| Table | Purpose |
|---|---|
| `candidates` | Profile, skills, CV text, experience — linked to `auth.users` via `user_id` |
| `jobs` | All jobs found across portals |
| `resumes` | Tailored resume per job, match score, PDF path |
| `applications` | Status per job — APPLIED / FAILED / SKIPPED / INTERVIEW / OFFER |
| `portal_accounts` | Encrypted credentials per portal per user |
| `search_sessions` | Log of each search run |

Row Level Security ensures every query is automatically scoped to the authenticated user.

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Auth** | Supabase Auth (ES256 JWT, Google OAuth, email/password) |
| **AI Agent** | LangGraph (stateful agentic workflow) |
| **LLMs** | Groq · Google Gemini · Zhipu AI (4-model fallback chain) |
| **Backend** | FastAPI + Python 3.11 |
| **Browser Automation** | Playwright (headless Chromium) |
| **PDF Generation** | xhtml2pdf |
| **CV Parsing** | pdfplumber + custom regex section parser |
| **Database** | Supabase (PostgreSQL + RLS) |
| **Frontend** | React + Vite + Supabase JS v2 |
| **Backend Deploy** | Render |
| **Frontend Deploy** | Vercel |

---

## 🐛 Troubleshooting

**Google OAuth stays on the hash URL after redirect**
- Set `flowType: "implicit"` in the Supabase client config (already done in this repo)
- Ensure your redirect URL is in Supabase → Authentication → URL Configuration

**401 Unauthorized on API calls**
- Supabase now issues ES256 tokens — the backend verifies via JWKS, not the JWT secret
- Make sure `SUPABASE_URL` is set correctly on Render so JWKS can be fetched

**Resume PDF only shows name and skills (no experience)**
- Re-upload your CV PDF — the parser has been rewritten to handle all common CV formats
- Check Render logs for `CV: X roles extracted` to confirm parsing worked

**Applications all showing FAILED**
- Check the Reason column in the tracker for the exact error
- Common causes: CAPTCHA on portal, OTP required, no Easy Apply button (external apply attempted)

**Recursion limit error (large batches)**
- Jobs are processed in batches of 4 automatically
- Each batch gets a dynamic recursion limit based on batch size

---

## ⚠️ Disclaimer

JobBot is a personal productivity tool. Be mindful of each job portal's Terms of Service regarding automated applications. Use responsibly — only apply to roles you are genuinely interested in and qualified for. The authors accept no liability for account bans or application errors.

---

## 👤 Author

Built by Sudhir Verma as a personal AI agent project.

> *"AI didn't write this for me. AI built it with me."*

---

## 📄 License

MIT — free to use, fork, and modify.
