import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, Bot, FileText, Headset, LoaderCircle, Plus, Send, Sparkles, Ticket, Trash2 } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { apiRequest } from '../services/api.js'
import { useAuth } from '../context/AuthContext.jsx'

const suggestions = [
  'How can I get help with my account?',
  'What information should I include in a support request?',
  'Can you check the status of my ticket?',
]

export default function ChatPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [escalating, setEscalating] = useState(false)
  const [aiAvailable, setAiAvailable] = useState(true)
  const [needsHuman, setNeedsHuman] = useState(false)
  const [sourceMode, setSourceMode] = useState('keyword_fallback')
  const [error, setError] = useState('')
  const scrollRef = useRef(null)
  const inputRef = useRef(null)

  const loadHistory = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await apiRequest('/api/ai/chat')
      setMessages(result.messages)
      setAiAvailable(result.ai_available)
      setNeedsHuman(result.needs_human)
      setSourceMode(result.source_mode)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadHistory() }, [loadHistory])
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, sending])

  async function sendMessage(event) {
    event.preventDefault()
    const content = input.trim()
    if (!content || sending) return
    setSending(true)
    setError('')
    setInput('')
    const optimistic = [...messages, { role: 'user', content, created_at: new Date().toISOString(), pending: true }]
    setMessages(optimistic)
    try {
      const result = await apiRequest('/api/ai/chat', {
        method: 'POST',
        body: JSON.stringify({ content }),
      })
      setMessages(result.messages)
      setNeedsHuman(result.needs_human)
      setAiAvailable(result.ai_available)
      setSourceMode(result.source_mode)
    } catch (requestError) {
      setMessages(messages)
      setInput(content)
      setError(requestError.message)
    } finally {
      setSending(false)
      inputRef.current?.focus()
    }
  }

  async function clearConversation() {
    if (!window.confirm('Clear your AI assistant conversation?')) return
    setError('')
    try {
      await apiRequest('/api/ai/chat', { method: 'DELETE' })
      setMessages([])
      setNeedsHuman(false)
    } catch (requestError) {
      setError(requestError.message)
    }
  }

  async function createHumanTicket() {
    setEscalating(true)
    setError('')
    try {
      const result = await apiRequest('/api/ai/chat/escalate', { method: 'POST', body: JSON.stringify({}) })
      navigate(`/app/customer/tickets/${result.ticket.id}`)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setEscalating(false)
    }
  }

  return (
    <main className="chat-page">
      <header className="chat-topbar">
        <Link className="brand" to="/app/customer"><span className="brand-mark"><Sparkles size={17} /></span><span>Nexus<span className="brand-light">AI</span></span></Link>
        <Link className="back-link" to="/app/customer"><ArrowLeft size={14} /> Workspace</Link>
      </header>
      <section className="chat-layout">
        <aside className="chat-side">
          <div className="chat-bot-mark"><Bot size={23} /></div>
          <p className="section-kicker">CUSTOMER SUPPORT</p>
          <h1>How can I<br /><span>help today?</span></h1>
          <p className="chat-side-copy">Ask a question about company policies and support. Answers are grounded in active knowledge sources; if evidence is missing, we’ll connect you with a person.</p>
          <div className="chat-privacy-note"><Headset size={15} /><span>Your chat is private to your account.</span></div>
          <Link className="secondary-button chat-ticket-link" to="/app/customer/tickets"><Ticket size={14} /> View your tickets</Link>
        </aside>
        <section className="chat-card" aria-label="NexusAI customer support assistant">
          <div className="chat-card-head">
            <div className="chat-agent-avatar"><Bot size={17} /></div>
            <div><strong>NexusAI Support Assistant</strong><span><i className={aiAvailable ? 'availability-dot' : 'availability-dot unavailable'} />{aiAvailable ? 'AI assistant available' : 'AI assistant not configured'}</span><small className="chat-search-mode">{sourceMode === 'vector' ? 'Atlas Vector Search' : 'Keyword fallback · not semantic'}</small></div>
            <button type="button" className="chat-clear-button" onClick={clearConversation} disabled={!messages.length || sending} aria-label="Clear conversation"><Trash2 size={15} /></button>
          </div>
          <div className="chat-messages">
            {loading ? <div className="chat-loading"><LoaderCircle size={16} className="spin" /> Loading your conversation…</div> : (
              <>
                {messages.length === 0 && <div className="chat-welcome">
                  <span className="welcome-icon"><Sparkles size={17} /></span>
                  <strong>Hi {user.name.split(' ')[0]}, what can I help with?</strong>
                  <p>I’ll look for supporting information in the company knowledge base. I can’t view your account or perform actions; if I can’t find a reliable answer, I’ll offer human support.</p>
                  <div className="suggested-questions">{suggestions.map((question) => <button key={question} type="button" disabled={!aiAvailable} onClick={() => { setInput(question); inputRef.current?.focus() }}>{question}</button>)}</div>
                </div>}
                {messages.map((item, index) => (
                  <article className={`chat-message ${item.role === 'user' ? 'customer-chat-message' : 'assistant-chat-message'}`} key={`${item.created_at}-${index}`}>
                    {item.role === 'assistant' && <span className="chat-message-avatar"><Bot size={13} /></span>}
                    <div className="chat-bubble">
                      <span className="chat-message-label">{item.role === 'assistant' ? 'AI assistant' : 'You'}{item.pending ? ' · sending' : ''}</span>
                      <p>{item.content}</p>
                      {item.role === 'assistant' && item.sources?.length > 0 && <div className="chat-source-list"><strong>Sources</strong>{item.sources.map((source) => <span key={source.chunk_id}><FileText size={11} /> {source.filename}{source.page_number ? ` · page ${source.page_number}` : ''}</span>)}</div>}
                      <time>{new Date(item.created_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</time>
                    </div>
                  </article>
                ))}
                {sending && <div className="typing-indicator"><span /><span /><span /> Assistant is thinking</div>}
                <div ref={scrollRef} />
              </>
            )}
          </div>
          {error && <div className="chat-error" role="alert">{error}</div>}
          {(!aiAvailable || needsHuman) && <div className="chat-escalation">
            <div><Headset size={15} /><span><strong>{needsHuman ? 'Would you like a human to follow up?' : 'AI chat is not configured.'}</strong><small>{needsHuman ? 'Create a ticket with your questions so our team can help.' : 'You can still create a support ticket for our team.'}</small></span></div>
            <button className="secondary-button" type="button" onClick={createHumanTicket} disabled={escalating || messages.length === 0}>{escalating ? 'Creating…' : 'Create support ticket'} <ArrowRight size={13} /></button>
          </div>}
          <form className="chat-compose" onSubmit={sendMessage}>
            <label htmlFor="chat-input" className="sr-only">Your support question</label>
            <textarea id="chat-input" ref={inputRef} rows="2" maxLength="2000" placeholder={aiAvailable ? 'Write your question…' : 'AI chat is unavailable. Create a support ticket instead.'} value={input} onChange={(event) => setInput(event.target.value)} disabled={!aiAvailable || sending} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form.requestSubmit() } }} />
            <div className="chat-compose-foot"><span>AI may be inaccurate. Don’t include passwords or sensitive information.</span><button type="submit" className="chat-send-button" disabled={!input.trim() || sending || !aiAvailable} aria-label="Send message">{sending ? <LoaderCircle size={15} className="spin" /> : <Send size={15} />}</button></div>
          </form>
          <p className="chat-honesty-note">{sourceMode === 'vector' ? 'Answers use Atlas Vector Search.' : 'Keyword fallback is active (not semantic search). Company knowledge is used when matching sources are found; account-specific requests require a support agent.'}</p>
        </section>
      </section>
    </main>
  )
}
