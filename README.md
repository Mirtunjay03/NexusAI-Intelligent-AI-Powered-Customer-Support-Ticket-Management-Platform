# NexusAI

NexusAI is an AI-powered customer support and ticket management platform. **Phases 1–7 provide the React frontend, FastAPI service, MongoDB connection lifecycle, database-backed authentication, role-aware ticket management, live analytics dashboards, LLM-powered ticket intelligence, a customer chat assistant, human-reviewed agent drafts, and a document-grounded knowledge base.** Atlas Vector Search is optional; without its configured index, retrieval is explicitly labelled keyword fallback rather than semantic search.

## Architecture

```text
frontend (React + Vite) ── HTTP/CORS ──> backend (FastAPI) ──> MongoDB
       localhost:5173                    localhost:8000
```

For production, the target architecture is Vercel (static frontend), Render (FastAPI), and MongoDB Atlas. See [architecture and database design](docs/ARCHITECTURE.md) and the [deployment guide](docs/DEPLOYMENT.md). Deployment descriptors are included, but this repository has not been deployed to external hosting.

The frontend checks `/api/health` rather than displaying a fabricated service status. The API reports HTTP 503 if MongoDB is unavailable. MongoDB credentials and service configuration are read from environment variables. Authentication uses Argon2id password hashes and short-lived JWTs in HttpOnly cookies; public registration always creates a customer account. Tickets are stored separately from conversation messages and audit events, with access checks applied per requester role. Internal notes are filtered from customer ticket and history responses. Dashboard counts, trends, distribution, and workload are calculated by backend MongoDB aggregation pipelines. The LLM layer uses an OpenAI-compatible chat-completions and embeddings API and validates structured outputs. Admin-managed PDFs and articles are stored in GridFS, extracted into page-aware chunks, and embedded into `knowledge_chunks`. Chat retrieval is tenant-scoped, uses Atlas Vector Search only when explicitly configured, and otherwise discloses keyword fallback. Customer responses cite only returned document/page references; no match yields an explicit no-answer and human-support option.

## Technology

- Frontend: React, Vite, JavaScript, Lucide React
- Backend: Python, FastAPI, Pydantic Settings, PyMongo
- Database: MongoDB (local development or MongoDB Atlas)
- Authentication: PyJWT, pwdlib/Argon2id, HttpOnly session cookie
- Analytics: MongoDB aggregation pipelines, Recharts
- AI: configurable OpenAI-compatible chat and embeddings provider, validated structured output
- Knowledge base: PyMuPDF extraction, GridFS source storage, chunk embeddings, Atlas Vector Search / keyword fallback

## Problem and features

Support teams need one place to triage customer requests, coordinate agent responses, and find consistent policy answers. NexusAI combines a role-based ticket inbox and operational dashboards with configurable AI assistance. Customers submit and track tickets or ask the assistant; agents assign and resolve requests with private notes; admins manage users, knowledge sources, and analytics.

AI-assisted classification, summaries, and reply suggestions are validated and visibly marked; a human must send a reply. Customer RAG responses use tenant-scoped retrieved sources and return document/page references. Without evidence, the assistant says it cannot answer and offers escalation. When Atlas Vector Search is not configured, the app explicitly labels keyword fallback.

## Database design

