# ONCODIR and ONCOSCREEN support platform

This repository contains the shared software platform for two distinct cancer-screening projects:

- `ONCODIR`
- `ONCOSCREEN`

They share one implementation but keep separate project configuration, operator access, WhatsApp configuration, FAQ content, conversations, tickets, and retention settings. Public interfaces must always use the configured project name rather than a combined product label.

## Current status

Phases 1–3 provide the local platform, project-isolated data foundation, and operator authentication:

- FastAPI application with liveness and database-readiness endpoints;
- validated project configuration for ONCODIR and ONCOSCREEN;
- PostgreSQL with pgvector through Docker Compose;
- Alembic migration foundation;
- a mock-only WhatsApp client boundary;
- React, TypeScript, Vite, React Router, TanStack Query, and Material UI foundation;
- Caddy as the local single entry point;
- backend and frontend test foundations;
- explicitly synthetic FAQ fixtures for automated tests only.
- project-owned SQLAlchemy entities and an initial Alembic migration;
- composite foreign keys that reject cross-project relationships;
- database-enforced one-active-ticket-per-conversation semantics;
- project-scoped repository foundations and PostgreSQL isolation tests;
- database records synchronized from the validated deployment configuration.
- Argon2id application-managed authentication with forced first-login password change;
- opaque server-side sessions, signed/session-bound CSRF protection, and secure cookie policy;
- database-backed login throttling, account lockout, password reset, and session revocation;
- project-scoped operator and administrator authorization with audited account actions;
- protected React routes for login, password management, project selection, and operator administration.

The current foundation does **not** contain ticket orchestration, real Meta integration, real FAQ content, MFA, or production deployment configuration.

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

Frontend commands are run from `frontend/`:

- `npm install`
- `npm run dev`
- `npm test`
- `npm run build`

## Test-data rule

Files under `backend/tests/fixtures/` are synthetic and must never be imported into production. A production environment with no approved FAQ collection must safely escalate questions rather than use test answers.

## Secrets

Production secrets must be injected at deployment time using Docker secrets where practical or root-owned files outside this repository. Never place Meta tokens, app secrets, database credentials, session keys, or backup keys in Git, frontend variables, images, or documentation.
