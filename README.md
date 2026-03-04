# 🤖 JobBot — AI-Powered Automatic Job Application Agent

JobBot is an agentic AI system that automatically searches jobs across multiple portals, scores each against your profile, builds tailored resumes, and submits applications — all without manual effort.

> Built with LangGraph, FastAPI, React, Supabase, and Playwright. 100% free AI models.

---

## ✨ Features

- **Multi-portal job search** — Naukri, LinkedIn, Indeed, Instahyre, Adzuna
- **AI-powered matching** — scores each job against your skills and experience (0–100%)
- **Auto-apply** — only applies to jobs with ≥80% match score
- **PDF CV upload** — upload your existing CV and AI extracts your skills automatically
- **Tailored resumes** — builds a unique PDF resume per job with JD keywords injected
- **Cover letter generation** — AI-written cover letter per job
- **Portal account creation** — creates accounts on job portals automatically if needed
- **Encrypted credential storage** — passwords stored AES-encrypted in Supabase
- **Application tracker** — dashboard showing all jobs: Applied ✅ | Skipped ⏭ | Failed ❌ | Interview 🎯
- **Multi-model AI fallback** — Groq → Gemini → Zhipu → Groq 8B (auto-switches on rate limits)

---

## 🏗️ Architecture

```
Candidate Profile + PDF CV
         ↓
    Job Search Agent
  (Naukri / LinkedIn / Indeed / Instahyre / Adzuna)
         ↓
    JD Analyser
  (extract keywords, skills, experience requirements)
         ↓
    Match Scorer
  (score 0–100 vs candidate profile)
         ↓ (only ≥80% proceed)
    Resume Builder
  (inject JD keywords, reorder skills, generate PDF)
         ↓
    Application Agent
  (Playwright headless browser → fill form → submit)
         ↓
    Repository
  (Supabase — jobs, resumes, applications, portal accounts)
```

---

## 🤖 AI Model Fallback Chain

All models are **free**. JobBot automatically switches if one hits a rate limit:

| Priority | Model | Provider | Notes |
|---|---|---|---|
| 1st | `llama-3.3-70b-versatile` | Groq | Best tool use, high RPM |
| 2nd | `gemini-2.5-flash-lite` | Google | Free tier, 10 RPM |
| 3rd | `glm-4-flash` | Zhipu AI | Free, generous limits |
| 4th | `llama-3.1-8b-instant` | Groq | Very high RPM, last resort |

---

## 📁 Project Structure

```
jobbot/
├── backend/
│   ├── main.py                    # FastAPI app — all API endpoints
│   ├── config.py                  # Environment variables / settings
│   ├── requirements.txt           # Python dependencies
│   ├── runtime.txt                # Python 3.11.0 for Render
│   ├── agent/
│   │   ├── graph.py               # LangGraph agent + model fallback chain
│   │   └── tools/
│   │       ├── job_search.py      # Search Naukri/LinkedIn/Indeed/Instahyre/Adzuna
│   │       ├── matcher.py         # JD keyword extraction + candidate scoring
│   │       ├── resume_builder.py  # Tailored PDF resume generation (xhtml2pdf)
│   │       ├── applicator.py      # Playwright browser automation for applying
│   │       └── repository.py      # Save jobs/resumes/applications to Supabase
│   └── db/
│       ├── schema.sql             # Supabase table definitions
│       └── supabase_client.py     # All database operations
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── vercel.json
│   ├── index.html
│   └── src/
│       ├── main.jsx
│       └── App.jsx                # React dashboard (Profile / Search / Tracker)
├── supabase/
│   └── schema.sql                 # Run this in Supabase SQL Editor
├── render.yaml                    # Render auto-deploy config
└── .gitignore
```

---

## 🚀 Setup & Deployment

### 1. Supabase (Database)

