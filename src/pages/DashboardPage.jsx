import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ArrowRight,
  Bot,
  CheckCircle2,
  Clock3,
  Database,
  Headset,
  FileText,
  LogOut,
  RefreshCw,
  Sparkles,
  Ticket,
  Users,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { apiRequest } from '../services/api.js'
import { useAuth } from '../context/AuthContext.jsx'

const roleLabel = {
  admin: 'Administrator',
  agent: 'Support agent',
  customer: 'Customer',
}

const palette = ['#23865c', '#75b58e', '#e3b454', '#d87956', '#87968d']
const priorityColor = { critical: '#c85249', high: '#dd8c45', medium: '#e2b64e', low: '#7eb28b' }
const statusNames = {
  open: 'Open',
  in_progress: 'In progress',
  pending_customer: 'Pending customer',
  resolved: 'Resolved',
  closed: 'Closed',
}

function chartRows(values = {}) {
  return Object.entries(values).map(([name, value]) => ({
    name: statusNames[name] || name.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()),
    value,
    color: priorityColor[name],
  }))
}

function MetricCard({ icon: Icon, label, value, detail, tone = 'green' }) {
  return (
    <article className="metric-card">
      <span className={`metric-icon ${tone}`}><Icon size={17} /></span>
      <div className="metric-copy"><span>{label}</span><strong>{value ?? '—'}</strong>{detail && <small>{detail}</small>}</div>
    </article>
  )
}

function ChartCard({ title, description, children, className = '' }) {
  return <section className={`dashboard-card chart-card ${className}`}><div className="chart-heading"><div><h2>{title}</h2><p>{description}</p></div></div>{children}</section>
}

export default function DashboardPage({ role }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [logoutError, setLogoutError] = useState('')
  const [dashboard, setDashboard] = useState(null)
  const [aiStatus, setAiStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshed, setRefreshed] = useState(false)

  const loadDashboard = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await apiRequest('/api/analytics/dashboard')
      setDashboard(result)
      setRefreshed(true)
    } catch (requestError) {
      setError(requestError.message)
      setDashboard(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadDashboard() }, [loadDashboard])
  useEffect(() => {
    if (user.role !== 'customer') {
      apiRequest('/api/ai/status').then(setAiStatus).catch(() => setAiStatus({ status: 'unavailable' }))
    }
  }, [user.role])

  async function signOut() {
    try {
      await logout()
      navigate('/', { replace: true })
    } catch (requestError) {
      setLogoutError(requestError.message)
    }
  }

  const metrics = dashboard?.metrics || {}
  const distribution = useMemo(
    () => chartRows(dashboard?.status_distribution),
    [dashboard?.status_distribution],
  )
  const priorities = useMemo(
    () => chartRows(dashboard?.priority_distribution).map((row) => ({
      ...row,
      color: priorityColor[row.name.toLowerCase()],
    })),
    [dashboard?.priority_distribution],
  )
  if (user.role !== role) return <Navigate to={`/app/${user.role}`} replace />

  return (
    <main className="dashboard-page">
      <header className="dashboard-topbar">
        <Link className="brand" to="/"><span className="brand-mark"><Sparkles size={18} /></span><span>Nexus<span className="brand-light">AI</span></span></Link>
        <nav className="dashboard-top-actions">
          <Link className="dashboard-nav-link active" to={`/app/${user.role}`}><Database size={14} /> Overview</Link>
          <Link className="dashboard-nav-link" to={`/app/${user.role}/tickets`}><Ticket size={14} /> Tickets</Link>
          {user.role === 'customer' && <Link className="dashboard-nav-link" to="/app/customer/chat"><Bot size={14} /> AI help</Link>}
          {user.role === 'admin' && <Link className="dashboard-nav-link" to="/app/admin/knowledge"><FileText size={14} /> Knowledge</Link>}
          <div className="dashboard-user"><span className="avatar">{user.name.charAt(0).toUpperCase()}</span><span>{user.name}</span></div>
          <button className="signout-button" onClick={signOut} aria-label="Sign out"><LogOut size={15} /></button>
        </nav>
      </header>

      <section className="dashboard-content">
        <div className="dashboard-welcome">
          <div><p className="section-kicker">{roleLabel[user.role]?.toUpperCase()} WORKSPACE</p><h1>{user.role === 'customer' ? `Welcome, ${user.name.split(' ')[0]}` : 'Support overview'}</h1><p>{user.role === 'customer' ? 'Track your requests and stay up to date with support.' : 'A live view of support activity and workload.'}</p></div>
          <div className="dashboard-heading-actions">
            {refreshed && <span className="updated-label"><CheckCircle2 size={13} /> Live data</span>}
            <button type="button" className="refresh-button" onClick={loadDashboard} disabled={loading}><RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh</button>
            {user.role === 'customer' && <Link className="primary-button compact-button" to={`/app/${user.role}/tickets/new`}><Ticket size={14} /> New ticket</Link>}
          </div>
        </div>
        {logoutError && <div className="ticket-alert" role="alert">{logoutError}</div>}
        {error && <div className="dashboard-error" role="alert"><div><strong>Couldn’t load your dashboard</strong><span>{error}</span></div><button className="secondary-button" onClick={loadDashboard}>Retry</button></div>}
        {loading && !dashboard ? <DashboardSkeleton /> : dashboard && (
          <>
            <Metrics role={user.role} metrics={metrics} />
            {user.role === 'admin' && <AdminCharts data={dashboard} distribution={distribution} priorities={priorities} />}
            {user.role === 'agent' && <AgentCharts data={dashboard} priorities={priorities} />}
            {user.role === 'customer' && <CustomerOverview tickets={dashboard.recent_tickets} />}
            {user.role !== 'customer' && <AIReadiness status={aiStatus} />}
            <RecentTickets tickets={dashboard.recent_tickets} role={user.role} />
          </>
        )}
        {!loading && !error && !dashboard && <div className="dashboard-empty"><Database size={20} /><strong>Dashboard data is not available</strong><span>Please refresh to try again.</span></div>}
      </section>
    </main>
  )
}

