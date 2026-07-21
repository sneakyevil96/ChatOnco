# ONCODIR and ONCOSCREEN support platform

This repository contains the shared software platform for two distinct cancer-screening projects:

- `ONCODIR`
- `ONCOSCREEN`

They share one implementation but keep separate project configuration, operator access, WhatsApp configuration, FAQ content, conversations, tickets, and retention settings. Public interfaces must always use the configured project name rather than a combined product label.

## Current status

Phases 1–5 provide the local platform, project-isolated data foundation, operator authentication, human-support workflow, and deterministic FAQ pipeline:

- FastAPI application with liveness and database-readiness endpoints;
- validated project configuration for ONCODIR and ONCOSCREEN;
- PostgreSQL with pgvector through Docker Compose;
- Alembic migration foundation;
- a mock-only WhatsApp client boundary;
- React, TypeScript, Vite, React Router, TanStack Query, and Material UI foundation;
- Caddy as the local single entry point;
- backend and frontend test foundations;
- explicitly synthetic FAQ fixtures for automated tests only;
- project-owned SQLAlchemy entities and an initial Alembic migration;
- composite foreign keys that reject cross-project relationships;
- database-enforced one-active-ticket-per-conversation semantics;
- project-scoped repository foundations and PostgreSQL isolation tests;
- database records synchronized from the validated deployment configuration;
- Argon2id application-managed authentication with forced first-login password change;
- opaque server-side sessions, signed/session-bound CSRF protection, and secure cookie policy;
- database-backed login throttling, account lockout, password reset, and session revocation;
- project-scoped operator and administrator authorization with audited account actions;
- protected React routes for login, password management, project selection, and operator administration;
- project-scoped ticket queues with masked contact identifiers and 15-second polling;
- atomic claiming, release, administrator reassignment, internal notes, and audited status transitions;
- conversation history, WhatsApp 24-hour-window visibility, and persistent queued operator replies;
- automatic seven-day resolved-ticket reopening and in-panel operator notifications;
- a dedicated database-claiming outbox worker with retry scheduling and terminal-failure tracking;
- controlled, audited, project-scoped FAQ CSV publication and emergency withdrawal;
- Romanian exact normalization plus optional local pgvector semantic retrieval;
- labelled evaluation tooling requiring `FAQ@version` or `ESCALATE` outcomes;
- provider-independent inbound orchestration that returns only stored answers or creates a ticket.

The current foundation does **not** contain real Meta integration, real FAQ content, MFA, or production deployment configuration. Operator replies are persisted to the PostgreSQL outbox but are not sent to Meta yet.

## Local prerequisites

- Docker with Docker Compose
- Alternatively, Python 3.12+ and Node.js 22+ for running services directly

## Local startup

1. Copy `.env.example` to `.env`.
2. Keep all placeholder values local; never add production credentials.
3. Start the stack with `docker compose up --build`.
4. Open `http://localhost:8080`.

Useful endpoints:

- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`
- `GET /api/v1/projects`

The local database is not published to the host. Caddy is the only service with a host port.

## Direct development

Backend commands are run from `backend/` after installing the development dependencies:

- `pytest`
- `alembic upgrade head`
- `python -m app.commands.sync_projects`
- `uvicorn app.main:app --reload`

Docker Compose applies migrations and synchronizes the validated ONCODIR and ONCOSCREEN configuration automatically when the local backend starts.

## First local administrator

There is no public registration endpoint. After the stack is running, an authorized developer can create the first administrator with:

`docker compose exec backend python -m app.commands.bootstrap_admin --project ONCODIR --email administrator@example.invalid`

The command generates a temporary password, displays it once, assigns the explicit project membership, records a bootstrap audit event, and requires a password change at first login. Repeat with the appropriate project and authorized institutional email when configuring another project; do not use example credentials in production.

Local HTTP cookies intentionally omit `Secure` so the Compose environment works at `http://localhost:8080`. Staging and production settings require HTTPS, deployment-specific security keys, and `Secure` cookies.

To exercise the ticket panel without a WhatsApp number, create a synthetic local ticket after creating an operator account:

`docker compose exec backend python -m app.commands.create_synthetic_ticket --project ONCODIR`

This command refuses to run outside `local` or `test` environments and never contacts WhatsApp.

## Controlled FAQ workflow

Semantic retrieval is intentionally disabled for both projects until approved FAQ collections and reviewed Romanian evaluation sets exist. Exact matches can return only currently valid, published answers. Every uncertain, ambiguous, expired, or unconfigured result escalates.

Validate an approved UTF-8 CSV without changing the database:

`docker compose exec backend python -m app.commands.import_faqs --project ONCODIR --file /approved/faq.csv`

Publication requires an active administrator membership and an explicit flag:

`docker compose exec backend python -m app.commands.import_faqs --project ONCODIR --administrator-email admin@example.invalid --file /approved/faq.csv --publish`

When embedding calibration begins, set `BACKEND_BUILD_TARGET=development-embeddings`, rebuild the shared backend image, and add `--with-embeddings` to the publication command. The configured CPU model is `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`; no model or threshold is selected silently.

Evaluation labels use `logical_key@version` or `ESCALATE`. Candidate thresholds and best-versus-second-best gaps must be supplied explicitly:

`docker compose exec backend python -m app.commands.evaluate_faqs --project ONCODIR --file /approved/evaluation.csv --thresholds <reviewed-score-candidates> --score-gaps <reviewed-gap-candidates>`

No numeric defaults are recommended. Only values meeting the reviewed precision and high-risk criteria may be copied into project configuration. Expiry processing and emergency withdrawal are available through `app.commands.expire_faqs` and `app.commands.retire_faq`.

Frontend commands are run from `frontend/`:

- `npm install`
- `npm run dev`
- `npm test`
- `npm run build`

## Test-data rule

Files under `backend/tests/fixtures/` are synthetic and must never be imported into production. A production environment with no approved FAQ collection must safely escalate questions rather than use test answers.

## Secrets

Production secrets must be injected at deployment time using Docker secrets where practical or root-owned files outside this repository. Never place Meta tokens, app secrets, database credentials, session keys, or backup keys in Git, frontend variables, images, or documentation.
