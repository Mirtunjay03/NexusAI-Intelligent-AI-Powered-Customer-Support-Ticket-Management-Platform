# Deployment guide

This guide prepares NexusAI for a Vercel frontend, Render FastAPI service, and MongoDB Atlas database. Deployment is not considered live until you provision accounts, set secrets, deploy, and verify the resulting URLs.

## 1. MongoDB Atlas

1. Create a MongoDB Atlas project and cluster.
2. Create a database user with a strong generated password; grant access only to the NexusAI database required by the app.
3. Configure Atlas Network Access for the Render service's outbound IP policy. Avoid `0.0.0.0/0` except as a deliberate temporary development choice.
4. Copy the TLS-enabled connection string and replace the username/password/database placeholders. Set it in Render as `MONGODB_URI`; never commit it.
5. Use `MONGODB_DATABASE=nexusai` (or your dedicated production database).
6. Configure Atlas backups/retention appropriate to the data. Source PDFs are stored in GridFS in this cluster.
7. For vector search, create the index described in the README, wait until Atlas reports it ready, and only then set `VECTOR_SEARCH_INDEX_NAME`.

## 2. Render backend

1. Push the repository to a private or public GitHub repository after confirming no `.env` or credentials are tracked.
2. In Render, create a Blueprint from the repository using `render.yaml`, or create a Python web service with root directory `backend`.
3. Use build command `pip install -r requirements.txt` and start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
4. Add `MONGODB_URI`, `CORS_ORIGINS`, and provider values using Render's secret/environment settings. `JWT_SECRET_KEY` is marked `generateValue` in the Blueprint; keep it stable between deploys or all sessions will be invalidated.
5. `CORS_ORIGINS` must exactly match the deployed Vercel frontend origin, including scheme. Do not use wildcard origins.
6. Set `LLM_API_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` only if you have a compatible provider. Set embedding model and dimensions to match the provider and Atlas index.
7. Optionally set task-specific model IDs: `LLM_CHAT_MODEL` for customer/RAG chat, `LLM_RESPONSE_MODEL` for agent drafts, `LLM_CLASSIFICATION_MODEL` for ticket triage, and `LLM_SUMMARY_MODEL` for summaries. Unset values fall back to `LLM_MODEL`; choose model IDs enabled for your provider and balance quality, latency, and cost.
8. The Render health check is `/api/health`; it pings MongoDB and returns HTTP 503 if MongoDB is unavailable. `/api/live` checks only that the process is serving requests.
9. Use a paid/persistent service tier for a production demonstration requiring consistent availability; free-tier sleep/availability behavior is controlled by Render and may change.

The service uses FastAPI's production cookie settings (`Secure`, `HttpOnly`, `SameSite=None`). Prefer a custom domain on the same registrable domain for frontend and API (for example `app.example.com` and `api.example.com`) to reduce browser third-party-cookie blocking. CORS still requires the exact frontend origin.

## 3. Vercel frontend

1. Import the repository into Vercel with the repository root as the project root.
2. `vercel.json` configures the Vite build (`npm run build`), `dist` output, and SPA route fallback.
3. Add `VITE_API_BASE_URL` as the HTTPS Render API origin, with no trailing slash; for example `https://nexusai-api.onrender.com`.
4. Deploy and note the exact Vercel origin.
5. Add that origin to Render's `CORS_ORIGINS`, redeploy the API, then test login and cookie behavior in a real browser. For durable browser support, configure same-site custom domains.

## 4. Admin and demo setup

After the backend is connected to Atlas, use a secure one-time terminal session to run the initial admin command against the production environment:

```powershell
cd backend
python -m app.create_admin
```

Do not place demo passwords in source control or portfolio materials. Provision agents through the admin user-management workflow; public registration creates customer-role accounts only. For a demo, create a disposable customer account through the signup UI and use a password manager or a one-time secure sharing method for credentials.

## 5. Production verification checklist

- `GET https://<api-host>/api/live` returns `200`.
- `GET https://<api-host>/api/health` returns `200` and `database: connected`.
- `https://<frontend-host>` serves the SPA and deep links resolve to the app.
- Browser network panel shows API requests to the configured HTTPS host, CORS allows the exact origin, and the HttpOnly session cookie persists.
- Customer signup/login, ticket creation, agent reply, admin source upload, and ticket/chat authorization are verified.
- AI readiness and embeddings are tested only after provider credentials are configured.
- RAG source citations and retrieval mode are verified; Atlas vector mode is claimed only after the actual configured index is ready.
- No production secret is present in build output, repository files, or frontend environment variables (except the public API origin).
- Atlas access controls, backups, logs, rate limits, and hosting plan are reviewed before using real customer data.

## Environment variable reference

Backend names and local examples are in `backend/.env.example`. Production secrets are entered directly into the hosting dashboard, not copied into committed files.

| Variable | Required | Purpose |
|---|---|---|
| `APP_ENV` | Yes | Set to `production` for Secure cookies and production validation |
| `MONGODB_URI` | Yes | TLS Atlas connection string; secret |
| `MONGODB_DATABASE` | Yes | Production database name |
| `JWT_SECRET_KEY` | Yes | Signing key; keep stable and secret |
| `CORS_ORIGINS` | Yes | Exact trusted frontend origins, comma-separated |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Recommended | Session lifetime |
| `LLM_API_BASE_URL` | Optional | OpenAI-compatible provider base URL |
| `LLM_API_KEY` | Optional | Provider credential; secret |
| `LLM_MODEL` | Optional | Chat/classification model |
| `LLM_CLASSIFICATION_MODEL` | Optional | Override for ticket classification |
| `LLM_RESPONSE_MODEL` | Optional | Override for agent reply drafts |
| `LLM_SUMMARY_MODEL` | Optional | Override for ticket summaries |
| `LLM_CHAT_MODEL` | Optional | Override for customer and RAG chat |
| `LLM_REQUEST_TIMEOUT_SECONDS` | Optional | Provider HTTP timeout |
| `EMBEDDING_MODEL` | Optional for RAG | Embedding API model |
| `EMBEDDING_DIMENSIONS` | Optional for RAG | Vector dimension; must match model/index |
| `VECTOR_SEARCH_INDEX_NAME` | Optional | Enables Atlas vector retrieval only when the index exists |
| `KNOWLEDGE_TENANT_ID` | Recommended | Deployment-level knowledge partition |
| `KNOWLEDGE_CHUNK_SIZE` / `KNOWLEDGE_CHUNK_OVERLAP` | Optional | Chunking policy |
| `KNOWLEDGE_TOP_K` / `KNOWLEDGE_MIN_SCORE` | Optional | Retrieval count and Atlas relevance floor |
| `KNOWLEDGE_MAX_PDF_BYTES` | Optional | Upload byte limit |
| `KNOWLEDGE_MAX_EXTRACTED_CHARS` | Optional | Extracted text upper bound |
| `VITE_API_BASE_URL` | Yes for frontend deploy | Public HTTPS API origin; not a secret |
