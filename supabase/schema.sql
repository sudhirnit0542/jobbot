-- ─── JobBot Database Schema ──────────────────────────────────────────────────
-- Paste this in Supabase SQL Editor and run

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Candidate profile
CREATE TABLE IF NOT EXISTS candidates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT,
    location TEXT,
    linkedin_url TEXT,
    github_url TEXT,
    portfolio_url TEXT,
    skills JSONB DEFAULT '[]',
    experience_years INTEGER DEFAULT 0,
    experience JSONB DEFAULT '[]',   -- [{company, role, duration, description, achievements}]
    education JSONB DEFAULT '[]',    -- [{degree, institution, year, grade}]
    certifications JSONB DEFAULT '[]',
    summary TEXT,
    base_resume_text TEXT,           -- Full resume as plain text for AI
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Jobs found from portals
CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    external_id TEXT,
    portal TEXT NOT NULL,            -- linkedin | naukri | indeed | instahyre | adzuna
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    job_type TEXT,                   -- full-time | remote | contract
    experience_required TEXT,
    salary_min NUMERIC,
    salary_max NUMERIC,
    description TEXT,
    keywords JSONB DEFAULT '[]',     -- AI extracted keywords
    skills_required JSONB DEFAULT '[]',
    apply_url TEXT,
    posted_date TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    found_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(portal, external_id)
);

-- Tailored resumes generated per job
CREATE TABLE IF NOT EXISTS resumes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    candidate_id UUID REFERENCES candidates(id),
    job_id UUID REFERENCES jobs(id),
    match_score NUMERIC,
    matched_keywords JSONB DEFAULT '[]',
    missing_keywords JSONB DEFAULT '[]',
    resume_text TEXT,
    cover_letter TEXT,
    pdf_path TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Applications submitted
CREATE TABLE IF NOT EXISTS applications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    candidate_id UUID REFERENCES candidates(id),
    job_id UUID REFERENCES jobs(id),
    resume_id UUID REFERENCES resumes(id),
    portal TEXT NOT NULL,
    status TEXT DEFAULT 'PENDING',   -- PENDING | APPLIED | FAILED | SKIPPED | INTERVIEW | REJECTED | OFFER
    applied_at TIMESTAMPTZ,
    account_created BOOLEAN DEFAULT FALSE,
    application_ref TEXT,            -- Confirmation number from portal
    notes TEXT,
    error_message TEXT,
    last_updated TIMESTAMPTZ DEFAULT NOW()
);

-- Portal accounts (passwords AES encrypted)
CREATE TABLE IF NOT EXISTS portal_accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    candidate_id UUID REFERENCES candidates(id),
    portal TEXT NOT NULL,
    username TEXT NOT NULL,
    password_enc TEXT NOT NULL,      -- Encrypted with app SECRET_KEY
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    UNIQUE(candidate_id, portal)
);

-- Search sessions log
CREATE TABLE IF NOT EXISTS search_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    candidate_id UUID REFERENCES candidates(id),
    search_query TEXT,
    portals JSONB DEFAULT '[]',
    jobs_found INTEGER DEFAULT 0,
    jobs_matched INTEGER DEFAULT 0,
    jobs_applied INTEGER DEFAULT 0,
    jobs_skipped INTEGER DEFAULT 0,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status TEXT DEFAULT 'RUNNING'    -- RUNNING | COMPLETED | FAILED
);

-- Useful indexes
CREATE INDEX IF NOT EXISTS idx_jobs_portal ON jobs(portal);
CREATE INDEX IF NOT EXISTS idx_applications_candidate ON applications(candidate_id);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
CREATE INDEX IF NOT EXISTS idx_portal_accounts_lookup ON portal_accounts(candidate_id, portal);