function Metrics({ role, metrics }) {
  const items = role === 'admin'
    ? [
      [Ticket, 'Total tickets', metrics.total_tickets, 'All customer requests'],
      [Clock3, 'Open tickets', metrics.open_tickets, 'Open or in progress', 'amber'],
      [CheckCircle2, 'Resolved', metrics.resolved_tickets, 'Resolved or closed'],
      [Ticket, 'Critical priority', metrics.critical_tickets, 'Needs close attention', 'red'],
      [Users, 'Customers', metrics.total_customers, 'Active accounts', 'blue'],
      [Headset, 'Support agents', metrics.total_agents, 'Active agents', 'blue'],
      [Clock3, 'Avg. resolution', metrics.average_resolution_hours == null ? '—' : `${metrics.average_resolution_hours}h`, 'Resolved tickets only', 'purple'],
    ]
    : role === 'agent'
      ? [
        [Ticket, 'Assigned to you', metrics.assigned_tickets, 'Your current workload'],
        [Ticket, 'Unassigned', metrics.unassigned_tickets, 'Available to claim', 'amber'],
        [Clock3, 'Open tickets', metrics.open_tickets, 'Assigned and in progress'],
        [Users, 'Pending customer', metrics.pending_customer, 'Waiting on a reply', 'amber'],
        [CheckCircle2, 'Resolved', metrics.resolved_tickets, 'Resolved or closed'],
      ]
      : [
        [Ticket, 'Your tickets', metrics.total_tickets, 'Requests you created'],
        [Clock3, 'Open', metrics.open_tickets, 'Awaiting resolution', 'amber'],
        [CheckCircle2, 'Resolved', metrics.resolved_tickets, 'Resolved or closed'],
      ]
  return <div className={`metrics-grid metrics-${role}`}>{items.map(([icon, label, value, detail, tone]) => <MetricCard key={label} icon={icon} label={label} value={value} detail={detail} tone={tone} />)}</div>
}

