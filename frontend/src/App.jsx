import React, { useEffect, useState } from 'react'
import Sidebar from './components/Sidebar'

const getApiBaseUrl = () => {
  return 'https://aiplag-production.up.railway.app'
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
  const [hasActiveSubscription, setHasActiveSubscription] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.localStorage.getItem('subscriptionActive') === 'true'
  })
  const [activeNav, setActiveNav] = useState(() => {
    if (typeof window === 'undefined') return 'login'
    return window.localStorage.getItem('authToken')
      ? (window.localStorage.getItem('subscriptionActive') === 'true' ? 'upload' : 'subscription')
      : 'login'
  })

  const handlePaymentSuccess = (message = 'Payment completed successfully. Your subscription is now active.') => {
    setHasActiveSubscription(true)
    window.localStorage.setItem('subscriptionActive', 'true')
    setSubscriptionStatus({
      message,
      method: paymentMethod,
      provider: 'razorpay',
    })
    setActiveNav('upload')
  }

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
        headers: authToken ? { Authorization: `Bearer ${authToken}` } : undefined,
        body: fd,
      })
      if (!res.ok) {
        let message = `Server error ${res.status}`
        try {
          const errBody = await res.json()
          if (errBody?.detail) message = errBody.detail
        } catch {
          // response wasn't JSON; fall back to the generic message above
        }
        throw new Error(message)
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
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
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
          handler: async function (response) {
            // Confirm the payment so the backend saves this plan + word limit on the user.
            try {
              const confirmRes = await fetch(buildApiUrl('/payment-confirm'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  payment_event_id: data.payment_event_id,
                  payment_id: response.razorpay_payment_id,
                  status: 'completed',
                }),
              })
              if (!confirmRes.ok) {
                throw new Error(`Payment confirm returned ${confirmRes.status}`)
              }
              handlePaymentSuccess()
            } catch (confirmErr) {
              console.error('Payment confirm failed', confirmErr)
              setError('Payment succeeded but we could not confirm your plan with the server. Please contact support before uploading a document.')
            }
          },
          prefill: {
            contact: data.phone_number || '',
          },
          theme: {
            color: '#142138',
          },
        }

        const razorpayInstance = new window.Razorpay(options)
        razorpayInstance.open()
      } else if (data.provider === 'demo') {
        try {
          const confirmRes = await fetch(buildApiUrl('/payment-confirm'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              payment_event_id: data.payment_event_id,
              payment_id: `demo-${Date.now()}`,
              status: 'completed',
            }),
          })
          if (!confirmRes.ok) {
            throw new Error(`Payment confirm returned ${confirmRes.status}`)
          }
          handlePaymentSuccess('Demo payment completed successfully. Your subscription is now active.')
        } catch (confirmErr) {
          console.error('Payment confirm failed', confirmErr)
          setError('Payment succeeded but we could not confirm your plan with the server. Please try subscribing again.')
        }
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
      setHasActiveSubscription(false)
      window.localStorage.removeItem('subscriptionActive')
      setActiveNav('subscription')
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
      setHasActiveSubscription(false)
      window.localStorage.removeItem('subscriptionActive')
      setActiveNav('subscription')
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
    if (score >= 70) return { level: 'High', color: '#B3261E' }
    if (score >= 50) return { level: 'Medium', color: '#B7791F' }
    return { level: 'Low', color: '#1F7A4D' }
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
      setActiveNav(hasActiveSubscription ? 'upload' : 'subscription')
    } else {
      window.localStorage.removeItem('authToken')
      window.localStorage.removeItem('subscriptionActive')
      setAuthUser(null)
      setHasActiveSubscription(false)
      setActiveNav('login')
    }
  }, [authToken, hasActiveSubscription])

  const handleLogout = () => {
    setAuthToken(null)
    setAuthMessage('')
    setResult(null)
  }

  return (
    <div className="app">
      <header className="header">
        <div className="header-content">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
                <circle cx="20" cy="20" r="18" stroke="currentColor" strokeWidth="1.5" />
                <path d="M12 20.5L17 25.5L28 14.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <div>
              <h1>SAHFON Verify</h1>
              <p className="brand-tagline">Academic Integrity &amp; AI Content Verification</p>
            </div>
          </div>
          <p className="brand-origin">An initiative of Saathaihum Foundation</p>
        </div>
      </header>

      <div className="layout">
        <Sidebar user={authUser} onLogout={handleLogout} />

        <main className="main">
          <div className="container">
            {activeNav === 'admin' ? (
              <section className="panel">
                <div className="panel-head">
                  <h2>Admin panel</h2>
                  <p className="panel-subtext">Review and confirm subscription payment activity.</p>
                </div>

                {!adminToken ? (
                  <form onSubmit={handleAdminLogin} className="form form--narrow">
                    <label className="field">
                      <span className="field-label">Admin username</span>
                      <input
                        type="text"
                        value={adminUsername}
                        onChange={(e) => setAdminUsername(e.target.value)}
                        className="input"
                        autoComplete="username"
                      />
                    </label>
                    <label className="field">
                      <span className="field-label">Password</span>
                      <input
                        type="password"
                        value={adminPassword}
                        onChange={(e) => setAdminPassword(e.target.value)}
                        className="input"
                        autoComplete="current-password"
                      />
                    </label>
                    <button className="btn btn-primary" type="submit" disabled={adminLoading}>
                      {adminLoading ? (
                        <>
                          <span className="spinner" aria-hidden="true"></span>
                          Logging in
                        </>
                      ) : (
                        'Log in'
                      )}
                    </button>
                    {adminError && <p className="form-error" role="alert">{adminError}</p>}
                  </form>
                ) : (
                  <div>
                    <div className="panel-toolbar">
                      <div>
                        <p className="panel-toolbar-title">Logged in as admin</p>
                        <p className="panel-subtext">Payment events across all plans</p>
                      </div>
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => { setAdminToken(null); setAdminPayments([]) }}
                      >
                        Log out
                      </button>
                    </div>

                    {adminError && <p className="form-error" role="alert">{adminError}</p>}

                    <div className="card">
                      <div className="card-head">
                        <h3>Payment events</h3>
                        {adminPayments.length > 0 && (
                          <span className="count-pill">{adminPayments.length}</span>
                        )}
                      </div>

                      {adminLoading ? (
                        <div className="empty-state">
                          <span className="spinner spinner-lg" aria-hidden="true"></span>
                          <p>Loading payment events…</p>
                        </div>
                      ) : adminPayments.length === 0 ? (
                        <div className="empty-state">
                          <p>No payment events yet. New subscriptions will appear here.</p>
                        </div>
                      ) : (
                        <ul className="event-list">
                          {adminPayments.map((event, idx) => (
                            <li key={idx} className="event-row">
                              <div className="event-row-main">
                                <div className="event-row-heading">
                                  <span className="event-plan">{event.plan}</span>
                                  <span className={`status-chip status-chip--${event.status === 'completed' ? 'success' : 'pending'}`}>
                                    {event.status}
                                  </span>
                                </div>
                                <dl className="event-meta">
                                  <div>
                                    <dt>Order</dt>
                                    <dd>{event.order_id}</dd>
                                  </div>
                                  <div>
                                    <dt>Method</dt>
                                    <dd>{event.payment_method}</dd>
                                  </div>
                                  <div>
                                    <dt>Phone</dt>
                                    <dd>{event.phone_number || '—'}</dd>
                                  </div>
                                </dl>
                              </div>
                              {event.status !== 'completed' && (
                                <button
                                  className="btn btn-secondary btn-sm"
                                  type="button"
                                  onClick={() => handleConfirmPayment(event.id)}
                                >
                                  Confirm payment
                                </button>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                )}
              </section>
            ) : activeNav === 'login' ? (
              <section className="panel panel--centered">
                <div className="panel-head">
                  <h2>{authMode === 'signin' ? 'Sign in' : 'Create your account'}</h2>
                  <p className="panel-subtext">
                    {authMode === 'signin'
                      ? 'Welcome back — sign in to continue verifying documents.'
                      : 'Set up an account to start uploading and analyzing documents.'}
                  </p>
                </div>

                <form onSubmit={authMode === 'signin' ? handleSignIn : handleSignUp} className="form form--narrow">
                  {authMode === 'signup' && (
                    <label className="field">
                      <span className="field-label">Email</span>
                      <input
                        type="email"
                        value={authEmail}
                        onChange={(e) => setAuthEmail(e.target.value)}
                        className="input"
                        autoComplete="email"
                      />
                    </label>
                  )}
                  <label className="field">
                    <span className="field-label">Username</span>
                    <input
                      type="text"
                      value={authUsername}
                      onChange={(e) => setAuthUsername(e.target.value)}
                      className="input"
                      autoComplete="username"
                    />
                  </label>
                  <label className="field">
                    <span className="field-label">Password</span>
                    <input
                      type="password"
                      value={authPassword}
                      onChange={(e) => setAuthPassword(e.target.value)}
                      className="input"
                      autoComplete={authMode === 'signin' ? 'current-password' : 'new-password'}
                    />
                  </label>
                  <button className="btn btn-primary" type="submit">
                    {authMode === 'signin' ? 'Sign in' : 'Create account'}
                  </button>
                </form>

                <button
                  className="btn-link"
                  onClick={() => setAuthMode(authMode === 'signin' ? 'signup' : 'signin')}
                >
                  {authMode === 'signin' ? "Don't have an account? Create one" : 'Already have an account? Sign in'}
                </button>

                {authError && <p className="form-error" role="alert">{authError}</p>}
                {authMessage && <p className="form-success" role="status">{authMessage}</p>}
              </section>
            ) : activeNav === 'subscription' ? (
              <section className="panel">
                <div className="panel-head">
                  <h2>Choose your plan</h2>
                  <p className="panel-subtext">Complete payment to unlock document uploading and analysis.</p>
                </div>

                <div className="plan-grid">
                  {[
                    { id: 'basic', title: 'Basic', description: 'Up to 2,999 words', price: '₹499', period: 'one-time' },
                    { id: 'premium', title: 'Premium', description: 'Up to 7,999 words', price: '₹1,499', period: 'one-time' },
                    { id: 'premium_pro', title: 'Premium Pro', description: 'Up to 10,000 words', price: '₹1,999', period: 'one-time' },
                  ].map((plan) => (
                    <button
                      key={plan.id}
                      type="button"
                      className={`plan-card ${selectedPlan === plan.id ? 'plan-card--active' : ''}`}
                      onClick={() => setSelectedPlan(plan.id)}
                      aria-pressed={selectedPlan === plan.id}
                    >
                      {selectedPlan === plan.id && <span className="plan-card-check" aria-hidden="true">✓</span>}
                      <span className="plan-card-title">{plan.title}</span>
                      <span className="plan-card-desc">{plan.description}</span>
                      <span className="plan-card-price">
                        {plan.price}
                        <span className="plan-card-period"> / {plan.period}</span>
                      </span>
                    </button>
                  ))}
                </div>

                <div className="card card--payment">
                  <h3>Payment method</h3>
                  <form onSubmit={handleSubscribe} className="form">
                    <div className="segmented" role="radiogroup" aria-label="Payment method">
                      <label className={`segmented-option ${paymentMethod === 'google_pay' ? 'is-active' : ''}`}>
                        <input
                          type="radio"
                          name="payment_method"
                          value="google_pay"
                          checked={paymentMethod === 'google_pay'}
                          onChange={(e) => setPaymentMethod(e.target.value)}
                        />
                        <span>Google Pay</span>
                      </label>
                      <label className={`segmented-option ${paymentMethod === 'phonepe' ? 'is-active' : ''}`}>
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
                      <label className="field">
                        <span className="field-label">Phone number</span>
                        <input
                          type="tel"
                          className="input"
                          placeholder="10-digit mobile number"
                          value={phoneNumber}
                          onChange={(e) => setPhoneNumber(e.target.value)}
                        />
                      </label>
                    )}

                    <button type="submit" className="btn btn-primary" disabled={subscribing}>
                      {subscribing ? (
                        <>
                          <span className="spinner" aria-hidden="true"></span>
                          Processing…
                        </>
                      ) : (
                        `Subscribe to ${selectedPlan.replace('_', ' ').replace(/\b\w/g, (x) => x.toUpperCase())}`
                      )}
                    </button>
                  </form>

                  {subscriptionStatus && (
                    <p className="form-success" role="status">{subscriptionStatus.message}</p>
                  )}
                </div>

                {error && <p className="form-error" role="alert">{error}</p>}
              </section>
            ) : (
              <>
                {/* Upload Section */}
                <section className="upload-section">
                  <div className="upload-card">
                    <div className="upload-icon" aria-hidden="true">
                      <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M24 6v24m0-24 8 8m-8-8-8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        <path d="M8 32v6a4 4 0 0 0 4 4h24a4 4 0 0 0 4-4v-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>
                    <h2>Upload a document</h2>
                    <p className="upload-subtext">Choose an analysis mode, then select a .docx file to verify.</p>

                    <form onSubmit={handleSubmit}>
                      <label htmlFor="file-input" className={`file-drop ${file ? 'file-drop--filled' : ''}`}>
                        <span className="file-drop-text">
                          {file ? file.name : 'Click to select a .docx file, or drag and drop'}
                        </span>
                        {file && <span className="file-drop-badge">Selected</span>}
                        <input
                          id="file-input"
                          type="file"
                          accept=".docx"
                          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                          className="file-input-hidden"
                        />
                      </label>

                      <div className="segmented segmented--wide" role="radiogroup" aria-label="Analysis mode">
                        <label className={`segmented-option ${analysisMode === 'ai' ? 'is-active' : ''}`}>
                          <input
                            type="radio"
                            name="analysis_mode"
                            value="ai"
                            checked={analysisMode === 'ai'}
                            onChange={(e) => setAnalysisMode(e.target.value)}
                          />
                          <span>AI Detection</span>
                        </label>
                        <label className={`segmented-option ${analysisMode === 'plagiarism' ? 'is-active' : ''}`}>
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

                      <button type="submit" disabled={!file || loading} className="btn btn-primary btn-lg btn-block">
                        {loading ? (
                          <>
                            <span className="spinner" aria-hidden="true"></span>
                            Analyzing document…
                          </>
                        ) : (
                          'Analyze document'
                        )}
                      </button>
                    </form>
                  </div>
                </section>

                {/* Error State */}
                {error && (
                  <div className="error-box" role="alert">
                    <span className="error-icon" aria-hidden="true">!</span>
                    <div>
                      <strong>Something went wrong</strong>
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
                        <h3>{analysisMode === 'plagiarism' ? 'Overall plagiarism score' : 'Overall AI score'}</h3>
                        <span
                          className="risk-tag"
                          style={{ color: getRiskLevel(overallScore).color, borderColor: getRiskLevel(overallScore).color }}
                        >
                          {getRiskLevel(overallScore).level} risk
                        </span>
                      </div>

                      <div className="score-bar-row">
                        <div className="score-bar">
                          <div
                            className="score-fill"
                            style={{
                              width: `${overallScore}%`,
                              backgroundColor: getRiskLevel(overallScore).color,
                            }}
                          ></div>
                        </div>
                        <span className="score-number">{overallScore}%</span>
                      </div>

                      {plagiarismScore !== undefined && plagiarismScore !== null && (
                        <div className="score-summary-row">
                          <strong>Plagiarism score:</strong> {plagiarismScore}%
                          {result.aggregate.plagiarism_label ? ` — ${result.aggregate.plagiarism_label}` : ''}
                        </div>
                      )}

                      {externalSource && (
                        <div className="score-summary-row score-summary-row--muted">
                          Verified using external API analysis.
                        </div>
                      )}
                    </div>

                    {/* Statistics Grid */}
                    {stats && (
                      <div className="stats-grid">
                        <div className="stat-card stat-card--high">
                          <div className="stat-number">{stats.highAI}</div>
                          <div className="stat-label">High AI risk</div>
                          <div className="stat-percent">{((stats.highAI / stats.total) * 100).toFixed(0)}%</div>
                        </div>
                        <div className="stat-card stat-card--medium">
                          <div className="stat-number">{stats.mediumAI}</div>
                          <div className="stat-label">Medium AI risk</div>
                          <div className="stat-percent">{((stats.mediumAI / stats.total) * 100).toFixed(0)}%</div>
                        </div>
                        <div className="stat-card stat-card--low">
                          <div className="stat-number">{stats.lowAI}</div>
                          <div className="stat-label">Low AI risk</div>
                          <div className="stat-percent">{((stats.lowAI / stats.total) * 100).toFixed(0)}%</div>
                        </div>
                      </div>
                    )}

                    {/* Detailed Results */}
                    <div className="card">
                      <div className="card-head">
                        <h3>Paragraph analysis</h3>
                      </div>
                      <ul className="paragraphs-list">
                        {result.results?.map((para, idx) => {
                          const risk = getRiskLevel(para.score)
                          return (
                            <li key={idx} className="paragraph-item" style={{ borderLeftColor: risk.color }}>
                              <div className="para-header">
                                <span className="para-number">¶ {para.index}</span>
                                <span className="para-score" style={{ color: risk.color, borderColor: risk.color }}>
                                  {para.score}% · {risk.level}
                                </span>
                              </div>
                              <p className="para-text">{para.text.substring(0, 150)}…</p>
                              <div className="para-footer">
                                <small>{para.reason}</small>
                                {para.plagiarism_score != null && (
                                  <small>
                                    Plagiarism: {para.plagiarism_score}%{para.plagiarism_label ? ` — ${para.plagiarism_label}` : ''}
                                  </small>
                                )}
                              </div>
                            </li>
                          )
                        })}
                      </ul>
                    </div>

                    {/* Action Buttons */}
                    <div className="action-buttons">
                      <button className="btn btn-secondary" onClick={() => setResult(null)}>
                        Analyze another file
                      </button>
                      <button className="btn btn-primary" onClick={handleDownloadReport}>
                        Download report
                      </button>
                    </div>
                  </section>
                )}

                {/* Info Box */}
                <div className="info-box">
                  <h4>⚠️ Important Notice — One-Time Login & Analysis Access</h4>

                  <p>
                    Please read the following notice carefully before proceeding with your
                    payment and analysis.
                  </p>

                  <p>
                    This is a <strong>one-time login and payment session</strong>. Your access
                    is linked to your current analysis session. This system is designed this
                    way to help protect the privacy and security of your uploaded documents
                    and analysis data.
                  </p>

                  <p>
                    <strong>⚠️ Do not reload, refresh, close, or navigate away from this page
                    while your analysis is in progress.</strong>
                  </p>

                  <p>
                    Reloading or leaving the page may permanently clear your current session,
                    uploaded documents, analysis results, and other associated data. For
                    privacy and security reasons, lost session data may not be recoverable.
                  </p>

                  <p>
                    <strong>By proceeding, you acknowledge and agree to the following:</strong>
                  </p>

                  <ul>
                    <li>
                      Your payment provides access to the <strong>current analysis session only</strong>.
                    </li>

                    <li>
                      If you <strong>reload or refresh the page</strong>, your current session,
                      uploaded document, and analysis results may be lost.
                    </li>

                    <li>
                      If your session is lost because you reload or leave the page, you may
                      be required to <strong>make the payment again</strong> to start a new
                      analysis session.
                    </li>

                    <li>
                      Please download your analysis report and save any required results
                      <strong> before refreshing, closing, or leaving the page</strong>.
                    </li>

                    <li>
                      Do not use the browser's refresh button, close the tab, or navigate
                      away from the analysis page until your analysis is complete and your
                      results have been saved.
                    </li>

                    <li>
                      This session-based approach is implemented as a
                      <strong> data-privacy and security measure</strong> to minimize the
                      retention and exposure of uploaded documents and analysis data.
                    </li>
                  </ul>

                  <p>
                    <strong>By continuing with the payment and analysis, you confirm that you
                    have read, understood, and agreed to these terms.</strong>
                  </p>

                  <p className="info-box-note">
                    <strong>Important:</strong> We strongly recommend downloading your
                    analysis report immediately after your analysis is completed.
                  </p>

                  {externalError && (
                    <p className="form-error">
                      External API error: {externalError}
                    </p>
                  )}

                  {!externalError && externalSource && (
                    <p className="info-box-note">
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
        <p>© 2026 SAHFON Verify · Protecting academic integrity</p>
      </footer>
    </div>
  )
}