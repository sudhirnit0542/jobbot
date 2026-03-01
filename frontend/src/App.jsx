import { useState, useEffect } from "react"

const API = import.meta.env.VITE_API_URL || "http://localhost:8000"

const STATUS_COLORS = {
  APPLIED: { bg: "#d4edda", text: "#155724", dot: "#28a745" },
  FAILED: { bg: "#f8d7da", text: "#721c24", dot: "#dc3545" },
  SKIPPED: { bg: "#fff3cd", text: "#856404", dot: "#ffc107" },
  PENDING: { bg: "#e2e3e5", text: "#383d41", dot: "#6c757d" },
  INTERVIEW: { bg: "#cce5ff", text: "#004085", dot: "#007bff" },
  OFFER: { bg: "#d4edda", text: "#155724", dot: "#20c997" },
}

export default function App() {
  const [tab, setTab] = useState("search")
  const [candidateId, setCandidateId] = useState(localStorage.getItem("jobbot_candidate_id") || "")
  const [candidate, setCandidate] = useState(null)
  const [applications, setApplications] = useState([])
  const [searching, setSearching] = useState(false)
  const [searchResult, setSearchResult] = useState(null)
  const [profileForm, setProfileForm] = useState({
    name: "", email: "", phone: "", location: "",
    linkedin_url: "", github_url: "",
    skills: "", experience_years: 0, summary: "",
    experience: [], education: [], certifications: []
  })
  const [searchForm, setSearchForm] = useState({ job_query: "", location: "India" })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (candidateId) {
      fetchCandidate()
      fetchApplications()
    }
  }, [candidateId])

  const fetchCandidate = async () => {
    try {
      const r = await fetch(`${API}/candidate/${candidateId}`)
      if (r.ok) {
        const data = await r.json()
        setCandidate(data)
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

  const saveProfile = async () => {
    setSaving(true)
    try {
      const payload = {
        ...profileForm,
        skills: profileForm.skills.split(",").map(s => s.trim()).filter(Boolean),
      }
      const r = await fetch(`${API}/candidate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      })
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

  const startSearch = async () => {
    if (!candidateId) return alert("Save your profile first!")
    if (!searchForm.job_query) return alert("Enter a job title or skill to search")
    setSearching(true)
    setSearchResult(null)
    try {
      const r = await fetch(`${API}/search/start`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidate_id: candidateId, ...searchForm })
      })
      if (r.ok) {
        const data = await r.json()
        setSearchResult(data)
        // Poll for applications every 10 seconds
        const interval = setInterval(async () => {
          await fetchApplications()
        }, 10000)
        setTimeout(() => clearInterval(interval), 300000) // Stop after 5 min
      }
    } catch (e) { setSearchResult({ error: "Search failed" }) }
    setSearching(false)
  }

  const summary = {
    total: applications.length,
    applied: applications.filter(a => a.status === "APPLIED").length,
    skipped: applications.filter(a => a.status === "SKIPPED").length,
    failed: applications.filter(a => a.status === "FAILED").length,
    interview: applications.filter(a => a.status === "INTERVIEW").length,
  }

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
            </div>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div style={{ background: "white", borderBottom: "1px solid #dee2e6" }}>
        <div style={{ maxWidth: 1100, margin: "0 auto", display: "flex" }}>
          {[["profile", "👤 Profile"], ["search", "🔍 Search & Apply"], ["tracker", "📊 Applications"]].map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)} style={{
              padding: "14px 24px", border: "none", cursor: "pointer", fontWeight: tab === id ? 600 : 400,
              background: "none", borderBottom: tab === id ? "3px solid #2980b9" : "3px solid transparent",
              color: tab === id ? "#2980b9" : "#555", fontSize: 14,
            }}>{label}</button>
          ))}
        </div>
      </div>

      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "28px 16px" }}>

        {/* ── PROFILE TAB ── */}
        {tab === "profile" && (
          <div style={{ background: "white", borderRadius: 12, padding: 28, boxShadow: "0 2px 8px rgba(0,0,0,0.08)" }}>
            <h2 style={{ marginBottom: 24, color: "#1a5276" }}>Candidate Profile</h2>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
              {[
                ["name", "Full Name *", "text"],
                ["email", "Email Address *", "email"],
                ["phone", "Phone Number", "text"],
                ["location", "Location (City)", "text"],
                ["linkedin_url", "LinkedIn URL", "url"],
                ["github_url", "GitHub URL", "url"],
              ].map(([field, label, type]) => (
                <div key={field}>
                  <label style={{ display: "block", marginBottom: 5, fontWeight: 500, fontSize: 13, color: "#444" }}>{label}</label>
                  <input type={type} value={profileForm[field] || ""} onChange={e => setProfileForm(p => ({ ...p, [field]: e.target.value }))}
                    style={{ width: "100%", padding: "9px 12px", border: "1px solid #ddd", borderRadius: 6, fontSize: 14, boxSizing: "border-box" }} />
                </div>
              ))}
            </div>

            <div style={{ marginTop: 18 }}>
              <label style={{ display: "block", marginBottom: 5, fontWeight: 500, fontSize: 13, color: "#444" }}>
                Skills (comma separated) *
              </label>
              <input value={profileForm.skills} onChange={e => setProfileForm(p => ({ ...p, skills: e.target.value }))}
                placeholder="Python, FastAPI, React, PostgreSQL, Docker, AWS..."
                style={{ width: "100%", padding: "9px 12px", border: "1px solid #ddd", borderRadius: 6, fontSize: 14 }} />
            </div>

            <div style={{ marginTop: 18, display: "grid", gridTemplateColumns: "1fr 4fr", gap: 18 }}>
              <div>
                <label style={{ display: "block", marginBottom: 5, fontWeight: 500, fontSize: 13, color: "#444" }}>Years of Experience</label>
                <input type="number" value={profileForm.experience_years} min={0} max={40}
                  onChange={e => setProfileForm(p => ({ ...p, experience_years: parseInt(e.target.value) || 0 }))}
                  style={{ width: "100%", padding: "9px 12px", border: "1px solid #ddd", borderRadius: 6, fontSize: 14 }} />
              </div>
              <div>
                <label style={{ display: "block", marginBottom: 5, fontWeight: 500, fontSize: 13, color: "#444" }}>Professional Summary</label>
                <textarea value={profileForm.summary} rows={2}
                  onChange={e => setProfileForm(p => ({ ...p, summary: e.target.value }))}
                  placeholder="Brief summary of your experience and expertise..."
                  style={{ width: "100%", padding: "9px 12px", border: "1px solid #ddd", borderRadius: 6, fontSize: 14, resize: "vertical" }} />
              </div>
            </div>

            {/* Experience Section */}
            <div style={{ marginTop: 24, borderTop: "1px solid #eee", paddingTop: 20 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <h3 style={{ color: "#1a5276", fontSize: 15 }}>Work Experience</h3>
                <button onClick={() => setProfileForm(p => ({ ...p, experience: [...p.experience, { role: "", company: "", duration: "", description: "", achievements: [] }] }))}
                  style={{ background: "#2980b9", color: "white", border: "none", borderRadius: 6, padding: "6px 14px", cursor: "pointer", fontSize: 13 }}>
                  + Add Experience
                </button>
              </div>
              {profileForm.experience.map((exp, i) => (
                <div key={i} style={{ background: "#f8f9fa", borderRadius: 8, padding: 16, marginBottom: 12 }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 10 }}>
                    {[["role", "Job Title"], ["company", "Company"], ["duration", "Duration (e.g. 2021-2023)"]].map(([field, placeholder]) => (
                      <input key={field} value={exp[field] || ""} placeholder={placeholder}
                        onChange={e => { const updated = [...profileForm.experience]; updated[i] = { ...updated[i], [field]: e.target.value }; setProfileForm(p => ({ ...p, experience: updated })) }}
                        style={{ padding: "8px 10px", border: "1px solid #ddd", borderRadius: 5, fontSize: 13 }} />
                    ))}
                  </div>
                  <textarea value={exp.description || ""} placeholder="Describe your role and responsibilities..."
                    onChange={e => { const updated = [...profileForm.experience]; updated[i] = { ...updated[i], description: e.target.value }; setProfileForm(p => ({ ...p, experience: updated })) }}
                    style={{ width: "100%", padding: "8px 10px", border: "1px solid #ddd", borderRadius: 5, fontSize: 13, resize: "vertical", marginBottom: 6 }} rows={2} />
                  <input value={(exp.achievements || []).join("; ")} placeholder="Key achievements (separated by semicolons)"
                    onChange={e => { const updated = [...profileForm.experience]; updated[i] = { ...updated[i], achievements: e.target.value.split(";").map(s => s.trim()).filter(Boolean) }; setProfileForm(p => ({ ...p, experience: updated })) }}
                    style={{ width: "100%", padding: "8px 10px", border: "1px solid #ddd", borderRadius: 5, fontSize: 13 }} />
                </div>
              ))}
            </div>

            <button onClick={saveProfile} disabled={saving}
              style={{ marginTop: 24, background: saving ? "#aaa" : "linear-gradient(135deg, #1a5276, #2980b9)", color: "white", border: "none",
                       borderRadius: 8, padding: "12px 32px", fontSize: 15, fontWeight: 600, cursor: saving ? "not-allowed" : "pointer" }}>
              {saving ? "Saving..." : "💾 Save Profile"}
            </button>
          </div>
        )}

        {/* ── SEARCH TAB ── */}
        {tab === "search" && (
          <div>
            <div style={{ background: "white", borderRadius: 12, padding: 28, boxShadow: "0 2px 8px rgba(0,0,0,0.08)", marginBottom: 20 }}>
              <h2 style={{ marginBottom: 6, color: "#1a5276" }}>🔍 Auto Job Search & Apply</h2>
              <p style={{ color: "#666", marginBottom: 22, fontSize: 14 }}>
                JobBot will search Naukri, LinkedIn, Indeed, and Instahyre — then automatically apply to jobs with ≥80% match score.
              </p>

              <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16, marginBottom: 20 }}>
                <div>
                  <label style={{ display: "block", marginBottom: 5, fontWeight: 500, fontSize: 13, color: "#444" }}>Job Title / Skills</label>
                  <input value={searchForm.job_query} onChange={e => setSearchForm(p => ({ ...p, job_query: e.target.value }))}
                    placeholder="e.g. Python Developer, React Frontend Engineer, Data Scientist..."
                    style={{ width: "100%", padding: "10px 14px", border: "1.5px solid #2980b9", borderRadius: 8, fontSize: 15 }} />
                </div>
                <div>
                  <label style={{ display: "block", marginBottom: 5, fontWeight: 500, fontSize: 13, color: "#444" }}>Location</label>
                  <input value={searchForm.location} onChange={e => setSearchForm(p => ({ ...p, location: e.target.value }))}
                    placeholder="India, Bangalore, Remote..."
                    style={{ width: "100%", padding: "10px 14px", border: "1.5px solid #ddd", borderRadius: 8, fontSize: 15 }} />
                </div>
              </div>

              {/* Portals badges */}
              <div style={{ display: "flex", gap: 8, marginBottom: 20, flexWrap: "wrap" }}>
                <span style={{ fontSize: 12, color: "#666" }}>Searching on:</span>
                {["Naukri", "LinkedIn", "Indeed", "Instahyre", "Adzuna"].map(p => (
                  <span key={p} style={{ background: "#eaf4fb", border: "1px solid #aed6f1", borderRadius: 20, padding: "3px 12px", fontSize: 12, color: "#2980b9" }}>✓ {p}</span>
                ))}
              </div>

              <button onClick={startSearch} disabled={searching || !candidateId}
                style={{ background: searching ? "#aaa" : "linear-gradient(135deg, #1a5276, #2980b9)", color: "white", border: "none",
                         borderRadius: 8, padding: "13px 36px", fontSize: 15, fontWeight: 600, cursor: (searching || !candidateId) ? "not-allowed" : "pointer" }}>
                {searching ? "🔍 Searching & Applying..." : "🚀 Start Auto-Apply"}
              </button>

              {!candidateId && <p style={{ color: "#dc3545", fontSize: 13, marginTop: 8 }}>⚠️ Please save your profile first</p>}
            </div>

            {searchResult && (
              <div style={{ background: searchResult.error ? "#f8d7da" : "#d4edda", borderRadius: 12, padding: 20,
                            border: `1px solid ${searchResult.error ? "#f5c6cb" : "#c3e6cb"}` }}>
                {searchResult.error ? (
                  <p style={{ color: "#721c24", margin: 0 }}>❌ {searchResult.error}</p>
                ) : (
                  <div>
                    <p style={{ color: "#155724", fontWeight: 600, margin: "0 0 6px" }}>✅ {searchResult.message}</p>
                    <p style={{ color: "#155724", margin: 0, fontSize: 13 }}>Session ID: {searchResult.session_id} — Running in background. Switch to Applications tab to track progress.</p>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── TRACKER TAB ── */}
        {tab === "tracker" && (
          <div>
            {/* Summary cards */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 14, marginBottom: 22 }}>
              {[
                ["Total Found", summary.total, "#6c757d"],
                ["Applied", summary.applied, "#28a745"],
                ["Interview", summary.interview, "#007bff"],
                ["Skipped", summary.skipped, "#ffc107"],
                ["Failed", summary.failed, "#dc3545"],
              ].map(([label, count, color]) => (
                <div key={label} style={{ background: "white", borderRadius: 10, padding: "16px 20px",
                                         boxShadow: "0 2px 8px rgba(0,0,0,0.08)", borderTop: `3px solid ${color}` }}>
                  <div style={{ fontSize: 28, fontWeight: 700, color }}>{count}</div>
                  <div style={{ fontSize: 13, color: "#666", marginTop: 2 }}>{label}</div>
                </div>
              ))}
            </div>

            {/* Refresh button */}
            <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 14 }}>
              <button onClick={fetchApplications} style={{ background: "#f8f9fa", border: "1px solid #ddd",
                borderRadius: 6, padding: "7px 16px", cursor: "pointer", fontSize: 13 }}>🔄 Refresh</button>
            </div>

            {/* Applications table */}
            <div style={{ background: "white", borderRadius: 12, boxShadow: "0 2px 8px rgba(0,0,0,0.08)", overflow: "hidden" }}>
              {applications.length === 0 ? (
                <div style={{ padding: 48, textAlign: "center", color: "#aaa" }}>
                  <div style={{ fontSize: 48, marginBottom: 12 }}>📭</div>
                  <div>No applications yet. Start a job search!</div>
                </div>
              ) : (
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ background: "#f8f9fa", borderBottom: "2px solid #dee2e6" }}>
                      {["Job Title", "Company", "Portal", "Match Score", "Status", "Applied At", "Resume"].map(h => (
                        <th key={h} style={{ padding: "12px 16px", textAlign: "left", fontSize: 12, fontWeight: 600,
                                             color: "#555", textTransform: "uppercase", letterSpacing: 0.5 }}>{h}</th>
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
                            <a href={job.apply_url} target="_blank" rel="noopener noreferrer"
                               style={{ color: "#2980b9", textDecoration: "none" }}>{job.title || "—"}</a>
                          </td>
                          <td style={{ padding: "12px 16px", fontSize: 13, color: "#444" }}>{job.company || "—"}</td>
                          <td style={{ padding: "12px 16px" }}>
                            <span style={{ background: "#eaf4fb", borderRadius: 20, padding: "2px 10px", fontSize: 12, color: "#2980b9" }}>
                              {app.portal}
                            </span>
                          </td>
                          <td style={{ padding: "12px 16px", fontSize: 13 }}>
                            {resume.match_score ? (
                              <span style={{ fontWeight: 600, color: resume.match_score >= 80 ? "#28a745" : "#ffc107" }}>
                                {resume.match_score}%
                              </span>
                            ) : "—"}
                          </td>
                          <td style={{ padding: "12px 16px" }}>
                            <span style={{ background: colors.bg, color: colors.text, borderRadius: 20,
                                           padding: "3px 12px", fontSize: 12, fontWeight: 500 }}>
                              <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: "50%",
                                             background: colors.dot, marginRight: 5 }}/>
                              {app.status}
                            </span>
                          </td>
                          <td style={{ padding: "12px 16px", fontSize: 12, color: "#777" }}>
                            {app.applied_at ? new Date(app.applied_at).toLocaleDateString("en-IN") : "—"}
                          </td>
                          <td style={{ padding: "12px 16px" }}>
                            {resume.pdf_path ? (
                              <span style={{ fontSize: 12, color: "#28a745" }}>✅ PDF</span>
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