function AdminCharts({ data, distribution, priorities }) {
  const workload = data.agent_workload || []
  return (
    <div className="charts-grid">
      <ChartCard title="Ticket activity" description="New tickets over the last 14 days" className="wide-chart">
        <div className="chart-area">
          {data.ticket_trends?.some((point) => point.count > 0)
            ? <ResponsiveContainer width="100%" height="100%"><LineChart data={data.ticket_trends} margin={{ top: 10, right: 10, left: -18, bottom: 0 }}><CartesianGrid stroke="#eef2ef" vertical={false} /><XAxis dataKey="date" tickFormatter={(value) => value.slice(5)} tickLine={false} axisLine={false} tick={{ fontSize: 9, fill: '#8b968f' }} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fontSize: 9, fill: '#8b968f' }} /><Tooltip /><Line type="monotone" dataKey="count" name="Tickets" stroke="#23865c" strokeWidth={2.5} dot={{ r: 3, fill: '#23865c' }} activeDot={{ r: 5 }} /></LineChart></ResponsiveContainer>
            : <ChartEmpty>No tickets were created during this period.</ChartEmpty>}
        </div>
      </ChartCard>
      <DistributionChart title="By status" data={distribution} />
      <DistributionChart title="By priority" data={priorities} />
      <ChartCard title="Agent workload" description="Tickets assigned per active agent" className="wide-chart">
        <div className="chart-area">
          {workload.length
            ? <ResponsiveContainer width="100%" height="100%"><BarChart data={workload} margin={{ top: 10, right: 10, left: -18, bottom: 0 }}><CartesianGrid stroke="#eef2ef" vertical={false} /><XAxis dataKey="agent_name" tickLine={false} axisLine={false} tick={{ fontSize: 9, fill: '#718078' }} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fontSize: 9, fill: '#8b968f' }} /><Tooltip /><Legend wrapperStyle={{ fontSize: 10 }} /><Bar dataKey="ticket_count" name="Assigned" fill="#75b58e" radius={[4, 4, 0, 0]} /><Bar dataKey="open_count" name="Open" fill="#23865c" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer>
            : <ChartEmpty>No assigned tickets yet.</ChartEmpty>}
        </div>
      </ChartCard>
    </div>
  )
}

function DistributionChart({ title, data }) {
  const total = data.reduce((sum, item) => sum + item.value, 0)
  return (
    <ChartCard title={title} description="Current ticket distribution">
      <div className="donut-wrap">
        {total
          ? <><div className="donut-chart"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={data} dataKey="value" nameKey="name" innerRadius="65%" outerRadius="92%" paddingAngle={2}>{data.map((item, index) => <Cell key={item.name} fill={item.color || palette[index % palette.length]} stroke="none" />)}</Pie><Tooltip /></PieChart></ResponsiveContainer><div className="donut-total"><strong>{total}</strong><span>tickets</span></div></div><div className="legend-list">{data.map((item, index) => <div key={item.name}><span style={{ background: item.color || palette[index % palette.length] }} /><span>{item.name}</span><strong>{item.value}</strong></div>)}</div></>
          : <ChartEmpty>No ticket data yet.</ChartEmpty>}
      </div>
    </ChartCard>
  )
}

function AgentCharts({ data, priorities }) {
  return (
    <div className="charts-grid agent-charts">
      <DistributionChart title="Priority mix" data={priorities} />
      <ChartCard title="Your workload" description={`${data.workload?.assigned_ticket_count || 0} assigned of ${data.workload?.visible_ticket_count || 0} available tickets`}>
        <div className="workload-summary"><strong>{data.metrics?.assigned_tickets || 0}</strong><span>tickets assigned to you</span><div className="workload-track"><span style={{ width: `${data.workload?.visible_ticket_count ? Math.min(100, data.workload.assigned_ticket_count / data.workload.visible_ticket_count * 100) : 0}%` }} /></div><small>Workload reflects tickets you are assigned to resolve.</small></div>
      </ChartCard>
    </div>
  )
}

