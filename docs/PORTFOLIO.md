# NexusAI portfolio notes

## Project description

NexusAI is a full-stack customer-support workspace built with React, FastAPI, and MongoDB. It combines role-aware ticket workflows and analytics with configurable LLM classification, human-reviewed response drafts, and a document-grounded chatbot that returns source references.

## Feature highlights

- Admin, support-agent, and customer roles with server-side authorization.
- Customer ticket submission, agent assignment, status transitions, messages, private notes, audit history, filtering, and pagination.
- MongoDB-backed dashboards and analytics.
- Configurable OpenAI-compatible provider with validated ticket classification, reply drafts, summaries, chat, and embeddings.
- Admin PDF/article knowledge management; PDF signature/size checks; page-aware chunking; Atlas Vector Search when configured; clearly disclosed keyword fallback otherwise.
- Source-cited RAG, no-evidence escalation, HttpOnly JWT cookies, password hashing, CORS/origin checks, and MongoDB GridFS source storage.

## Architecture and data model

See [Architecture and data design](ARCHITECTURE.md) for the architecture diagram, collection descriptions, indexes, tenancy boundary, and AI/RAG flows. API routes are documented interactively at `/docs` when the backend is running.

## Demo checklist

1. Provision an admin account using `python -m app.create_admin`; do not commit credentials.
2. Create an agent through admin user management and register a disposable customer account.
3. Configure a real compatible LLM and embedding provider in the backend environment if demonstrating model-generated results.
4. Upload a non-sensitive test policy PDF from the admin Knowledge page.
5. Set up an Atlas Vector Search index if demonstrating semantic retrieval; otherwise describe the actual fallback as keyword search.
6. Capture fresh screenshots from the actual running app for role dashboards, ticket detail, admin knowledge, and a chat answer with visible citations. Do not show personal data, secrets, or real customer conversations.

The repository includes [a genuine landing-page screenshot](screenshots/landing.png) captured from the running local app while the API and MongoDB were operational. Additional authenticated screenshots should be captured from a configured demo environment before publishing a portfolio page.

## Resume summary

> Built NexusAI, a full-stack customer-support platform with React, FastAPI, and MongoDB, implementing role-scoped ticket workflows, analytics dashboards, configurable LLM assistance, and source-cited document retrieval with Atlas Vector Search and an explicitly labelled keyword fallback.

This description states implemented capabilities and does not claim user counts, model accuracy, latency, production deployment, or a formal security assessment.

## Known limitations

- No live production deployment has been provisioned from this workspace.
- The current environment has no configured LLM provider credentials or Atlas Vector Search index; real model/semantic behavior needs operator setup.
- Keyword fallback is lexical rather than semantic.
- OCR for image-only PDFs is not included.
- Knowledge tenant selection is deployment-wide; organization membership and per-user multi-tenant administration are not yet modeled.
- GridFS is the current durable source store; a dedicated object store can be added if file volume or retention needs grow.
- Automated workflow coverage uses mocked model calls. No formal penetration test or security certification is claimed.
