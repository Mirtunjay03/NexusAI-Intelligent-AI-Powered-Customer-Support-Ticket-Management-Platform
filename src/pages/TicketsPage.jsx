import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft, ArrowRight, Bot, Clock3, Plus, Search, Ticket, UserRound } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { apiRequest } from '../services/api.js'
import { useAuth } from '../context/AuthContext.jsx'

const statuses = [
  ['open', 'Open'],
  ['in_progress', 'In progress'],
  ['pending_customer', 'Pending customer'],
  ['resolved', 'Resolved'],
  ['closed', 'Closed'],
]

const priorities = [
  ['low', 'Low'],
  ['medium', 'Medium'],
  ['high', 'High'],
  ['critical', 'Critical'],
]

const categories = [
  ['technical_issue', 'Technical issue'],
  ['billing', 'Billing'],
  ['account', 'Account'],
  ['product_inquiry', 'Product inquiry'],
  ['general_support', 'General support'],
]

function humanize(value = '') {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function TicketsLayout({ title, children, action }) {
  const { role } = useParams()
  return (
    <main className="workspace-page">
      <header className="topbar ticket-topbar">
        <Link className="brand" to={`/app/${role}`}><span className="brand-mark"><Ticket size={17} /></span><span>Nexus<span className="brand-light">AI</span></span></Link>
        <div className="ticket-header-actions">
          <Link className="back-link" to={`/app/${role}`}><ArrowLeft size={14} /> Workspace</Link>
          {action}
        </div>
      </header>
      <section className="ticket-content">
        <div className="ticket-page-heading"><div><p className="section-kicker">SUPPORT WORKSPACE</p><h1>{title}</h1></div></div>
        {children}
      </section>
    </main>
  )
}

export function TicketListPage() {
  const { role } = useParams()
  const { user } = useAuth()
  const isCustomer = role === 'customer'
  const [tickets, setTickets] = useState([])
  const [agents, setAgents] = useState([])
  const [total, setTotal] = useState(0)
  const [skip, setSkip] = useState(0)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [priority, setPriority] = useState('')
  const [category, setCategory] = useState('')
  const [agentId, setAgentId] = useState('')
  const [createdFrom, setCreatedFrom] = useState('')
  const [createdTo, setCreatedTo] = useState('')
  const [sortOrder, setSortOrder] = useState('desc')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const limit = 10

  const loadTickets = useCallback(async () => {
    setLoading(true)
    setError('')
    const params = new URLSearchParams({ skip: String(skip), limit: String(limit), sort_by: 'created_at', sort_order: 'desc' })
    if (search.trim()) params.set('search', search.trim())
    if (status) params.set('status', status)
    if (priority) params.set('priority', priority)
    if (category) params.set('category', category)
    if (agentId) params.set('agent_id', agentId)
    if (createdFrom) params.set('created_from', `${createdFrom}T00:00:00.000Z`)
    if (createdTo) params.set('created_to', `${createdTo}T23:59:59.999Z`)
    params.set('sort_order', sortOrder)
    try {
      const result = await apiRequest(`/api/tickets?${params}`)
      setTickets(result.items)
      setTotal(result.total)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }, [skip, search, status, priority, category, agentId, createdFrom, createdTo, sortOrder])

  useEffect(() => { loadTickets() }, [loadTickets])
  useEffect(() => {
    if (user.role === 'admin' || user.role === 'agent') {
      apiRequest('/api/tickets/agents').then(setAgents).catch((requestError) => setError(requestError.message))
    }
  }, [user.role])
  const action = isCustomer
    ? <Link className="primary-button compact-button" to={`/app/${role}/tickets/new`}><Plus size={15} /> New ticket</Link>
    : null

  return (
    <TicketsLayout title={isCustomer ? 'Your support requests' : 'Ticket queue'} action={action}>
      <div className="ticket-toolbar">
        <label className="ticket-search"><Search size={16} /><input value={search} onChange={(event) => { setSearch(event.target.value); setSkip(0) }} placeholder="Search subject or ticket number" /></label>
        <select aria-label="Filter by status" value={status} onChange={(event) => { setStatus(event.target.value); setSkip(0) }}>
          <option value="">All statuses</option>{statuses.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <select aria-label="Filter by priority" value={priority} onChange={(event) => { setPriority(event.target.value); setSkip(0) }}>
          <option value="">All priorities</option>{priorities.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <select aria-label="Filter by category" value={category} onChange={(event) => { setCategory(event.target.value); setSkip(0) }}>
          <option value="">All categories</option>{categories.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        {!isCustomer && <select aria-label="Filter by assigned agent" value={agentId} onChange={(event) => { setAgentId(event.target.value); setSkip(0) }}>
          <option value="">All eligible tickets</option><option value="unassigned">Unassigned</option>{agents.map((agent) => <option value={agent.id} key={agent.id}>{agent.name}</option>)}
        </select>}
        <label className="date-filter">From <input aria-label="Created from" type="date" value={createdFrom} onChange={(event) => { setCreatedFrom(event.target.value); setSkip(0) }} /></label>
        <label className="date-filter">To <input aria-label="Created to" type="date" value={createdTo} onChange={(event) => { setCreatedTo(event.target.value); setSkip(0) }} /></label>
        <select aria-label="Sort order" value={sortOrder} onChange={(event) => setSortOrder(event.target.value)}>
          <option value="desc">Newest first</option><option value="asc">Oldest first</option>
        </select>
      </div>
      {error && <div className="ticket-alert" role="alert">{error}</div>}
      {loading ? <div className="ticket-empty">Loading tickets…</div> : tickets.length === 0 ? (
        <div className="ticket-empty"><span className="empty-icon"><Ticket size={20} /></span><strong>{isCustomer ? 'No support requests yet' : 'No tickets match these filters'}</strong><span>{isCustomer ? 'Create a ticket and our support team will get back to you.' : 'Try adjusting your search or filters.'}</span></div>
      ) : (
        <div className="ticket-list">
          {tickets.map((ticket) => (
            <Link className="ticket-row" key={ticket.id} to={`/app/${role}/tickets/${ticket.id}`}>
              <div className="ticket-row-top"><span className="ticket-number">{ticket.ticket_number}</span><span className={`ticket-status status-${ticket.status}`}>{humanize(ticket.status)}</span></div>
              <h2>{ticket.subject}</h2>
              <p>{ticket.description}</p>
              <div className="ticket-row-meta">
                <span>{humanize(ticket.category)}</span><span className={`ticket-priority priority-${ticket.priority}`}>{humanize(ticket.priority)}</span>
                {!isCustomer && <span><UserRound size={13} /> {ticket.assigned_agent_name || 'Unassigned'}</span>}
                <span><Clock3 size={13} /> {new Date(ticket.created_at).toLocaleDateString()}</span>
              </div>
              {ticket.tags.length > 0 && <div className="ticket-tags">{ticket.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>}
            </Link>
          ))}
        </div>
      )}
      <div className="ticket-pagination">
        <span>{total ? `${skip + 1}–${Math.min(skip + limit, total)} of ${total} tickets` : '0 tickets'}</span>
        <div>
          <button type="button" disabled={skip === 0 || loading} onClick={() => setSkip(Math.max(0, skip - limit))}><ArrowLeft size={14} /> Previous</button>
          <button type="button" disabled={skip + limit >= total || loading} onClick={() => setSkip(skip + limit)}>Next <ArrowRight size={14} /></button>
        </div>
      </div>
    </TicketsLayout>
  )
}

export function TicketCreatePage() {
  const { role } = useParams()
  const navigate = useNavigate()
  const [form, setForm] = useState({ subject: '', description: '', category: 'general_support', priority: 'medium', tags: '' })
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      const ticket = await apiRequest('/api/tickets', {
        method: 'POST',
        body: JSON.stringify({ ...form, tags: form.tags.split(',').map((tag) => tag.trim()).filter(Boolean) }),
      })
      navigate(`/app/${role}/tickets/${ticket.id}`)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <TicketsLayout title="Create a support ticket">
      <form className="ticket-form" onSubmit={submit}>
        <p>Tell us what’s going on. Your request will be saved to your support workspace.</p>
        <label className="ticket-field"><span>Subject</span><input required minLength="4" maxLength="160" placeholder="A short summary of the issue" value={form.subject} onChange={(event) => setForm({ ...form, subject: event.target.value })} /></label>
        <label className="ticket-field"><span>Description</span><textarea required minLength="10" maxLength="10000" rows="6" placeholder="Include any details that will help our team investigate…" value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
        <div className="ticket-fields-grid">
          <label className="ticket-field"><span>Category</span><select value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })}>{categories.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="ticket-field"><span>Priority</span><select value={form.priority} onChange={(event) => setForm({ ...form, priority: event.target.value })}>{priorities.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        </div>
        <label className="ticket-field"><span>Tags <small>Optional, separated by commas</small></span><input maxLength="320" placeholder="login, account access" value={form.tags} onChange={(event) => setForm({ ...form, tags: event.target.value })} /></label>
        {error && <div className="ticket-alert" role="alert">{error}</div>}
        <div className="ticket-form-actions"><Link className="secondary-button" to={`/app/${role}/tickets`}>Cancel</Link><button className="primary-button" disabled={saving}>{saving ? 'Submitting…' : 'Submit ticket'} <ArrowRight size={15} /></button></div>
      </form>
    </TicketsLayout>
  )
}

export function TicketDetailPage() {
  const { role, ticketId } = useParams()
  const { user } = useAuth()
  const [ticket, setTicket] = useState(null)
  const [threadMessages, setThreadMessages] = useState([])
  const [threadTotal, setThreadTotal] = useState(0)
  const [agents, setAgents] = useState([])
  const [history, setHistory] = useState([])
  const [aiSummary, setAiSummary] = useState(null)
  const [aiLoading, setAiLoading] = useState('')
  const [aiDraft, setAiDraft] = useState('')
  const [draftCopied, setDraftCopied] = useState(false)
  const [message, setMessage] = useState('')
  const [isInternal, setIsInternal] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const isStaff = user.role === 'admin' || user.role === 'agent'

  const loadTicket = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [ticketResult, historyResult, messagePage] = await Promise.all([
        apiRequest(`/api/tickets/${ticketId}`),
        apiRequest(`/api/tickets/${ticketId}/history`),
        apiRequest(`/api/tickets/${ticketId}/messages?skip=0&limit=50`),
      ])
      setTicket(ticketResult)
      setHistory(historyResult)
      setThreadMessages(messagePage.items)
      setThreadTotal(messagePage.total)
      if (isStaff) {
        const availableAgents = await apiRequest('/api/tickets/agents')
        setAgents(availableAgents)
      }
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }, [ticketId, isStaff])

  useEffect(() => { loadTicket() }, [loadTicket])

  async function updateTicket(path, body) {
    setError('')
    try {
      const updated = await apiRequest(`/api/tickets/${ticketId}${path}`, { method: 'PATCH', body: JSON.stringify(body) })
      setTicket(updated)
      const events = await apiRequest(`/api/tickets/${ticketId}/history`)
      setHistory(events)
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  async function loadEarlierMessages() {
    try {
      const page = await apiRequest(`/api/tickets/${ticketId}/messages?skip=${threadMessages.length}&limit=50`)
      setThreadMessages((current) => [...page.items, ...current])
      setThreadTotal(page.total)
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  async function generateSuggestion() {
    setAiLoading('suggestion')
    setError('')
    try {
      const result = await apiRequest(`/api/ai/tickets/${ticketId}/suggest-response`, { method: 'POST' })
      setAiDraft(result.suggestion)
      setDraftCopied(false)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setAiLoading('')
    }
  }

  async function generateSummary() {
    setAiLoading('summary')
    setError('')
    try {
      setAiSummary(await apiRequest(`/api/ai/tickets/${ticketId}/summarize`, { method: 'POST' }))
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setAiLoading('')
    }
  }

  function copyDraftToReply() {
    setMessage(aiDraft)
    setIsInternal(false)
    setDraftCopied(true)
    document.getElementById('ticket-reply-editor')?.focus()
  }

  async function sendMessage(event) {
    event.preventDefault()
    if (!message.trim()) return
    setSending(true)
    setError('')
    try {
      const updated = await apiRequest(`/api/tickets/${ticketId}/${isInternal ? 'internal-notes' : 'messages'}`, {
        method: 'POST',
        body: JSON.stringify({ content: message }),
      })
      setTicket(updated)
      const [messagePage, events] = await Promise.all([
        apiRequest(`/api/tickets/${ticketId}/messages?skip=0&limit=50`),
        apiRequest(`/api/tickets/${ticketId}/history`),
      ])
      setThreadMessages(messagePage.items)
      setThreadTotal(messagePage.total)
      setMessage('')
      setHistory(events)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setSending(false)
    }
  }

  if (loading) return <TicketsLayout title="Ticket details"><div className="ticket-empty">Loading ticket…</div></TicketsLayout>
  if (error && !ticket) return <TicketsLayout title="Ticket details"><div className="ticket-alert" role="alert">{error}</div><Link className="secondary-button" to={`/app/${role}/tickets`}>Back to tickets</Link></TicketsLayout>
  if (!ticket) return null

  return (
    <TicketsLayout title={ticket.subject}>
      <Link className="ticket-back-link" to={`/app/${role}/tickets`}><ArrowLeft size={14} /> All tickets</Link>
      {error && <div className="ticket-alert" role="alert">{error}</div>}
      <div className="ticket-detail-grid">
        <section className="ticket-main-column">
          <article className="ticket-detail-card">
            <div className="ticket-row-top"><span className="ticket-number">{ticket.ticket_number}</span><span className={`ticket-status status-${ticket.status}`}>{humanize(ticket.status)}</span></div>
            <p className="ticket-description">{ticket.description}</p>
            <div className="ticket-row-meta"><span>{humanize(ticket.category)}</span><span className={`ticket-priority priority-${ticket.priority}`}>{humanize(ticket.priority)}</span><span>Opened {new Date(ticket.created_at).toLocaleString()}</span></div>
            {ticket.ai_classification && <div className={`classification-panel ${ticket.ai_classification.status === 'complete' ? 'classification-complete' : ''}`}><Bot size={15} /><div><strong>AI classification · {ticket.ai_classification.status === 'complete' ? 'Ready' : 'Pending'}</strong>{ticket.ai_classification.status === 'complete' && <span>{humanize(ticket.ai_classification.category)} · {humanize(ticket.ai_classification.priority)} · {Math.round(ticket.ai_classification.confidence * 100)}% confidence</span>}{ticket.ai_classification.status !== 'complete' && <span>Classification is pending until an LLM provider is configured.</span>}</div></div>}
          </article>
          {isStaff && <section className="conversation-card ai-tools-card"><div className="conversation-heading"><div><p className="section-kicker">AI ASSISTANCE</p><h2>Agent tools</h2></div><Bot size={17} /></div><p className="ai-human-review-note">AI content is a draft only. Review and edit it before sending; nothing is sent automatically.</p><div className="ai-tool-buttons"><button className="secondary-button" type="button" onClick={generateSuggestion} disabled={Boolean(aiLoading)}>{aiLoading === 'suggestion' ? 'Drafting…' : aiDraft ? 'Regenerate draft' : 'Generate reply draft'}</button><button className="secondary-button" type="button" onClick={generateSummary} disabled={Boolean(aiLoading)}>{aiLoading === 'summary' ? 'Summarizing…' : 'Summarize ticket'}</button></div>{aiDraft && <div className="ai-draft-preview"><div><Bot size={13} /><strong>AI-generated draft · review before sending</strong></div><p>{aiDraft}</p><button className="secondary-button" type="button" onClick={copyDraftToReply}>{draftCopied ? 'Copied to reply editor' : 'Copy draft to reply editor'} <ArrowRight size={13} /></button></div>}{aiSummary && <div className="ai-summary"><span className="ai-generated-label"><Bot size={12} /> AI-generated summary · verify details</span><strong>Main issue</strong><p>{aiSummary.main_issue}</p><strong>Steps attempted</strong>{aiSummary.steps_attempted.length ? <ul>{aiSummary.steps_attempted.map((step, index) => <li key={`${index}-${step}`}>{step}</li>)}</ul> : <p>No steps recorded.</p>}<strong>Current status</strong><p>{aiSummary.current_status}</p><strong>Recommended next action</strong><p>{aiSummary.recommended_next_action}</p></div>}</section>}
          <section className="conversation-card">
            <div className="conversation-heading"><div><p className="section-kicker">CONVERSATION</p><h2>Messages</h2></div><span>{threadMessages.length} of {threadTotal} messages</span></div>
            <div className="message-list">
              {threadMessages.length === 0 && <div className="ticket-empty compact-empty">No replies yet. Send a message to start the conversation.</div>}
              {threadTotal > threadMessages.length && <button className="load-earlier-button" type="button" onClick={loadEarlierMessages}>Load earlier messages</button>}
              {threadMessages.map((item) => (
                <article className={`message-bubble ${item.is_internal ? 'internal-message' : ''}`} key={item.id}>
                  <div className="message-meta"><strong>{item.sender_name}</strong><span>{item.is_internal ? 'Internal note' : humanize(item.sender_role)}</span><time>{new Date(item.created_at).toLocaleString()}</time></div>
                  <p>{item.content}</p>
                </article>
              ))}
            </div>
            <form className="reply-form" onSubmit={sendMessage}>
              {isStaff && <label className="internal-toggle"><input type="checkbox" checked={isInternal} onChange={(event) => setIsInternal(event.target.checked)} /> Add internal note <span>Only staff can see notes</span></label>}
              <textarea id="ticket-reply-editor" rows="3" maxLength="10000" placeholder={isInternal ? 'Write a private note for the support team…' : 'Write a reply…'} value={message} onChange={(event) => setMessage(event.target.value)} />
              <div className="reply-actions"><span>{isInternal ? 'Private to staff' : 'Visible to the customer'}</span><button className="primary-button compact-button" disabled={sending || !message.trim()}>{sending ? 'Sending…' : isInternal ? 'Add note' : 'Send reply'} <ArrowRight size={14} /></button></div>
            </form>
          </section>
          <section className="conversation-card history-card"><div className="conversation-heading"><div><p className="section-kicker">AUDIT TRAIL</p><h2>Ticket history</h2></div></div>
            {history.map((event) => <div className="history-row" key={event.id}><span className="history-dot" /><div><strong>{humanize(event.action.replaceAll('_', ' '))}</strong><span>{event.actor_name} · {new Date(event.created_at).toLocaleString()}</span></div></div>)}
          </section>
        </section>
        <aside className="ticket-sidebar">
          <section className="ticket-detail-card"><p className="section-kicker">TICKET DETAILS</p>
            <dl className="detail-list"><div><dt>Customer</dt><dd>{ticket.customer_name}</dd></div><div><dt>Status</dt><dd>{humanize(ticket.status)}</dd></div><div><dt>Priority</dt><dd>{humanize(ticket.priority)}</dd></div><div><dt>Assigned to</dt><dd>{ticket.assigned_agent_name || 'Unassigned'}</dd></div></dl>
          </section>
          {isStaff && <section className="ticket-detail-card staff-controls"><p className="section-kicker">STAFF ACTIONS</p>
            <label className="ticket-field"><span>Status</span><select value={ticket.status} onChange={(event) => updateTicket('/status', { status: event.target.value })}>{statuses.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
            <label className="ticket-field"><span>Priority</span><select value={ticket.priority} onChange={(event) => updateTicket('', { priority: event.target.value })}>{priorities.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
            <label className="ticket-field"><span>Assign agent</span><select value={ticket.assigned_agent_id || ''} onChange={(event) => updateTicket('/assign', { agent_id: event.target.value || null })}><option value="">Unassigned</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}{agent.id === user.id ? ' (you)' : ''}</option>)}</select></label>
          </section>}
          {ticket.tags.length > 0 && <section className="ticket-detail-card"><p className="section-kicker">TAGS</p><div className="ticket-tags">{ticket.tags.map((tag) => <span key={tag}>{tag}</span>)}</div></section>}
        </aside>
      </div>
    </TicketsLayout>
  )
}
