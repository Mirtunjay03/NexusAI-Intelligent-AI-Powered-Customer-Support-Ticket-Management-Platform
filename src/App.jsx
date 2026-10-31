import { lazy, Suspense } from 'react'
import { useCallback, useEffect, useState } from 'react'
import {
  ArrowUpRight,
  CheckCircle2,
  CircleAlert,
  Database,
  LoaderCircle,
  RefreshCw,
  Server,
  Sparkles,
} from 'lucide-react'
import { Link, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext.jsx'
import ProtectedRoute from './components/ProtectedRoute.jsx'
import AuthPage from './pages/AuthPage.jsx'
import { TicketCreatePage, TicketDetailPage, TicketListPage } from './pages/TicketsPage.jsx'
import ChatPage from './pages/ChatPage.jsx'
import KnowledgePage from './pages/KnowledgePage.jsx'
import { API_BASE_URL } from './services/api.js'

const DashboardPage = lazy(() => import('./pages/DashboardPage.jsx'))

export default function App() {
  return (
    <AuthProvider>
      <Suspense fallback={<main className="auth-loading">Loading your workspace…</main>}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/login" element={<AuthPage mode="login" />} />
          <Route path="/signup" element={<AuthPage mode="signup" />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/app" element={<RoleRedirect />} />
            <Route path="/app/admin" element={<DashboardPage role="admin" />} />
            <Route path="/app/agent" element={<DashboardPage role="agent" />} />
            <Route path="/app/customer" element={<DashboardPage role="customer" />} />
            <Route path="/app/:role/tickets" element={<TicketListPage />} />
            <Route path="/app/:role/tickets/new" element={<TicketCreatePage />} />
            <Route path="/app/:role/tickets/:ticketId" element={<TicketDetailPage />} />
            <Route path="/app/customer/chat" element={<ChatPage />} />
            <Route path="/app/admin/knowledge" element={<KnowledgePage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </AuthProvider>
  )
}

function RoleRedirect() {
  const { user } = useAuth()
  return <Navigate to={`/app/${user.role}`} replace />
}

function HomePage() {
  const { user, loading } = useAuth()
  const [health, setHealth] = useState({ state: 'loading', database: 'Checking' })

  const checkHealth = useCallback(async () => {
    setHealth({ state: 'loading', database: 'Checking' })
    try {
      const response = await fetch(`${API_BASE_URL}/api/health`)
      const result = await response.json()
      setHealth(response.ok
        ? { state: 'healthy', database: result.database || 'Connected', message: 'Your API and database connection are ready.' }
        : { state: 'degraded', database: 'Unavailable', message: 'The API is running, but MongoDB is not reachable.' })
    } catch {
      setHealth({ state: 'offline', database: 'Unknown', message: `Could not reach the API at ${API_BASE_URL}.` })
    }
  }, [])

  useEffect(() => { checkHealth() }, [checkHealth])

  const isLoading = health.state === 'loading'
  return (
    <main className="page-shell">
      <header className="topbar">
        <Link className="brand" to="/" aria-label="NexusAI home">
          <span className="brand-mark"><Sparkles size={18} strokeWidth={2.2} /></span>
          <span>Nexus<span className="brand-light">AI</span></span>
        </Link>
        <nav className="home-nav">
          {!loading && user
            ? <Link className="nav-signup" to={`/app/${user.role}`}>Open workspace <ArrowUpRight size={15} /></Link>
            : <><Link className="nav-login" to="/login">Sign in</Link><Link className="nav-signup" to="/signup">Create account <ArrowUpRight size={15} /></Link></>}
        </nav>
      </header>

      <section className="hero">
        <div className="eyebrow"><span /> CUSTOMER SUPPORT, REIMAGINED</div>
        <h1>Every conversation,<br /><span>closer to a solution.</span></h1>
        <p className="hero-copy">
          A smarter workspace for your support team. NexusAI brings customer
          conversations and intelligent assistance together.
        </p>
        <div className="hero-actions">
          <Link className="primary-button" to={user ? `/app/${user.role}` : '/signup'}>
            {user ? 'Open your workspace' : 'Get started'} <ArrowUpRight size={17} />
          </Link>
          <span className="setup-note">Support that scales with you</span>
        </div>
      </section>

      <section className="status-card" id="services" aria-live="polite">
        <div className="status-heading">
          <div><p className="section-kicker">SYSTEM STATUS</p><h2>Your support foundation</h2></div>
          <button className="refresh-button" type="button" onClick={checkHealth} disabled={isLoading}>
            <RefreshCw size={15} className={isLoading ? 'spin' : ''} /> Check again
          </button>
        </div>
        <div className="service-grid">
          <ServiceCard icon={<Server size={18} />} name="API service" detail={health.message || 'Checking backend availability'} state={health.state === 'healthy' || health.state === 'degraded' ? 'online' : health.state} />
          <ServiceCard icon={<Database size={18} />} name="MongoDB" detail={health.database} state={health.state === 'healthy' ? 'online' : health.state === 'degraded' ? 'offline' : health.state} />
        </div>
        <div className="status-foot">
          <span>Services are checked directly against your backend.</span>
          <span className="endpoint">{API_BASE_URL}/api/health</span>
        </div>
      </section>
      <footer className="footer"><span>Built for better support experiences.</span><span>NEXUSAI <span className="footer-dot">·</span> SUPPORT PLATFORM</span></footer>
    </main>
  )
}

function ServiceCard({ icon, name, detail, state }) {
  const label = { loading: 'Checking', online: 'Operational', offline: 'Unavailable', degraded: 'Degraded' }[state] || 'Unknown'
  const StatusIcon = state === 'loading' ? LoaderCircle : state === 'online' ? CheckCircle2 : CircleAlert
  return (
    <article className="service-card">
      <div className={`service-icon ${state}`}>{icon}</div>
      <div className="service-info">
        <div className="service-title"><h3>{name}</h3><span className={`service-state ${state}`}><StatusIcon size={13} className={state === 'loading' ? 'spin' : ''} />{label}</span></div>
        <p>{detail}</p>
      </div>
    </article>
  )
}