MongoDB stores `users`, `tickets`, `ticket_messages`, `ticket_events`, `counters`, `ai_chat_sessions`, `ai_rate_limits`, `knowledge_documents`, and `knowledge_chunks`. GridFS stores uploaded source bytes in the selected MongoDB deployment. Key indexes cover user email, ticket number/ownership/assignment/status/priority/date, ticket message/event timelines, AI TTL cleanup, and knowledge tenant/document queries. See [collection and index details](docs/ARCHITECTURE.md#collections).

## Requirements

- Node.js 20+
- Python 3.10+
- MongoDB locally or a MongoDB Atlas connection string

## Setup

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Set `MONGODB_URI` in `backend/.env` to your local MongoDB URI or Atlas connection string. The API starts even if the database is temporarily unavailable; its readiness endpoint will return `503` until MongoDB responds.

Set a long, random `JWT_SECRET_KEY` for deployments. Production mode refuses to start with an unset signing key and uses Secure, SameSite=None session cookies. For development, the signing secret is generated for the running process when the environment variable is empty.

Production `CORS_ORIGINS` must contain explicit trusted frontend origins (wildcards are rejected). State-changing requests reject any supplied untrusted `Origin`; production requests carrying the session cookie must include an allowed `Origin`, preventing cross-site form submissions such as admin knowledge uploads. Configure the deployed frontend origin exactly, including its scheme and hostname. The `/api/health` check pings MongoDB and reports `503` when the database is unavailable; this is a readiness check as well as an API liveness check.

### LLM provider (optional)

To enable ticket classification, customer chat, response drafts, and ticket summaries, set these values in `backend/.env`:

```dotenv
LLM_API_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-provider-key
LLM_MODEL=your-enabled-model
LLM_REQUEST_TIMEOUT_SECONDS=25
```

`LLM_API_BASE_URL` is the provider's API base URL; NexusAI appends `/chat/completions`. Use a compatible provider endpoint and keep the API key private. If these settings are absent or a call fails, ticket creation still succeeds with AI classification marked `pending`; manual AI actions return an explicit service error instead of invented output. Agent response suggestions and summaries are visibly AI-generated; suggestions are never sent automatically. Customer chat can retrieve matching active company knowledge but cannot access account/ticket records or perform actions; unsupported questions lead to human support. Customers can turn their chat into a support ticket. Staff AI endpoints and customer chat have database-backed rate limits; chatbot transcripts expire after 30 days.

For model tuning, optionally set `LLM_CLASSIFICATION_MODEL`, `LLM_RESPONSE_MODEL`, `LLM_SUMMARY_MODEL`, and `LLM_CHAT_MODEL` to model IDs available from your provider. These override `LLM_MODEL` for ticket triage, agent drafts, summaries, and customer/RAG chat respectively. This lets you use a faster model for structured triage and a more capable model for customer-facing answers without changing code; unset overrides use `LLM_MODEL`. Model IDs and capabilities vary by provider, so select models that support the JSON response mode used by the API. Embeddings remain separately configured with `EMBEDDING_MODEL` and `EMBEDDING_DIMENSIONS`.
For knowledge indexing, the provider must also support OpenAI-compatible `POST /embeddings`. `EMBEDDING_MODEL` and `EMBEDDING_DIMENSIONS` must match that provider's model and the Atlas index. The default is `text-embedding-3-small` with 1536 dimensions. Uploads require a valid PDF signature, are limited by `KNOWLEDGE_MAX_PDF_BYTES` (10 MB) and `KNOWLEDGE_MAX_EXTRACTED_CHARS` (500,000) by default, reject encrypted/over-1000-page/image-only PDFs, and store source bytes in MongoDB GridFS. OCR is not included.

### Atlas Vector Search (optional)

Create a Search index on `knowledge_chunks` with the exact index name you set in `VECTOR_SEARCH_INDEX_NAME` (for example `nexusai_knowledge_vector`). Its definition must match the embedding dimensions and include tenant/active filters:

```json
{
  "fields": [
    { "type": "vector", "path": "embedding", "numDimensions": 1536, "similarity": "cosine" },
    { "type": "filter", "path": "tenant_id" },
    { "type": "filter", "path": "is_active" }
  ]
}
```

Set `VECTOR_SEARCH_INDEX_NAME=nexusai_knowledge_vector` only after Atlas reports the index ready. If unset, the API reports `keyword_fallback` and uses MongoDB text-field matching; this mode is not semantic and is labelled in the admin UI and chatbot. A configured but missing/misconfigured Atlas index returns an explicit retrieval error rather than silently switching modes. This deployment currently has one configured knowledge tenant (`KNOWLEDGE_TENANT_ID`); all content and retrieval filters are isolated to that deployment tenant.

### Frontend

In another terminal, from the repository root:

```powershell
npm install
Copy-Item frontend\.env.example .env.local
npm run dev
```

Open the Vite URL printed in the terminal (normally `http://localhost:5173`). Set `VITE_API_BASE_URL` in `.env.local` if the backend is hosted elsewhere.

Keep the backend process in **Terminal 1** and run the frontend in **Terminal 2**:

```powershell
# Terminal 1
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

```powershell
# Terminal 2, repository root
npm run dev
```

### Provisioning the first administrator

Public registration intentionally cannot select elevated roles. After configuring the backend environment, create the initial admin interactively:

```powershell
cd backend
python -m app.create_admin
```

The script prompts for the admin name, email, and password and writes only the Argon2id password hash to MongoDB.

## API and checks

- Health check: `GET http://localhost:8000/api/health`
- Liveness check (does not contact MongoDB): `GET http://localhost:8000/api/live`
- Register customer: `POST http://localhost:8000/api/auth/register`
- Sign in: `POST http://localhost:8000/api/auth/login`
- Current session: `GET http://localhost:8000/api/auth/me`
- Sign out: `POST http://localhost:8000/api/auth/logout`
- Admin user management: `GET /api/users`, `GET /api/users/{user_id}`, `PATCH /api/users/{user_id}`
- Tickets: `POST /api/tickets`, `GET /api/tickets`, `GET /api/tickets/{ticket_id}`, `PATCH /api/tickets/{ticket_id}`
- Ticket workflow: `PATCH /api/tickets/{ticket_id}/status`, `PATCH /api/tickets/{ticket_id}/assign`
- Conversation: `GET /api/tickets/{ticket_id}/messages`, `POST /api/tickets/{ticket_id}/messages`, `POST /api/tickets/{ticket_id}/internal-notes`
- Audit history: `GET /api/tickets/{ticket_id}/history`
- Agent options: `GET /api/tickets/agents` (staff only)
- Role dashboard analytics: `GET /api/analytics/dashboard`
- AI readiness: `GET /api/ai/status` (staff only)
- AI classification: `POST /api/ai/tickets/{ticket_id}/classify` (staff only)
- AI response draft: `POST /api/ai/tickets/{ticket_id}/suggest-response` (staff only)
- AI ticket summary: `POST /api/ai/tickets/{ticket_id}/summarize` (staff only)
- Customer chatbot: `GET|POST|DELETE /api/ai/chat` (customer only)
- Escalate chatbot conversation: `POST /api/ai/chat/escalate` (customer only)
- Knowledge PDF upload: `POST /api/knowledge/upload` (admin only, multipart PDF)
- Add article: `POST /api/knowledge/articles` (admin only)
- List/deactivate/re-index sources: `GET /api/knowledge`, `DELETE /api/knowledge/{document_id}`, `POST /api/knowledge/{document_id}/reprocess` (admin only)
- Test knowledge retrieval: `POST /api/knowledge/search` (admin only)
- Interactive API docs: `http://localhost:8000/docs`
- Frontend production build: `npm run build`
- Backend tests: from `backend/`, run `pytest`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

### Phase 8 verification

The backend tests cover authentication and role checks, ticket creation/assignment/replies/internal-note privacy, pagination and filters, AI provider output validation with mocked provider calls, PDF signature/extraction/chunking, tenant-scoped keyword and vector retrieval, missing Atlas index behavior, source citations, no-evidence escalation, document deactivation/re-indexing, and production-origin checks. The end-to-end integration test uses the in-memory Mongo test double and mocked AI/embedding methods; it exercises customer signup and ticket creation/classification, agent assignment/reply, admin access and PDF indexing, and a cited chatbot answer. No external LLM or Atlas Vector Search request is made by automated tests.

In addition, the complete register/login → ticket classification → agent assignment/reply → admin PDF upload/index → chatbot source-citation flow was exercised against the local MongoDB server using a uniquely named temporary database and mocked LLM/embedding methods; that temporary database was removed afterward. No formal penetration test or security certification has been performed. Real-provider and Atlas vector-search end-to-end behavior still require operator credentials and an Atlas search index; the configured environment currently has neither.

## Project structure

```text
backend/
  app/
    ai/          LLM provider abstraction and validated outputs
    api/         HTTP routes
      analytics.py role-scoped dashboard aggregates
      ai.py       LLM features, customer chat, and support escalation
      knowledge.py admin knowledge source management and indexing
    ai/
      knowledge.py PDF/article chunking and tenant-scoped retrieval
    core/        application settings
    database/    MongoDB client
    schemas/     validated API schemas
    create_admin.py  interactive initial-admin provisioning
    main.py      FastAPI app and lifecycle
  tests/
frontend/
  .env.example
src/
  components/    protected routes
  context/       authentication state
  pages/         landing, auth, ticket, and role dashboard views
  services/      API client
docs/
  ARCHITECTURE.md deployment and collection diagrams
  DEPLOYMENT.md  Atlas, Render, and Vercel runbook
  PORTFOLIO.md   demo, screenshot, and resume notes
```

## Environment variables

See `backend/.env.example` and `frontend/.env.example`. Never commit `.env` files or credentials.

## Deployment and portfolio

- **Deployment:** follow [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for Atlas, Render, Vercel, production environment variables, cookie/CORS setup, admin provisioning, and post-deploy verification. Root-level `render.yaml` and `vercel.json` provide starter configurations.
- **Storage:** PDF originals use MongoDB GridFS; Atlas storage survives Render restarts/redeploys. This avoids reliance on an ephemeral Render filesystem. Configure Atlas backups and retention.
- **Portfolio:** [docs/PORTFOLIO.md](docs/PORTFOLIO.md) includes feature highlights, a resume-ready project summary, demo steps, and known limitations. A genuine landing-page capture is available at [docs/screenshots/landing.png](docs/screenshots/landing.png); capture additional authenticated screens only with disposable demo data.
- **API documentation:** run the backend and open `http://localhost:8000/docs`; OpenAPI JSON is `/openapi.json`.

No hosted deployment, external provider credentials, performance metrics, production user counts, model accuracy figures, formal penetration test, or security certification are claimed.

## Roadmap

1. Core project setup and database connectivity (complete)
2. Authentication, initial admin provisioning, roles, and protected routes (complete)
3. Ticket CRUD, assignment, conversations, search, filters, and audit history (complete)
4. Admin, agent, and customer dashboards with live analytics (complete)
5. LLM provider abstraction, ticket classification, response drafts, and summaries (complete when provider configured)
6. Customer chatbot, human-reviewed agent assistance, and ticket summaries (complete)
7. Knowledge management, PDF/article processing, embeddings, and RAG (complete; Atlas vector search requires operator configuration)
8. Security review, production-origin checks, workflow tests, and quality assurance (implemented; no formal penetration test)
9. Deployment configuration, complete documentation, and portfolio preparation (complete; external hosting not provisioned)