1. Create a new project at [supabase.com](https://supabase.com)
2. Go to **SQL Editor** → paste contents of `supabase/schema.sql` → **Run**
3. Go to **Settings → API** → copy:
   - **Project URL**
   - **service_role** key (starts with `eyJ...`)

### 2. Get Free API Keys

| Service | URL | Notes |
|---|---|---|
| Groq | [console.groq.com](https://console.groq.com) | Free, high RPM |
| Google Gemini | [aistudio.google.com](https://aistudio.google.com) | Free tier |
| Zhipu AI | [open.bigmodel.cn](https://open.bigmodel.cn) | Free, register with email |
| Adzuna | [developer.adzuna.com](https://developer.adzuna.com) | Free, 1M calls/month |

### 3. Render (Backend)

1. Go to [render.com](https://render.com) → **New → Web Service**
2. Connect your `jobbot` GitHub repository
3. Settings:
   - **Root Directory**: `backend`
   - **Build Command**: `pip install -r requirements.txt && playwright install chromium && playwright install-deps chromium`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

4. Add Environment Variables:

| Key | Value |
|---|---|
| `PYTHON_VERSION` | `3.11.0` |
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Your `eyJ...` service_role key |
| `GROQ_API_KEY` | From console.groq.com |
| `GOOGLE_API_KEY` | From aistudio.google.com |
| `ZHIPU_API_KEY` | From open.bigmodel.cn |
| `ADZUNA_APP_ID` | From developer.adzuna.com |
| `ADZUNA_API_KEY` | From developer.adzuna.com |
| `SECRET_KEY` | Any random 32-char string |
| `ALLOWED_ORIGINS` | Your Vercel URL (update after step 4) |

### 4. Vercel (Frontend)

1. Go to [vercel.com](https://vercel.com) → **New Project** → import `jobbot` repo
2. Settings:
   - **Root Directory**: `frontend`
   - **Framework**: Vite
3. Add Environment Variable:

| Key | Value |
|---|---|
| `VITE_API_URL` | `https://your-jobbot-api.onrender.com` |

4. After deploy, copy your Vercel URL and update `ALLOWED_ORIGINS` on Render

---

## 🔑 Environment Variables Reference

### Backend `.env` (for local development)

```env
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...

GROQ_API_KEY=gsk_...
GOOGLE_API_KEY=AIza...
ZHIPU_API_KEY=...
ADZUNA_APP_ID=...
ADZUNA_API_KEY=...

SECRET_KEY=your-random-32-char-secret-key!!
ALLOWED_ORIGINS=http://localhost:5173
MIN_MATCH_SCORE=80.0
```

### Frontend `.env` (for local development)

```env
VITE_API_URL=http://localhost:8000
```

---

## 💻 Local Development

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate        # Mac/Linux
pip install -r requirements.txt
playwright install chromium
uvicorn main:app --reload

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Frontend: `http://localhost:5173`
Backend: `http://localhost:8000`
API docs: `http://localhost:8000/docs`

---

## 📊 How It Works

### Step 1 — Build Your Profile
- Fill in your name, email, skills, experience
- **Upload your CV as PDF** — AI auto-extracts skills and summary

### Step 2 — Search Jobs
- Enter job title (e.g. "Product Manager", "Python Developer")
- JobBot searches all 5 portals simultaneously
- Each job is scored against your profile (0–100%)
- Results shown in 3 groups: Strong Match ≥80% / Review 60–79% / Low Match <60%

### Step 3 — Auto Apply
- Click **Auto Apply Now** for all ≥80% matched jobs
- JobBot:
  - Builds a tailored PDF resume per job (JD keywords injected, skills reordered)
  - Writes a cover letter
  - Opens a headless browser
  - Creates portal account if needed (credentials saved encrypted)
  - Fills form and submits
- Switch to **Applications** tab to track live progress

---

## 🗄️ Database Schema

| Table | Purpose |
|---|---|
| `candidates` | Profile, skills, CV text, experience |
| `jobs` | All jobs found across portals |
| `resumes` | Tailored resume per job + match score |
| `applications` | Application status per job |
| `portal_accounts` | Encrypted login credentials per portal |
| `search_sessions` | Log of each search run |

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **AI Agent** | LangGraph (agentic workflow orchestration) |
| **LLMs** | Groq + Google Gemini + Zhipu + Groq 8B (fallback chain) |
| **Backend** | FastAPI + Python 3.11 |
| **Browser Automation** | Playwright (headless Chromium) |
| **PDF Generation** | xhtml2pdf |
| **PDF Parsing** | pdfplumber |
| **Database** | Supabase (PostgreSQL) |
| **Frontend** | React + Vite |
| **Backend Deploy** | Render |
| **Frontend Deploy** | Vercel |

---

## ⚠️ Disclaimer

JobBot is a personal productivity tool. Be mindful of each job portal's Terms of Service regarding automated applications. Use responsibly — apply only to roles you are genuinely interested in and qualified for.

---

## 👤 Author

Built by Sudhir Verma as a personal AI project.

> *"AI didn't write this for me. AI built it with me."*

---

## 📄 License

MIT License — free to use and modify.
