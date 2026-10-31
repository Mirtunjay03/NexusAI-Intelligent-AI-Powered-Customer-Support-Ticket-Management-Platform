import { useState } from 'react'
import { ArrowLeft, ArrowRight, LockKeyhole, Mail, Sparkles, UserRound } from 'lucide-react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

export default function AuthPage({ mode }) {
  const isSignup = mode === 'signup'
  const { user, loading, login, register } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ name: '', email: '', password: '' })
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (!loading && user) return <Navigate to={`/app/${user.role}`} replace />

  function update(event) {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }))
    setError('')
  }

  async function submit(event) {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      if (isSignup) await register(form)
      else await login({ email: form.email, password: form.password })
      navigate('/app', { replace: true })
    } catch (requestError) {
      setError(
        requestError.status === 409
          ? 'An account with this email already exists.'
          : requestError.message,
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <header className="auth-header">
        <Link className="brand" to="/">
          <span className="brand-mark"><Sparkles size={18} /></span>
          <span>Nexus<span className="brand-light">AI</span></span>
        </Link>
        <Link className="back-link" to="/"><ArrowLeft size={15} /> Back to home</Link>
      </header>
      <section className="auth-layout">
        <div className="auth-intro">
          <div className="eyebrow"><span /> SUPPORT THAT MOVES WITH YOU</div>
          <h1>{isSignup ? <>A better way<br />to <span>help people.</span></> : <>Welcome<br /><span>back.</span></>}</h1>
          <p>
            {isSignup
              ? 'Create your workspace account and bring every customer conversation into focus.'
              : 'Sign in to pick up where your team left off and keep every conversation moving.'}
          </p>
          <div className="auth-note"><span><LockKeyhole size={15} /></span> Secure sign-in with an encrypted session</div>
        </div>
        <form className="auth-card" onSubmit={submit}>
          <div className="auth-card-heading">
            <p className="section-kicker">{isSignup ? 'GET STARTED' : 'YOUR WORKSPACE'}</p>
            <h2>{isSignup ? 'Create your account' : 'Sign in to NexusAI'}</h2>
            <p>{isSignup ? 'Join your support team on NexusAI.' : 'Enter your details to access your workspace.'}</p>
          </div>

          {isSignup && (
            <label className="form-field">
              <span>Full name</span>
              <span className="input-wrap"><UserRound size={16} /><input name="name" autoComplete="name" placeholder="Your name" value={form.name} onChange={update} minLength="2" maxLength="100" required /></span>
            </label>
          )}
          <label className="form-field">
            <span>Email address</span>
            <span className="input-wrap"><Mail size={16} /><input name="email" type="email" autoComplete="email" placeholder="you@company.com" value={form.email} onChange={update} required /></span>
          </label>
          <label className="form-field">
            <span>Password</span>
            <span className="input-wrap"><LockKeyhole size={16} /><input name="password" type="password" autoComplete={isSignup ? 'new-password' : 'current-password'} placeholder={isSignup ? 'At least 8 characters' : 'Enter your password'} value={form.password} onChange={update} minLength={isSignup ? 8 : undefined} required /></span>
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="auth-submit" type="submit" disabled={submitting}>
            {submitting ? 'Please wait…' : isSignup ? 'Create account' : 'Sign in'}
            {!submitting && <ArrowRight size={16} />}
          </button>
          <p className="auth-switch">
            {isSignup ? 'Already have an account?' : 'New to NexusAI?'}
            {' '}<Link to={isSignup ? '/login' : '/signup'}>{isSignup ? 'Sign in' : 'Create an account'}</Link>
          </p>
          {isSignup && <p className="role-notice">New accounts start with customer access. Admin and agent access is provisioned by an administrator.</p>}
        </form>
      </section>
      <footer className="auth-footer"><span>NexusAI · Thoughtful support, at every scale.</span><span>YOUR WORKSPACE, SECURED</span></footer>
    </main>
  )
}
