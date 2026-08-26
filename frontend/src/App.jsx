import React, { useEffect, useState } from 'react'
import Sidebar from './components/Sidebar'

const getApiBaseUrl = () => {
  return 'VITE_API_BASE_URL=https://aiplag-production.up.railway.app'
}

const buildApiUrl = (path) => {
  const baseUrl = getApiBaseUrl()
  if (!baseUrl) return path.startsWith('/') ? path : `/${path}`
  return `${baseUrl}${path.startsWith('/') ? path : `/${path}`}`
}

const parseJsonResponse = async (res) => {
  const text = await res.text()
  if (!text) {
    throw new Error(`The backend returned an empty response (${res.status}).`)
  }

  const contentType = res.headers.get('content-type') || ''
  if (!contentType.includes('application/json') && !contentType.includes('+json')) {
    throw new Error(
      `The backend returned HTML instead of JSON. Set VITE_API_BASE_URL to your Railway backend URL, for example https://your-app.railway.app.`
    )
  }

  try {
    return JSON.parse(text)
  } catch {
    throw new Error('The backend returned invalid JSON. Check the Railway deployment URL.')
  }
}

export default function App() {
  const [file, setFile] = useState(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [analysisMode, setAnalysisMode] = useState('ai')
  const [selectedPlan, setSelectedPlan] = useState('basic')
  const [paymentMethod, setPaymentMethod] = useState('google_pay')
  const [phoneNumber, setPhoneNumber] = useState('')
  const [subscriptionStatus, setSubscriptionStatus] = useState(null)
  const [subscribing, setSubscribing] = useState(false)
  const [adminUsername, setAdminUsername] = useState('')
  const [adminPassword, setAdminPassword] = useState('')
  const [adminToken, setAdminToken] = useState(null)
  const [adminPayments, setAdminPayments] = useState([])
  const [adminLoading, setAdminLoading] = useState(false)
  const [adminError, setAdminError] = useState(null)
  const [authToken, setAuthToken] = useState(() => {
    if (typeof window === 'undefined') return null
    return window.localStorage.getItem('authToken')
  })
  const [authUsername, setAuthUsername] = useState('')
  const [authEmail, setAuthEmail] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [authMode, setAuthMode] = useState('signin')
  const [authError, setAuthError] = useState(null)
  const [authMessage, setAuthMessage] = useState('')
  const [authUser, setAuthUser] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!file) return
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('mode', analysisMode)

      const res = await fetch(buildApiUrl('/analyze'), {
        method: 'POST',
        body: fd,
      })
      if (!res.ok) {
        const body = await res.text()
        throw new Error(`Server error ${res.status}: ${body}`)
      }
      const data = await parseJsonResponse(res)
      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const loadRazorpayScript = () => {
    return new Promise((resolve, reject) => {
      if (typeof window === 'undefined') {
        reject(new Error('Razorpay is only available in the browser'))
        return
      }

      if (window.Razorpay) {
        resolve(true)
        return
      }

      const existing = document.querySelector('script[data-razorpay="true"]')
      if (existing) {
        existing.addEventListener('load', () => resolve(true))
        existing.addEventListener('error', () => reject(new Error('Unable to load Razorpay checkout script')))
        return
      }

      const script = document.createElement('script')
      script.src = 'https://checkout.razorpay.com/v1/checkout.js'
      script.async = true
      script.dataset.razorpay = 'true'
      script.onload = () => resolve(true)
      script.onerror = () => reject(new Error('Unable to load Razorpay checkout script'))
      document.body.appendChild(script)
    })
  }

  const handleSubscribe = async (e) => {
    e.preventDefault()
    setSubscribing(true)
    setError(null)
    setSubscriptionStatus(null)

    try {
      const res = await fetch(buildApiUrl('/subscribe'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          plan: selectedPlan,
          payment_method: paymentMethod,
          phone_number: paymentMethod === 'phonepe' ? phoneNumber : undefined,
        }),
      })

      const data = await parseJsonResponse(res)
      if (!res.ok) {
        throw new Error(data.detail || 'Subscription request failed')
      }

      setSubscriptionStatus({
        message: data.message,
        method: data.payment_method,
        provider: data.provider,
      })

      if (data.provider === 'razorpay' && data.checkout?.key && data.checkout?.order_id) {
        await loadRazorpayScript()
        const options = {
          key: data.checkout.key,
          amount: data.checkout.amount,
          currency: data.checkout.currency,
          name: 'AI Plag Detector',
          description: `Subscription: ${data.plan}`,
          order_id: data.checkout.order_id,
          handler: function () {
            setSubscriptionStatus({
              message: 'Payment completed successfully. Your subscription is now active.',
              method: data.payment_method,
              provider: data.provider,
            })
          },
          prefill: {
            contact: data.phone_number || '',
          },
          theme: {
            color: '#7C3AED',
          },
        }

        const razorpayInstance = new window.Razorpay(options)
        razorpayInstance.open()
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setSubscribing(false)
    }
  }

  const handleAdminLogin = async (e) => {
    e.preventDefault()
    setAdminLoading(true)
    setAdminError(null)

    try {
      const res = await fetch(buildApiUrl('/admin/login'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: adminUsername, password: adminPassword }),
      })
      const data = await parseJsonResponse(res)
      if (!res.ok) throw new Error(data.detail || 'Login failed')
      setAdminToken(data.token)
      setAdminError(null)
      setAdminUsername('')
      setAdminPassword('')
      await fetchAdminPayments(data.token)
    } catch (err) {
      setAdminError(err.message)
    } finally {
      setAdminLoading(false)
    }
  }

  const fetchAdminPayments = async (token) => {
    setAdminLoading(true)
    setAdminError(null)
    try {
      const res = await fetch(buildApiUrl('/admin/payments'), {
        headers: { Authorization: `Bearer ${token}` },
      })
      const data = await parseJsonResponse(res)
      if (!res.ok) throw new Error(data.detail || 'Could not fetch payments')
      setAdminPayments(data.payments || [])
    } catch (err) {
      setAdminError(err.message)
    } finally {
      setAdminLoading(false)
    }
  }

  const handleConfirmPayment = async (paymentEventId) => {
    if (!adminToken) return
    setAdminLoading(true)
    setAdminError(null)
    try {
      const res = await fetch(buildApiUrl('/payment-confirm'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payment_event_id: paymentEventId, payment_id: `pay_${Date.now()}` }),
      })
      const data = await parseJsonResponse(res)
      if (!res.ok) throw new Error(data.detail || 'Confirmation failed')
      await fetchAdminPayments(adminToken)
    } catch (err) {
      setAdminError(err.message)
    } finally {
      setAdminLoading(false)
    }
  }

  const handleSignUp = async (e) => {
    e.preventDefault()
    setAuthError(null)
    try {
      const res = await fetch(buildApiUrl('/signup'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: authUsername, password: authPassword, email: authEmail }),
      })
      const data = await parseJsonResponse(res)
      if (!res.ok) throw new Error(data.detail || data.message || 'Signup failed')
      setAuthToken(data.token)
      setAuthUser(data.user || { username: authUsername, email: authEmail })
      setAuthMode('signin')
      setAuthError(null)
      setAuthMessage(data.message || 'Account created successfully')
      setAuthUsername('')
      setAuthPassword('')
      setAuthEmail('')
      setActiveNav('profile')
    } catch (err) {
      setAuthError(err.message)
    }
  }

  const handleSignIn = async (e) => {
    e.preventDefault()
    setAuthError(null)
    try {
      const res = await fetch(buildApiUrl('/signin'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: authUsername, password: authPassword }),
      })
      const data = await parseJsonResponse(res)
      if (!res.ok) throw new Error(data.detail || data.message || 'Signin failed')
      setAuthToken(data.token)
      setAuthUser(data.user || { username: authUsername })
      setAuthError(null)
      setAuthMessage(data.message || 'Login successful')
      setAuthUsername('')
      setAuthPassword('')
      setActiveNav('profile')
    } catch (err) {
      setAuthError(err.message)
    }
  }

 const handleDownloadReport = async () => {
  if (!result) return

  setError(null)

  try {
    const payload = {
      results: result.results || [],
      aggregate: result.aggregate || {},
      title: `ai_plag_report_${Date.now()}`
    }

    const res = await fetch(buildApiUrl('/download-report'), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    })

    if (!res.ok) {
      const body = await res.text()
      throw new Error(`Download failed ${res.status}: ${body}`)
    }

    const blob = await res.blob()

    if (blob.size === 0) {
      throw new Error('The backend returned an empty PDF.')
    }

    const url = window.URL.createObjectURL(blob)

    const a = document.createElement('a')
    a.href = url
    a.download = `${payload.title}.pdf`

    document.body.appendChild(a)
    a.click()
    a.remove()

    window.URL.revokeObjectURL(url)

  } catch (err) {
    setError(err.message)
  }
}

  const getRiskLevel = (score) => {
    if (score >= 70) return { level: 'HIGH', color: '#dc2626' }
    if (score >= 50) return { level: 'MEDIUM', color: '#f97316' }
    return { level: 'LOW', color: '#16a34a' }
  }

  const getResultStats = (results) => {
    if (!results || !Array.isArray(results)) return null
    const highAI = results.filter(r => r.score >= 60).length
    const mediumAI = results.filter(r => r.score >= 40 && r.score < 60).length
    const lowAI = results.filter(r => r.score < 40).length
    return { highAI, mediumAI, lowAI, total: results.length }
  }

  const stats = result?.results ? getResultStats(result.results) : null
  const overallScore = result?.aggregate?.overall_score ?? 0
  const plagiarismScore = result?.aggregate?.plagiarism_score
  const externalError = result?.external_error
  const externalSource = result?.external_source

  const [activeNav, setActiveNav] = useState('upload')

  const loadUserProfile = async (token) => {
    if (!token) return
    try {
      const res = await fetch(buildApiUrl('/profile'), {
        headers: { Authorization: `Bearer ${token}` },
      })
      const data = await parseJsonResponse(res)
      if (!res.ok) throw new Error(data.detail || 'Unable to load profile')
      setAuthUser(data.user || null)
      if (data.user?.username) {
        setAuthUsername('')
        setAuthPassword('')
      }
    } catch (err) {
      setAuthError(err.message)
    }
  }

  useEffect(() => {
    if (authToken) {
      window.localStorage.setItem('authToken', authToken)
      loadUserProfile(authToken)
    } else {
      window.localStorage.removeItem('authToken')
      setAuthUser(null)
    }
  }, [authToken])

  return (
    <div className="app">
      <header className="header">
        <div className="header-content">
          <h1>🔍 AI Detection Analyzer</h1>
          <p>Detect AI-generated content in your Word documents</p>
        </div>
      </header>

      <div className="layout">
        <Sidebar activeNav={activeNav} setActiveNav={setActiveNav} />

        <main className="main">
          <div className="container">
            {/* Conditionally render views based on sidebar nav */}
            {activeNav === 'admin' ? (
              <section className="details-section">
                <h3>Admin Panel</h3>
                {!adminToken ? (
                  <form onSubmit={handleAdminLogin} style={{ display: 'grid', gap: 12, maxWidth: 420 }}>
                    <label>
                      Admin username
                      <input
                        type="text"
                        value={adminUsername}
                        onChange={(e) => setAdminUsername(e.target.value)}
                        className="payment-input"
                      />
                    </label>
                    <label>
                      Password
                      <input
                        type="password"
                        value={adminPassword}
                        onChange={(e) => setAdminPassword(e.target.value)}
                        className="payment-input"
                      />
                    </label>
                    <button className="btn-submit" type="submit" disabled={adminLoading}>
                      {adminLoading ? 'Logging in…' : 'Admin Login'}
                    </button>
                    {adminError && <p style={{ color: '#b91c1c' }}>{adminError}</p>}
                  </form>
                ) : (
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
                      <div>
                        <p>Logged in as <strong>admin</strong></p>
                        <p style={{ color: 'var(--text-muted)' }}>View subscription payment activity.</p>
                      </div>
                      <button className="btn-secondary" onClick={() => { setAdminToken(null); setAdminPayments([]) }}>
                        Logout
                      </button>
                    </div>
                    {adminError && <p style={{ color: '#b91c1c' }}>{adminError}</p>}
                    <div className="details-section" style={{ padding: '1.5rem' }}>
                      <h4>Payment Events</h4>
                      {adminLoading ? (
                        <p>Loading…</p>
                      ) : adminPayments.length === 0 ? (
                        <p>No payment events yet.</p>
                      ) : (
                        <div style={{ display: 'grid', gap: 12 }}>
                          {adminPayments.map((event, idx) => (
                            <div key={idx} className="paragraph-item" style={{ borderLeftColor: '#7C3AED' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
                                <strong>{event.plan} — {event.status}</strong>
                                {event.status !== 'completed' && (
                                  <button className="btn-secondary" type="button" onClick={() => handleConfirmPayment(event.id)}>
                                    Confirm
                                  </button>
                                )}
                              </div>
                              <div style={{ marginTop: 10, color: 'var(--text-muted)', fontSize: '0.95rem' }}>
                                Order: {event.order_id}<br />
                                Method: {event.payment_method}<br />
                                Phone: {event.phone_number || 'n/a'}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </section>
            ) : activeNav === 'login' ? (
              <section className="auth-section">
                <h3>{authMode === 'signin' ? 'Sign In' : 'Sign Up'}</h3>
                <form onSubmit={authMode === 'signin' ? handleSignIn : handleSignUp} style={{ display: 'grid', gap: 12, maxWidth: 420 }}>
                  {authMode === 'signup' && (
                    <label>
                      Email
                      <input type="email" value={authEmail} onChange={(e) => setAuthEmail(e.target.value)} className="payment-input" />
                    </label>
                  )}
                  <label>
                    Username
                    <input type="text" value={authUsername} onChange={(e) => setAuthUsername(e.target.value)} className="payment-input" />
                  </label>
                  <label>
                    Password
                    <input type="password" value={authPassword} onChange={(e) => setAuthPassword(e.target.value)} className="payment-input" />
                  </label>
                  <button className="btn-submit" type="submit">
                    {authMode === 'signin' ? 'Sign In' : 'Create Account'}
                  </button>
                </form>
                <div style={{ marginTop: 12 }}>
                  <button className="btn-link" onClick={() => setAuthMode(authMode === 'signin' ? 'signup' : 'signin')}>{authMode === 'signin' ? 'Create an account' : 'Have an account? Sign in'}</button>
                </div>
                {authError && <p style={{ color: '#b91c1c' }}>{authError}</p>}
                {authMessage && <p style={{ color: '#15803d' }}>{authMessage}</p>}
              </section>
            ) : activeNav === 'profile' ? (
              <section className="profile-view">
                <div className="details-section">
                  <h3>Profile</h3>
                  <div style={{ display: 'flex', gap: 20, alignItems: 'center' }}>
                    <div className="avatar" style={{ width: 96, height: 96, fontSize: 28 }}>{(authUser?.username || 'U').slice(0, 2).toUpperCase()}</div>
                    <div>
                      <div style={{ fontSize: 20, fontWeight: 800 }}>{authUser?.username || 'Your Profile'}</div>
                      <div style={{ color: 'var(--text-muted)', marginTop: 6 }}>{authUser?.email || 'No email provided yet'}</div>
                      {authMessage && <div style={{ marginTop: 8, color: '#15803d' }}>{authMessage}</div>}
                      <div style={{ marginTop: 12 }}>
                        <button className="btn-secondary">Edit Profile</button>
                      </div>
                    </div>
                  </div>
                </div>
              </section>
            ) : (
              <>
          {/* Upload Section */}
          <section className="upload-section">
            <div className="upload-card">
              <div className="upload-icon">📄</div>
              <h2>Upload Document</h2>
              <p style={{ marginBottom: '1rem', color: 'var(--text-muted)' }}>
                Choose the analysis mode before uploading.
              </p>
              <form onSubmit={handleSubmit}>
                <label htmlFor="file-input" className="file-label">
                  <span className="file-input-text">
                    {file ? `✓ ${file.name}` : 'Click to select .docx file or drag & drop'}
                  </span>
                  <input
                    id="file-input"
                    type="file"
                    accept=".docx"
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                    className="file-input"
                  />
                </label>
                <div className="analysis-options" style={{ display: 'flex', gap: 10, flexWrap: 'wrap', justifyContent: 'center', marginBottom: 16 }}>
                  <label className="payment-option" style={{ cursor: 'pointer' }}>
                    <input
                      type="radio"
                      name="analysis_mode"
                      value="ai"
                      checked={analysisMode === 'ai'}
                      onChange={(e) => setAnalysisMode(e.target.value)}
                    />
                    <span>AI Detection</span>
                  </label>
                  <label className="payment-option" style={{ cursor: 'pointer' }}>
                    <input
                      type="radio"
                      name="analysis_mode"
                      value="plagiarism"
                      checked={analysisMode === 'plagiarism'}
                      onChange={(e) => setAnalysisMode(e.target.value)}
                    />
                    <span>Plagiarism Detection</span>
                  </label>
                </div>
                <button type="submit" disabled={!file || loading} className="btn-submit">
                  {loading ? (
                    <>
                      <span className="spinner"></span>
                      Analyzing…
                    </>
                  ) : (
                    '🚀 Analyze Document'
                  )}
                </button>
              </form>
            </div>
          </section>

          {/* Error State */}
          {error && (
            <div className="error-box">
              <span className="error-icon">⚠️</span>
              <div>
                <strong>Error</strong>
                <p>{error}</p>
              </div>
            </div>
          )}

          {/* Results Section */}
          {result && (
            <section className="results-section">
              {/* Overall Score Card */}
              <div className="score-card">
                <div className="score-header">
                  <h3>{analysisMode === 'plagiarism' ? 'Overall Plagiarism Score' : 'Overall AI Score'}</h3>
                  <span className="score-badge">{overallScore}%</span>
                </div>
                <div className="score-bar-container">
                  <div className="score-bar">
                    <div
                      className="score-fill"
                      style={{
                        width: `${overallScore}%`,
                        backgroundColor: getRiskLevel(overallScore).color,
                      }}
                    ></div>
                  </div>
                  <span className="risk-label" style={{ color: getRiskLevel(overallScore).color }}>
                    {getRiskLevel(overallScore).level} RISK
                  </span>
                </div>
                {plagiarismScore !== undefined && plagiarismScore !== null && (
                  <div className="score-summary-row" style={{ marginTop: '1.25rem' }}>
                    <strong>Plagiarism Score:</strong> {plagiarismScore}%
                    {result.aggregate.plagiarism_label ? ` — ${result.aggregate.plagiarism_label}` : ''}
                  </div>
                )}
                {externalSource && (
                  <div className="score-summary-row" style={{ marginTop: '0.75rem', color: '#2563eb' }}>
                    External API analysis applied.
                  </div>
                )}
              </div>

              {/* Statistics Grid */}
              {stats && (
                <div className="stats-grid">
                  <div className="stat-card high">
                    <div className="stat-number">{stats.highAI}</div>
                    <div className="stat-label">High AI Risk</div>
                    <div className="stat-percent">({((stats.highAI / stats.total) * 100).toFixed(0)}%)</div>
                  </div>
                  <div className="stat-card medium">
                    <div className="stat-number">{stats.mediumAI}</div>
                    <div className="stat-label">Medium AI Risk</div>
                    <div className="stat-percent">({((stats.mediumAI / stats.total) * 100).toFixed(0)}%)</div>
                  </div>
                  <div className="stat-card low">
                    <div className="stat-number">{stats.lowAI}</div>
                    <div className="stat-label">Low AI Risk</div>
                    <div className="stat-percent">({((stats.lowAI / stats.total) * 100).toFixed(0)}%)</div>
                  </div>
                </div>
              )}

              {/* Detailed Results */}
              <div className="details-section">
                <h3>Paragraph Analysis</h3>
                <div className="paragraphs-list">
                  {result.results?.map((para, idx) => {
                    const risk = getRiskLevel(para.score)
                    return (
                      <div key={idx} className="paragraph-item" style={{ borderLeftColor: risk.color }}>
                        <div className="para-header">
                          <span className="para-number">¶ {para.index}</span>
                          <span className="para-score" style={{ backgroundColor: risk.color }}>
                            {para.score}% — {risk.level}
                          </span>
                        </div>
                        <p className="para-text">{para.text.substring(0, 150)}…</p>
                        <div className="para-footer" style={{ display: 'grid', gap: 6 }}>
                          <small>{para.reason}</small>
                          {para.plagiarism_score != null && (
                            <small>
                              Plagiarism: {para.plagiarism_score}%{para.plagiarism_label ? ` — ${para.plagiarism_label}` : ''}
                            </small>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Action Buttons */}
              <div className="action-buttons">
                <button className="btn-secondary" onClick={() => setResult(null)}>
                  Analyze Another File
                </button>
                <button className="btn-secondary" onClick={handleDownloadReport} style={{ marginLeft: 8 }}>
                  Download Report
                </button>
              </div>
            </section>
          )}

          {/* Info Box */}
          <div className="info-box">
            <h4>ℹ️ About This Tool</h4>
            <p>
              This tool analyzes Word documents to detect AI-generated content and plagiarism using your configured backend API.
            </p>
            <p style={{ marginTop: 8, fontSize: '0.9em', color: '#666' }}>
              Backend endpoint: <code>/analyze</code> (FastAPI wrapper around analyze_docx.py).
            </p>
            <div className="subscription-card" style={{ marginTop: 18 }}>
              <h4 style={{ marginBottom: 12 }}>💳 Subscription Plans</h4>
              <div style={{ marginBottom: 18, padding: 16, borderRadius: 16, background: 'rgba(255,255,255,0.92)', border: '1px solid rgba(124,58,237,0.14)' }}>
                <div style={{ marginBottom: 10, fontWeight: 700 }}>UPI ID</div>
                <div style={{ marginBottom: 14, fontSize: '1.05rem', color: 'var(--primary-dark)', fontWeight: 800 }}>
                  gogreensavepaper@ibl
                </div>
                <div style={{ color: 'var(--text-muted)', lineHeight: 1.6 }}>
                  Use the UPI ID above to pay for your selected plan. Your subscription is activated after payment confirmation.
                </div>
              </div>
              <div className="plan-selector" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 18 }}>
                {[
                  { id: 'basic', title: 'Basic', description: '2999 words', price: '₹599/-' },
                  { id: 'premium', title: 'Premium', description: '7999 words', price: '₹1499/-' },
                  { id: 'premium_pro', title: 'Premium Pro', description: '10000 words', price: '₹1999/-' },
                ].map((plan) => (
                  <button
                    key={plan.id}
                    type="button"
                    className={`plan-card ${selectedPlan === plan.id ? 'active' : ''}`}
                    onClick={() => setSelectedPlan(plan.id)}
                    style={{
                      padding: '1rem',
                      borderRadius: '16px',
                      border: selectedPlan === plan.id ? '2px solid var(--primary)' : '1px solid rgba(124,58,237,0.18)',
                      background: selectedPlan === plan.id ? 'rgba(124,58,237,0.1)' : 'white',
                      cursor: 'pointer',
                      textAlign: 'left',
                      minHeight: '120px',
                      transition: 'all 0.2s ease',
                    }}
                  >
                    <div style={{ fontSize: '1rem', fontWeight: 700, marginBottom: 6 }}>{plan.title}</div>
                    <div style={{ color: 'var(--text-muted)', marginBottom: 14 }}>{plan.description}</div>
                    <div style={{ fontSize: '1.1rem', fontWeight: 800 }}>{plan.price}</div>
                  </button>
                ))}
              </div>
              <form onSubmit={handleSubscribe} className="subscription-form">
                <div className="payment-options" style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
                  <label className="payment-option">
                    <input
                      type="radio"
                      name="payment_method"
                      value="google_pay"
                      checked={paymentMethod === 'google_pay'}
                      onChange={(e) => setPaymentMethod(e.target.value)}
                    />
                    <span>Google Pay</span>
                  </label>
                  <label className="payment-option">
                    <input
                      type="radio"
                      name="payment_method"
                      value="phonepe"
                      checked={paymentMethod === 'phonepe'}
                      onChange={(e) => setPaymentMethod(e.target.value)}
                    />
                    <span>PhonePe</span>
                  </label>
                </div>

                {paymentMethod === 'phonepe' && (
                  <input
                    type="tel"
                    className="payment-input"
                    placeholder="Enter phone number"
                    value={phoneNumber}
                    onChange={(e) => setPhoneNumber(e.target.value)}
                    style={{ marginBottom: 12 }}
                  />
                )}

                <button type="submit" className="btn-submit" disabled={subscribing}>
                  {subscribing ? 'Processing…' : `Subscribe to ${selectedPlan.replace('_', ' ').replace(/\b\w/g, (x) => x.toUpperCase())}`}
                </button>
              </form>
              {subscriptionStatus && (
                <p style={{ marginTop: 12, color: '#15803d', fontWeight: 700 }}>
                  {subscriptionStatus.message}
                </p>
              )}
              <p style={{ marginTop: 14, color: 'var(--text-muted)', fontSize: '0.9rem', lineHeight: 1.6 }}>
                Terms and conditions apply. No profit business.
              </p>
            </div>
            {externalError && (
              <p style={{ marginTop: 8, color: '#b91c1c', fontWeight: 700 }}>
                External API error: {externalError}
              </p>
            )}
            {!externalError && externalSource && (
              <p style={{ marginTop: 8, color: '#2563eb', fontWeight: 700 }}>
                Plagiarism and AI detection data were returned from the external API.
              </p>
            )}
          </div>
            </>
            )}
          </div>
        </main>
      </div>

      <footer className="footer">
        <p>© 2026 AI Plag Detector • Protecting Academic Integrity</p>
      </footer>
    </div>
  )
}
