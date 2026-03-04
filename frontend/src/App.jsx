import { useState, useEffect, useRef } from "react"

const API = import.meta.env.VITE_API_URL || "http://localhost:8000"

const STATUS_COLORS = {
  APPLIED:   { bg: "#d4edda", text: "#155724", dot: "#28a745" },
  FAILED:    { bg: "#f8d7da", text: "#721c24", dot: "#dc3545" },
  SKIPPED:   { bg: "#fff3cd", text: "#856404", dot: "#ffc107" },
  PENDING:   { bg: "#e2e3e5", text: "#383d41", dot: "#6c757d" },
  INTERVIEW: { bg: "#cce5ff", text: "#004085", dot: "#007bff" },
  OFFER:     { bg: "#d4edda", text: "#155724", dot: "#20c997" },
}

export default function App() {
  const [tab, setTab] = useState("profile")
  const [candidateId, setCandidateId] = useState(localStorage.getItem("jobbot_candidate_id") || "")
  const [candidate, setCandidate] = useState(null)
  const [applications, setApplications] = useState([])
  const [saving, setSaving] = useState(false)
  const [uploadingPdf, setUploadingPdf] = useState(false)
  const [pdfUploaded, setPdfUploaded] = useState(false)
  const fileInputRef = useRef(null)
  const pollRef = useRef(null)

  // Search flow
  const [searchForm, setSearchForm] = useState({ job_query: "", location: "India" })
  const [searchResults, setSearchResults] = useState(null)
  const [searching, setSearching] = useState(false)
  const [applying, setApplying] = useState(false)
  const [applyStarted, setApplyStarted] = useState(false)

  const [profileForm, setProfileForm] = useState({
    name: "", email: "", phone: "", location: "",
    linkedin_url: "", github_url: "",
    skills: "", experience_years: 0, summary: "",
    experience: [], education: [], certifications: []
  })

  useEffect(() => {
    if (candidateId) {
      fetchCandidate()
      fetchApplications()
    }
    // Cleanup polling on unmount
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [candidateId])

  const fetchCandidate = async () => {
    try {
      const r = await fetch(`${API}/candidate/${candidateId}`)
      if (r.ok) {
        const data = await r.json()
        setCandidate(data)
        setPdfUploaded(!!(data.base_resume_text || "").startsWith("PDF:"))
        setProfileForm({
          ...data,
          skills: Array.isArray(data.skills) ? data.skills.join(", ") : data.skills || ""
        })
      }
    } catch (e) { console.error(e) }
  }

  const fetchApplications = async () => {
    try {
      const r = await fetch(`${API}/applications/${candidateId}`)
      if (r.ok) {
        const data = await r.json()
        setApplications(data.applications || [])
      }
    } catch (e) { console.error(e) }
  }

  // Start polling — stops automatically after maxPolls
  const startPolling = (maxPolls = 20, intervalMs = 10000) => {
    if (pollRef.current) clearInterval(pollRef.current)
    let count = 0
    pollRef.current = setInterval(async () => {
      count++
      await fetchApplications()
      if (count >= maxPolls) {
        clearInterval(pollRef.current)
        pollRef.current = null
        setApplying(false)
      }
    }, intervalMs)
  }

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  // ── Upload PDF CV ──────────────────────────────────────────────────────────
  const handlePdfUpload = async (file) => {
    if (!file || file.type !== "application/pdf") return alert("Please upload a PDF file")
    if (!candidateId) return alert("Save your profile first, then upload your CV")
    setUploadingPdf(true)
    try {
      const formData = new FormData()
      formData.append("file", file)
      const r = await fetch(`${API}/candidate/${candidateId}/upload-cv`, { method: "POST", body: formData })
      if (r.ok) {
        const data = await r.json()
        setPdfUploaded(true)
        if (data.extracted_skills?.length) {
          setProfileForm(p => ({ ...p, skills: data.extracted_skills.join(", "), summary: data.extracted_summary || p.summary }))
          alert(`✅ CV uploaded! Extracted ${data.extracted_skills.length} skills automatically.`)
        } else {
          alert("✅ CV uploaded successfully!")
        }
        fetchCandidate()
      } else {
        const err = await r.json()
        alert(`Upload failed: ${err.detail || "Unknown error"}`)
      }
    } catch (e) { alert("Upload failed") }
    setUploadingPdf(false)
  }

  // ── Save Profile ───────────────────────────────────────────────────────────
  const saveProfile = async () => {
    if (!profileForm.name || !profileForm.email) return alert("Name and Email are required")
    setSaving(true)
    try {
      const payload = { ...profileForm, skills: profileForm.skills.split(",").map(s => s.trim()).filter(Boolean) }
      const r = await fetch(`${API}/candidate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })
      if (r.ok) {
        const data = await r.json()
        const newId = data.candidate?.id
        if (newId) {
          setCandidateId(newId)
          localStorage.setItem("jobbot_candidate_id", newId)
          setCandidate(data.candidate)
          alert("✅ Profile saved!")
        }
      }
    } catch (e) { alert("Error saving profile") }
    setSaving(false)
  }

  // ── Step 1: Search ─────────────────────────────────────────────────────────
  const searchJobs = async () => {
    if (!candidateId) return alert("Save your profile first!")
    if (!searchForm.job_query) return alert("Enter a job title or skill")
    setSearching(true)
    setSearchResults(null)
    setApplyStarted(false)
    stopPolling()
    try {
      const r = await fetch(`${API}/search/jobs`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidate_id: candidateId, ...searchForm })
      })
      if (r.ok) setSearchResults(await r.json())
      else alert("Search failed — try again")
    } catch (e) { alert("Search failed") }
    setSearching(false)
  }

  // ── Step 2: Auto Apply ─────────────────────────────────────────────────────
  const startAutoApply = async () => {
    if (!searchResults?.session_id) return
    const matchedIds = searchResults.jobs.filter(j => j.match_score >= 80 && j.job_id).map(j => j.job_id)
    if (!matchedIds.length) return alert("No jobs with valid IDs to apply to")
    setApplying(true)
    setApplyStarted(true)
    try {
      const r = await fetch(`${API}/search/apply`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidate_id: candidateId, session_id: searchResults.session_id, job_ids: matchedIds })
      })
      if (r.ok) {
        // Poll for up to ~3 minutes (20 polls × 10s), then stop
        startPolling(20, 10000)
        setTab("tracker")
      } else {
        setApplying(false)
        setApplyStarted(false)
        alert("Auto-apply failed to start")
      }
    } catch (e) {
      setApplying(false)
      setApplyStarted(false)
      alert("Auto-apply failed")
    }
  }

  const summary = {
    total: applications.length,
    applied: applications.filter(a => a.status === "APPLIED").length,
    skipped: applications.filter(a => a.status === "SKIPPED").length,
    failed: applications.filter(a => a.status === "FAILED").length,
    interview: applications.filter(a => a.status === "INTERVIEW").length,
  }

  const matchedJobs = searchResults?.jobs?.filter(j => j.match_score >= 80) || []
  const reviewJobs  = searchResults?.jobs?.filter(j => j.match_score >= 60 && j.match_score < 80) || []
  const skippedJobs = searchResults?.jobs?.filter(j => j.match_score < 60) || []

  return (
    <div style={{ fontFamily: "'Segoe UI', sans-serif", minHeight: "100vh", background: "#f0f4f8" }}>

      {/* Header */}
      <div style={{ background: "linear-gradient(135deg, #1a5276, #2980b9)", color: "white", padding: "20px 32px" }}>
        <div style={{ maxWidth: 1100, margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: 26, fontWeight: 700, letterSpacing: 1 }}>🤖 JobBot</div>
            <div style={{ fontSize: 13, opacity: 0.85 }}>AI-Powered Automatic Job Application Agent</div>
          </div>
          {candidate && (
            <div style={{ textAlign: "right", fontSize: 13 }}>
              <div style={{ fontWeight: 600 }}>{candidate.name}</div>
              <div style={{ opacity: 0.8 }}>{candidate.email}</div>
              {pdfUploaded && <div style={{ opacity: 0.7, fontSize: 11 }}>📄 CV uploaded</div>}
            </div>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div style={{ background: "white", borderBottom: "1px solid #dee2e6" }}>
        <div style={{ maxWidth: 1100, margin: "0 auto", display: "flex" }}>
          {[["profile","👤 Profile"],["search","🔍 Search & Apply"],["tracker","📊 Applications"]].map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)} style={{
              padding: "14px 24px", border: "none", cursor: "pointer", fontWeight: tab === id ? 600 : 400,
              background: "none", borderBottom: tab === id ? "3px solid #2980b9" : "3px solid transparent",
              color: tab === id ? "#2980b9" : "#555", fontSize: 14,
            }}>{label}{id === "tracker" && applying ? " 🔄" : ""}</button>
          ))}
        </div>
      </div>

      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "28px 16px" }}>

        {/* ── PROFILE TAB ── */}
        {tab === "profile" && (
          <div>
            {/* CV Upload */}
            <div style={{ background: "white", borderRadius: 12, padding: 24, boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
                         marginBottom: 20, border: pdfUploaded ? "2px solid #28a745" : "2px dashed #aed6f1" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 15, color: "#1a5276", marginBottom: 4 }}>📄 Upload Your CV (PDF)</div>
                  <div style={{ fontSize: 13, color: "#666" }}>
                    {pdfUploaded
                      ? "✅ CV on file — will be referenced when building tailored resumes and matching skills"
                      : "Upload your existing CV to auto-extract skills and use as reference for job matching"}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 10, alignItems: "center", flexShrink: 0, marginLeft: 20 }}>
                  {pdfUploaded && <span style={{ background: "#d4edda", color: "#155724", borderRadius: 20, padding: "4px 14px", fontSize: 12, fontWeight: 500 }}>✅ CV on file</span>}
                  <input type="file" accept=".pdf" ref={fileInputRef} style={{ display: "none" }}
                    onChange={e => e.target.files[0] && handlePdfUpload(e.target.files[0])} />
                  <button onClick={() => fileInputRef.current?.click()} disabled={uploadingPdf}
                    style={{ background: pdfUploaded ? "#f8f9fa" : "linear-gradient(135deg, #1a5276, #2980b9)",
                             color: pdfUploaded ? "#333" : "white", border: pdfUploaded ? "1px solid #ddd" : "none",
                             borderRadius: 8, padding: "9px 20px", cursor: uploadingPdf ? "not-allowed" : "pointer", fontSize: 13, fontWeight: 500, whiteSpace: "nowrap" }}>
                    {uploadingPdf ? "Uploading..." : pdfUploaded ? "📤 Replace CV" : "📤 Upload CV"}
                  </button>
                </div>
              </div>
            </div>

            {/* Profile Form */}
            <div style={{ background: "white", borderRadius: 12, padding: 28, boxShadow: "0 2px 8px rgba(0,0,0,0.08)" }}>
              <h2 style={{ marginBottom: 6, color: "#1a5276" }}>Candidate Profile</h2>
              <p style={{ color: "#888", fontSize: 13, marginBottom: 22 }}>Fill manually or upload CV above to auto-populate skills.</p>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
                {[["name","Full Name *","text"],["email","Email *","email"],["phone","Phone","text"],
                  ["location","Location","text"],["linkedin_url","LinkedIn URL","url"],["github_url","GitHub URL","url"]
                ].map(([field, label, type]) => (
                  <div key={field}>
                    <label style={{ display: "block", marginBottom: 5, fontWeight: 500, fontSize: 13, color: "#444" }}>{label}</label>
                    <input type={type} value={profileForm[field] || ""}
                      onChange={e => setProfileForm(p => ({ ...p, [field]: e.target.value }))}
                      style={{ width: "100%", padding: "9px 12px", border: "1px solid #ddd", borderRadius: 6, fontSize: 14, boxSizing: "border-box" }} />
                  </div>
                ))}
              </div>

              <div style={{ marginTop: 18 }}>
                <label style={{ display: "block", marginBottom: 5, fontWeight: 500, fontSize: 13, color: "#444" }}>Skills (comma separated) *</label>
                <input value={profileForm.skills} onChange={e => setProfileForm(p => ({ ...p, skills: e.target.value }))}
                  placeholder="Python, FastAPI, React, PostgreSQL, Docker..."
                  style={{ width: "100%", padding: "9px 12px", border: "1px solid #ddd", borderRadius: 6, fontSize: 14 }} />
                <div style={{ fontSize: 11, color: "#999", marginTop: 3 }}>💡 Auto-populated when you upload a CV</div>
              </div>

              <div style={{ marginTop: 18, display: "grid", gridTemplateColumns: "1fr 4fr", gap: 18 }}>
                <div>
                  <label style={{ display: "block", marginBottom: 5, fontWeight: 500, fontSize: 13, color: "#444" }}>Years of Exp.</label>
                  <input type="number" value={profileForm.experience_years} min={0} max={40}
                    onChange={e => setProfileForm(p => ({ ...p, experience_years: parseInt(e.target.value) || 0 }))}
                    style={{ width: "100%", padding: "9px 12px", border: "1px solid #ddd", borderRadius: 6, fontSize: 14 }} />
                </div>
                <div>
                  <label style={{ display: "block", marginBottom: 5, fontWeight: 500, fontSize: 13, color: "#444" }}>Professional Summary</label>
                  <textarea value={profileForm.summary} rows={2}
                    onChange={e => setProfileForm(p => ({ ...p, summary: e.target.value }))}
                    placeholder="Brief summary of your experience..."
                    style={{ width: "100%", padding: "9px 12px", border: "1px solid #ddd", borderRadius: 6, fontSize: 14, resize: "vertical" }} />
                </div>
              </div>

              {/* Experience */}
              <div style={{ marginTop: 24, borderTop: "1px solid #eee", paddingTop: 20 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                  <h3 style={{ color: "#1a5276", fontSize: 15 }}>Work Experience</h3>
                  <button onClick={() => setProfileForm(p => ({ ...p, experience: [...p.experience, { role: "", company: "", duration: "", description: "", achievements: [] }] }))}
                    style={{ background: "#2980b9", color: "white", border: "none", borderRadius: 6, padding: "6px 14px", cursor: "pointer", fontSize: 13 }}>+ Add</button>
                </div>
                {profileForm.experience.map((exp, i) => (
                  <div key={i} style={{ background: "#f8f9fa", borderRadius: 8, padding: 16, marginBottom: 12 }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 10 }}>
                      {[["role","Job Title"],["company","Company"],["duration","Duration"]].map(([field, ph]) => (
                        <input key={field} value={exp[field] || ""} placeholder={ph}
                          onChange={e => { const u = [...profileForm.experience]; u[i] = { ...u[i], [field]: e.target.value }; setProfileForm(p => ({ ...p, experience: u })) }}
                          style={{ padding: "8px 10px", border: "1px solid #ddd", borderRadius: 5, fontSize: 13 }} />
                      ))}
                    </div>
                    <textarea value={exp.description || ""} placeholder="Role description..." rows={2}
                      onChange={e => { const u = [...profileForm.experience]; u[i] = { ...u[i], description: e.target.value }; setProfileForm(p => ({ ...p, experience: u })) }}
                      style={{ width: "100%", padding: "8px 10px", border: "1px solid #ddd", borderRadius: 5, fontSize: 13, resize: "vertical", marginBottom: 6 }} />
                    <input value={(exp.achievements || []).join("; ")} placeholder="Key achievements (semicolon separated)"
                      onChange={e => { const u = [...profileForm.experience]; u[i] = { ...u[i], achievements: e.target.value.split(";").map(s => s.trim()).filter(Boolean) }; setProfileForm(p => ({ ...p, experience: u })) }}
                      style={{ width: "100%", padding: "8px 10px", border: "1px solid #ddd", borderRadius: 5, fontSize: 13 }} />
                  </div>
                ))}
              </div>

              <button onClick={saveProfile} disabled={saving}
                style={{ marginTop: 24, background: saving ? "#aaa" : "linear-gradient(135deg, #1a5276, #2980b9)",
                         color: "white", border: "none", borderRadius: 8, padding: "12px 32px",
                         fontSize: 15, fontWeight: 600, cursor: saving ? "not-allowed" : "pointer" }}>
                {saving ? "Saving..." : "💾 Save Profile"}
              </button>
            </div>
          </div>
        )}

        {/* ── SEARCH TAB ── */}
        {tab === "search" && (
          <div>
            <div style={{ background: "white", borderRadius: 12, padding: 28, boxShadow: "0 2px 8px rgba(0,0,0,0.08)", marginBottom: 20 }}>
              <h2 style={{ marginBottom: 6, color: "#1a5276" }}>🔍 Search Jobs</h2>
              <p style={{ color: "#666", marginBottom: 20, fontSize: 13 }}>
                Step 1 — Search and review matched jobs. &nbsp; Step 2 — Click Auto Apply for ≥80% matches.
              </p>
              <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr auto", gap: 14, alignItems: "flex-end" }}>
                <div>
                  <label style={{ display: "block", marginBottom: 5, fontWeight: 500, fontSize: 13, color: "#444" }}>Job Title / Skills</label>
                  <input value={searchForm.job_query} onChange={e => setSearchForm(p => ({ ...p, job_query: e.target.value }))}
                    onKeyDown={e => e.key === "Enter" && searchJobs()}
                    placeholder="e.g. Product Manager, Python Developer, Data Scientist..."
                    style={{ width: "100%", padding: "10px 14px", border: "1.5px solid #2980b9", borderRadius: 8, fontSize: 15 }} />
                </div>
                <div>
                  <label style={{ display: "block", marginBottom: 5, fontWeight: 500, fontSize: 13, color: "#444" }}>Location</label>
                  <input value={searchForm.location} onChange={e => setSearchForm(p => ({ ...p, location: e.target.value }))}
                    placeholder="India / Bangalore / Remote"
                    style={{ width: "100%", padding: "10px 14px", border: "1.5px solid #ddd", borderRadius: 8, fontSize: 14 }} />
                </div>
                <button onClick={searchJobs} disabled={searching || !candidateId}
                  style={{ background: (searching || !candidateId) ? "#aaa" : "linear-gradient(135deg, #1a5276, #2980b9)",
                           color: "white", border: "none", borderRadius: 8, padding: "11px 28px",
                           fontSize: 14, fontWeight: 600, cursor: (searching || !candidateId) ? "not-allowed" : "pointer", whiteSpace: "nowrap" }}>
                  {searching ? "⏳ Searching..." : "🔍 Search"}
                </button>
              </div>
              {!candidateId && <p style={{ color: "#dc3545", fontSize: 13, marginTop: 8 }}>⚠️ Save your profile first</p>}
              <div style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
                <span style={{ fontSize: 12, color: "#888" }}>Searching:</span>
                {["Naukri","LinkedIn","Indeed","Instahyre","Adzuna"].map(p => (
                  <span key={p} style={{ background: "#eaf4fb", border: "1px solid #aed6f1", borderRadius: 20, padding: "2px 10px", fontSize: 11, color: "#2980b9" }}>✓ {p}</span>
                ))}
              </div>
            </div>

            {searchResults && (
              <div>
                {/* Summary */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12, marginBottom: 20 }}>
                  {[
                    ["Jobs Found", searchResults.total_found, "#2980b9"],
                    ["✅ Strong Match ≥80%", matchedJobs.length, "#28a745"],
                    ["🔶 Review 60-79%", reviewJobs.length, "#ffc107"],
                    ["⏭ Low Match <60%", skippedJobs.length, "#aaa"],
                  ].map(([label, count, color]) => (
                    <div key={label} style={{ background: "white", borderRadius: 10, padding: "14px 18px",
                                             boxShadow: "0 2px 6px rgba(0,0,0,0.07)", borderTop: `3px solid ${color}` }}>
                      <div style={{ fontSize: 26, fontWeight: 700, color }}>{count}</div>
                      <div style={{ fontSize: 12, color: "#666", marginTop: 2 }}>{label}</div>
                    </div>
                  ))}
                </div>

                {/* Auto Apply CTA */}
                {matchedJobs.length > 0 && !applyStarted && (
                  <div style={{ background: "linear-gradient(135deg, #1a5276, #2980b9)", borderRadius: 12,
                               padding: "20px 28px", marginBottom: 20, display: "flex",
                               justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ color: "white" }}>
                      <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 3 }}>🚀 Ready to auto-apply to {matchedJobs.length} matched jobs?</div>
                      <div style={{ fontSize: 13, opacity: 0.85 }}>JobBot will build tailored resumes and submit applications — you'll be redirected to the tracker</div>
                    </div>
                    <button onClick={startAutoApply}
                      style={{ background: "white", color: "#1a5276", border: "none", borderRadius: 8,
                               padding: "12px 28px", fontSize: 14, fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap", minWidth: 160 }}>
                      ⚡ Auto Apply Now
                    </button>
                  </div>
                )}

                {applyStarted && (
                  <div style={{ background: "#d4edda", borderRadius: 10, padding: "14px 20px", marginBottom: 20, border: "1px solid #c3e6cb" }}>
                    <div style={{ fontWeight: 600, color: "#155724" }}>⏳ Auto-applying in background...</div>
                    <div style={{ fontSize: 13, color: "#155724", marginTop: 3 }}>Check the Applications tab for live updates. Applying to {matchedJobs.length} jobs.</div>
                  </div>
                )}

                {/* Job Tables */}
                {matchedJobs.length > 0 && (
                  <div style={{ background: "white", borderRadius: 12, boxShadow: "0 2px 8px rgba(0,0,0,0.08)", marginBottom: 16, overflow: "hidden" }}>
                    <div style={{ background: "#d4edda", padding: "12px 20px", borderBottom: "1px solid #c3e6cb" }}>
                      <span style={{ fontWeight: 600, color: "#155724" }}>✅ Strong Match — Will Auto-Apply ({matchedJobs.length})</span>
                    </div>
                    <JobTable jobs={matchedJobs} />
                  </div>
                )}
                {reviewJobs.length > 0 && (
                  <div style={{ background: "white", borderRadius: 12, boxShadow: "0 2px 8px rgba(0,0,0,0.08)", marginBottom: 16, overflow: "hidden" }}>
                    <div style={{ background: "#fff3cd", padding: "12px 20px", borderBottom: "1px solid #ffe8a1" }}>
                      <span style={{ fontWeight: 600, color: "#856404" }}>🔶 Review These — Close but below 80% ({reviewJobs.length})</span>
                    </div>
                    <JobTable jobs={reviewJobs} />
                  </div>
                )}
                {skippedJobs.length > 0 && (
                  <details style={{ background: "white", borderRadius: 12, boxShadow: "0 2px 8px rgba(0,0,0,0.08)", overflow: "hidden" }}>
                    <summary style={{ background: "#f8f9fa", padding: "12px 20px", cursor: "pointer",
                                     borderBottom: "1px solid #dee2e6", fontWeight: 600, color: "#666", fontSize: 14, listStyle: "none" }}>
                      ⏭ Low Match — Skipped ({skippedJobs.length}) — click to expand
                    </summary>
                    <JobTable jobs={skippedJobs} />
                  </details>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── TRACKER TAB ── */}
        {tab === "tracker" && (
          <div>
            {applying && (
              <div style={{ background: "#cce5ff", borderRadius: 10, padding: "12px 20px", marginBottom: 18, border: "1px solid #b8daff" }}>
                <span style={{ color: "#004085", fontWeight: 600 }}>🔄 Auto-apply in progress — page refreshing automatically every 10 seconds</span>
                <button onClick={() => { stopPolling(); setApplying(false) }}
                  style={{ marginLeft: 16, background: "none", border: "1px solid #004085", borderRadius: 4, padding: "2px 10px", cursor: "pointer", color: "#004085", fontSize: 12 }}>
                  Stop
                </button>
              </div>
            )}

            <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 14, marginBottom: 22 }}>
              {[["Total",summary.total,"#6c757d"],["Applied",summary.applied,"#28a745"],
                ["Interview",summary.interview,"#007bff"],["Skipped",summary.skipped,"#ffc107"],["Failed",summary.failed,"#dc3545"]
              ].map(([label, count, color]) => (
                <div key={label} style={{ background: "white", borderRadius: 10, padding: "16px 20px",
                                         boxShadow: "0 2px 8px rgba(0,0,0,0.08)", borderTop: `3px solid ${color}` }}>
                  <div style={{ fontSize: 28, fontWeight: 700, color }}>{count}</div>
                  <div style={{ fontSize: 13, color: "#666", marginTop: 2 }}>{label}</div>
                </div>
              ))}
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 14 }}>
              <button onClick={fetchApplications}
                style={{ background: "#f8f9fa", border: "1px solid #ddd", borderRadius: 6, padding: "7px 16px", cursor: "pointer", fontSize: 13 }}>
                🔄 Refresh
              </button>
            </div>

            <div style={{ background: "white", borderRadius: 12, boxShadow: "0 2px 8px rgba(0,0,0,0.08)", overflow: "hidden" }}>
              {applications.length === 0 ? (
                <div style={{ padding: 48, textAlign: "center", color: "#aaa" }}>
                  <div style={{ fontSize: 48, marginBottom: 12 }}>📭</div>
                  <div>No applications yet. Search and auto-apply!</div>
                </div>
              ) : (
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ background: "#f8f9fa", borderBottom: "2px solid #dee2e6" }}>
                      {["Job Title","Company","Portal","Match","Status","Applied","Resume"].map(h => (
                        <th key={h} style={{ padding: "12px 16px", textAlign: "left", fontSize: 12, fontWeight: 600, color: "#555", textTransform: "uppercase", letterSpacing: 0.5 }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {applications.map((app, i) => {
                      const job = app.jobs || {}
                      const resume = app.resumes || {}
                      const colors = STATUS_COLORS[app.status] || STATUS_COLORS.PENDING
                      return (
                        <tr key={app.id} style={{ borderBottom: "1px solid #eee", background: i % 2 === 0 ? "white" : "#fafafa" }}>
                          <td style={{ padding: "12px 16px", fontWeight: 500, fontSize: 14 }}>
                            <a href={job.apply_url} target="_blank" rel="noopener noreferrer" style={{ color: "#2980b9", textDecoration: "none" }}>{job.title || "—"}</a>
                          </td>
                          <td style={{ padding: "12px 16px", fontSize: 13, color: "#444" }}>{job.company || "—"}</td>
                          <td style={{ padding: "12px 16px" }}>
                            <span style={{ background: "#eaf4fb", borderRadius: 20, padding: "2px 10px", fontSize: 12, color: "#2980b9" }}>{app.portal}</span>
                          </td>
                          <td style={{ padding: "12px 16px", fontSize: 13 }}>
                            {resume.match_score
                              ? <span style={{ fontWeight: 600, color: resume.match_score >= 80 ? "#28a745" : "#ffc107" }}>{resume.match_score}%</span>
                              : "—"}
                          </td>
                          <td style={{ padding: "12px 16px" }}>
                            <span style={{ background: colors.bg, color: colors.text, borderRadius: 20, padding: "3px 12px", fontSize: 12, fontWeight: 500 }}>
                              <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%", background: colors.dot, marginRight: 5 }} />
                              {app.status}
                            </span>
                          </td>
                          <td style={{ padding: "12px 16px", fontSize: 12, color: "#777" }}>
                            {app.applied_at ? new Date(app.applied_at).toLocaleDateString("en-IN") : "—"}
                          </td>
                          <td style={{ padding: "12px 16px" }}>
                            {resume.pdf_path ? (
                                <div style={{ display: "flex", gap: 6 }}>
                                  <a
                                    href={`${API}/resume/${app.resume_id || app.resumes?.id}/view`}
                                    target="_blank" rel="noopener noreferrer"
                                    style={{ fontSize: 11, color: "#2980b9", textDecoration: "none",
                                             background: "#eaf4fb", borderRadius: 4, padding: "2px 7px" }}>
                                    👁 View
                                  </a>
                                  <a
                                    href={`${API}/resume/${app.resume_id || app.resumes?.id}/download`}
                                    target="_blank" rel="noopener noreferrer"
                                    style={{ fontSize: 11, color: "#155724", textDecoration: "none",
                                             background: "#d4edda", borderRadius: 4, padding: "2px 7px" }}>
                                    ⬇ PDF
                                  </a>
                                </div>
                              ) : "—"}
                          </td>
                          <td style={{ padding: "12px 16px", maxWidth: 220 }}>
                            {app.error_message ? (
                              <span title={app.error_message}
                                style={{ fontSize: 11, color: "#721c24", background: "#f8d7da",
                                         borderRadius: 4, padding: "2px 7px", display: "block",
                                         overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                                         maxWidth: 200, cursor: "help" }}>
                                ⚠ {app.error_message.substring(0, 60)}{app.error_message.length > 60 ? "…" : ""}
                              </span>
                            ) : app.notes ? (
                              <span style={{ fontSize: 11, color: "#555" }}>{app.notes.substring(0, 60)}</span>
                            ) : "—"}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function JobTable({ jobs }) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead>
        <tr style={{ borderBottom: "1px solid #eee" }}>
          {["Job Title","Company","Location","Portal","Match","Link"].map(h => (
            <th key={h} style={{ padding: "10px 16px", textAlign: "left", fontSize: 11, fontWeight: 600, color: "#888", textTransform: "uppercase" }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {jobs.map((job, i) => (
          <tr key={i} style={{ borderBottom: "1px solid #f0f0f0", background: i % 2 === 0 ? "white" : "#fafafa" }}>
            <td style={{ padding: "11px 16px", fontWeight: 500, fontSize: 13 }}>{job.title}</td>
            <td style={{ padding: "11px 16px", fontSize: 13, color: "#555" }}>{job.company}</td>
            <td style={{ padding: "11px 16px", fontSize: 12, color: "#777" }}>{job.location || "—"}</td>
            <td style={{ padding: "11px 16px" }}>
              <span style={{ background: "#eaf4fb", borderRadius: 20, padding: "2px 9px", fontSize: 11, color: "#2980b9" }}>{job.portal}</span>
            </td>
            <td style={{ padding: "11px 16px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{ width: 60, height: 7, background: "#eee", borderRadius: 4, overflow: "hidden" }}>
                  <div style={{ width: `${Math.min(job.match_score, 100)}%`, height: "100%",
                               background: job.match_score >= 80 ? "#28a745" : job.match_score >= 60 ? "#ffc107" : "#dc3545",
                               borderRadius: 4 }} />
                </div>
                <span style={{ fontWeight: 600, fontSize: 13, color: job.match_score >= 80 ? "#28a745" : job.match_score >= 60 ? "#856404" : "#aaa" }}>
                  {job.match_score}%
                </span>
              </div>
            </td>
            <td style={{ padding: "11px 16px" }}>
              <a href={job.apply_url} target="_blank" rel="noopener noreferrer" style={{ color: "#2980b9", fontSize: 12, textDecoration: "none" }}>View →</a>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
