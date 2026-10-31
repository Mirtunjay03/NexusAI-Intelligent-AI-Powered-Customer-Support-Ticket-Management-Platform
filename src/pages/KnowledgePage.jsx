import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowLeft, BookOpen, FileText, LoaderCircle, Plus, RefreshCw, Search, Trash2, Upload } from 'lucide-react'
import { Link, Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { apiRequest } from '../services/api.js'

export default function KnowledgePage() {
  const { user } = useAuth()
  const [documents, setDocuments] = useState([])
  const [includeInactive, setIncludeInactive] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [file, setFile] = useState(null)
  const pdfFormRef = useRef(null)
  const [article, setArticle] = useState({ title: '', content: '' })
  const [query, setQuery] = useState('')
  const [searchMode, setSearchMode] = useState('')
  const [results, setResults] = useState([])

  const loadDocuments = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ include_inactive: String(includeInactive) })
      const result = await apiRequest(`/api/knowledge?${params}`)
      setDocuments(result.items)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setLoading(false)
    }
  }, [includeInactive])

  useEffect(() => { loadDocuments() }, [loadDocuments])

  if (user.role !== 'admin') return <Navigate to={`/app/${user.role}`} replace />

  async function uploadPdf(event) {
    event.preventDefault()
    if (!file) return
    setBusy('upload')
    setError('')
    setNotice('')
    try {
      const form = new FormData()
      form.append('file', file)
      const result = await apiRequest('/api/knowledge/upload', { method: 'POST', body: form })
      setNotice(result.status === 'ready' ? `Processed ${result.filename} into ${result.chunk_count} searchable chunks.` : `${result.filename}: ${result.processing_error}`)
      setFile(null)
      pdfFormRef.current?.reset()
      await loadDocuments()
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy('')
    }
  }

  async function addArticle(event) {
    event.preventDefault()
    setBusy('article')
    setError('')
    setNotice('')
    try {
      const result = await apiRequest('/api/knowledge/articles', {
        method: 'POST',
        body: JSON.stringify(article),
      })
      setNotice(result.status === 'ready' ? `Article added as ${result.chunk_count} searchable chunks.` : result.processing_error)
      setArticle({ title: '', content: '' })
      await loadDocuments()
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy('')
    }
  }

  async function deactivate(document) {
    if (!window.confirm(`Deactivate "${document.filename}"? It will no longer be used for answers.`)) return
    setBusy(document.id)
    setError('')
    try {
      await apiRequest(`/api/knowledge/${document.id}`, { method: 'DELETE' })
      setNotice(`${document.filename} is no longer searchable.`)
      await loadDocuments()
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy('')
    }
  }

  async function reprocess(document) {
    setBusy(document.id)
    setError('')
    try {
      const result = await apiRequest(`/api/knowledge/${document.id}/reprocess`, { method: 'POST' })
      setNotice(result.status === 'ready' ? `${result.filename} re-indexed successfully.` : result.processing_error)
      await loadDocuments()
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy('')
    }
  }

  async function searchKnowledge(event) {
    event.preventDefault()
    setBusy('search')
    setError('')
    try {
      const result = await apiRequest('/api/knowledge/search', {
        method: 'POST',
        body: JSON.stringify({ query }),
      })
      setSearchMode(result.mode)
      setResults(result.sources)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy('')
    }
  }

  return (
    <main className="workspace-page knowledge-page">
      <header className="topbar ticket-topbar">
        <Link className="brand" to="/app/admin"><span className="brand-mark"><BookOpen size={17} /></span><span>Nexus<span className="brand-light">AI</span></span></Link>
        <Link className="back-link" to="/app/admin"><ArrowLeft size={14} /> Workspace</Link>
      </header>
      <section className="ticket-content knowledge-content">
        <div className="ticket-page-heading">
          <div><p className="section-kicker">ADMINISTRATION</p><h1>Knowledge base</h1><p>Manage the company sources used to ground customer support answers.</p></div>
          <button type="button" className="refresh-button" onClick={loadDocuments} disabled={loading}><RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh</button>
        </div>
        <div className="knowledge-notice"><BookOpen size={16} /><span><strong>Source-grounded answers</strong><small>Configure LLM_API_BASE_URL, LLM_API_KEY, LLM_MODEL, and a compatible embeddings model before indexing. PDFs and articles are chunked and embedded; customers see answers only from retrieved active sources. Document text is treated as untrusted content.</small></span></div>
        {error && <div className="ticket-alert" role="alert">{error}</div>}
        {notice && <div className="knowledge-success" role="status">{notice}</div>}
        <div className="knowledge-forms">
          <form ref={pdfFormRef} className="knowledge-card" onSubmit={uploadPdf}>
            <div className="knowledge-card-heading"><span><Upload size={15} /></span><div><h2>Upload a PDF</h2><p>Max 10 MB. Scanned/image-only PDFs need OCR (not included).</p></div></div>
            <label className="knowledge-file-field"><span>PDF file</span><input type="file" accept="application/pdf,.pdf" required onChange={(event) => setFile(event.target.files?.[0] || null)} /></label>
            {file && <small className="knowledge-file-name">{file.name} · {(file.size / 1024 / 1024).toFixed(2)} MB</small>}
            <button type="submit" className="primary-button" disabled={!file || Boolean(busy)}>{busy === 'upload' ? <><LoaderCircle size={14} className="spin" /> Processing…</> : <><Upload size={14} /> Upload and index</>}</button>
          </form>
          <form className="knowledge-card" onSubmit={addArticle}>
            <div className="knowledge-card-heading"><span><FileText size={15} /></span><div><h2>Add an article</h2><p>Write a policy or support guide directly.</p></div></div>
            <label className="ticket-field"><span>Article title</span><input required minLength="3" maxLength="160" value={article.title} onChange={(event) => setArticle({ ...article, title: event.target.value })} /></label>
            <label className="ticket-field"><span>Article content</span><textarea required minLength="20" maxLength="200000" rows="4" value={article.content} onChange={(event) => setArticle({ ...article, content: event.target.value })} /></label>
            <button type="submit" className="primary-button" disabled={Boolean(busy)}>{busy === 'article' ? <><LoaderCircle size={14} className="spin" /> Processing…</> : <><Plus size={14} /> Add and index</>}</button>
          </form>
        </div>
        <section className="knowledge-card knowledge-search-card">
          <div className="knowledge-card-heading"><span><Search size={15} /></span><div><h2>Test retrieval</h2><p>Preview the sources that would support a customer question.</p></div></div>
          <form className="knowledge-search-form" onSubmit={searchKnowledge}>
            <input aria-label="Search knowledge base" minLength="2" maxLength="2000" required placeholder="Ask a question to test retrieval…" value={query} onChange={(event) => setQuery(event.target.value)} />
            <button className="secondary-button" type="submit" disabled={Boolean(busy)}>{busy === 'search' ? 'Searching…' : 'Search'} <Search size={13} /></button>
          </form>
          {searchMode && <p className="retrieval-mode">Retrieval mode: <strong>{searchMode === 'vector' ? 'Atlas Vector Search' : 'Keyword fallback (not semantic)'}</strong></p>}
          {searchMode && !results.length && <div className="knowledge-empty">No relevant source was retrieved. The assistant will offer human support instead of inventing an answer.</div>}
          {results.map((source) => <article className="knowledge-search-result" key={source.chunk_id}><strong>{source.filename}{source.page_number ? ` · page ${source.page_number}` : ''}</strong><p>{source.text}</p></article>)}
        </section>
        <section className="knowledge-card knowledge-documents-card">
          <div className="knowledge-documents-heading"><div><h2>Documents and articles</h2><p>{documents.length} shown · status reflects indexing availability</p></div><label className="knowledge-inactive-toggle"><input type="checkbox" checked={includeInactive} onChange={(event) => setIncludeInactive(event.target.checked)} /> Include inactive</label></div>
          {loading ? <div className="knowledge-empty"><LoaderCircle size={15} className="spin" /> Loading documents…</div> : documents.length === 0 ? <div className="knowledge-empty">No knowledge sources yet. Add an article or upload a PDF.</div> : (
            <div className="knowledge-document-list">
              {documents.map((document) => <article className="knowledge-document-row" key={document.id}>
                <span className="knowledge-document-icon">{document.document_type === 'pdf' ? <FileText size={17} /> : <BookOpen size={17} />}</span>
                <div className="knowledge-document-copy"><strong>{document.filename}</strong><small>{document.document_type.toUpperCase()} · {document.chunk_count} chunks · {new Date(document.uploaded_at).toLocaleString()}</small>{document.processing_error && <small className="knowledge-processing-error">{document.processing_error}</small>}</div>
                <span className={`knowledge-status knowledge-status-${document.status}`}>{document.status}</span>
                {document.status !== 'ready' && document.status !== 'processing' && <button className="secondary-button" type="button" onClick={() => reprocess(document)} disabled={Boolean(busy)}>{busy === document.id ? 'Working…' : 'Re-index'}</button>}
                {document.status !== 'inactive' && <button className="knowledge-delete-button" type="button" onClick={() => deactivate(document)} disabled={Boolean(busy)} aria-label={`Deactivate ${document.filename}`}><Trash2 size={15} /></button>}
              </article>)}
            </div>
          )}
        </section>
      </section>
    </main>
  )
}