function CustomerOverview({ tickets }) {
  return (
    <div className="dashboard-card customer-overview">
      <div className="customer-overview-copy"><span className="metric-icon green"><Headset size={17} /></span><div><h2>Need a hand?</h2><p>Our team is here to help. Create a request and track replies from your workspace.</p></div></div>
      <div className="customer-actions"><Link to="/app/customer/tickets/new" className="secondary-button">Create a support request <ArrowRight size={14} /></Link><Link to="/app/customer/chat" className="secondary-button"><Bot size={14} /> Ask AI assistant</Link></div>
      <div className="customer-latest">
        <p className="section-kicker">LATEST UPDATE</p>
        {tickets?.length
          ? <div className="latest-update"><strong>{tickets[0].ticket_number} · {tickets[0].subject}</strong><span>Status: {statusNames[tickets[0].status] || tickets[0].status} · Updated {new Date(tickets[0].updated_at).toLocaleString()}</span></div>
          : <div className="latest-update muted">Your latest ticket update will appear here.</div>}
      </div>
      <Link className="assistant-teaser" to="/app/customer/chat"><Bot size={16} /><span><strong>AI support assistant</strong><small>Ask a question or create a ticket for human support.</small></span><span className="coming-chip">Open chat <ArrowRight size={11} /></span></Link>
    </div>
  )
}

function AIReadiness({ status }) {
  const configured = status?.status === 'ready'
  return (
    <div className={`ai-readiness ${configured ? 'configured' : ''}`}>
      <span className="ai-readiness-icon"><Bot size={16} /></span>
      <div><strong>AI ticket intelligence</strong><span>{configured ? `Connected to ${status.model}. Classification, drafts, and summaries are available.` : 'Not configured. Set LLM_API_BASE_URL, LLM_API_KEY, and LLM_MODEL to enable AI tools.'}</span></div>
      <span className="ai-availability">{configured ? 'Ready' : 'Setup required'}</span>
    </div>
  )
}

function RecentTickets({ tickets, role }) {
  return (
    <section className="dashboard-card recent-tickets-card">
      <div className="recent-heading"><div><p className="section-kicker">LATEST ACTIVITY</p><h2>{role === 'customer' ? 'Recent tickets' : 'Recently updated tickets'}</h2></div><Link to={`/app/${role}/tickets`} className="text-link">View all <ArrowRight size={13} /></Link></div>
      {!tickets?.length
        ? <div className="dashboard-empty small-empty"><Ticket size={18} /><strong>No tickets to show yet</strong><span>Ticket updates will appear here when available.</span></div>
        : <div className="recent-ticket-list">{tickets.map((ticket) => <Link className="recent-ticket-row" to={`/app/${role}/tickets/${ticket.id}`} key={ticket.id}><span className="recent-ticket-icon"><Ticket size={15} /></span><span className="recent-ticket-copy"><strong>{ticket.ticket_number} · {ticket.subject}</strong><small>{role === 'customer' ? `Updated ${new Date(ticket.updated_at).toLocaleString()}` : `${ticket.customer_name} · ${new Date(ticket.updated_at).toLocaleString()}`}</small></span><span className={`ticket-status status-${ticket.status}`}>{statusNames[ticket.status] || ticket.status}</span><ArrowRight size={14} className="recent-arrow" /></Link>)}</div>}
    </section>
  )
}

function ChartEmpty({ children }) {
  return <div className="chart-empty">{children}</div>
}

function DashboardSkeleton() {
  return <div className="dashboard-skeleton" aria-label="Loading dashboard"><div className="skeleton-metrics">{[1, 2, 3, 4].map((item) => <span key={item} />)}</div><span className="skeleton-chart" /><span className="skeleton-chart" /></div>
}
