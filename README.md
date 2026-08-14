# ONCODIR and ONCOSCREEN support platform

This repository contains the shared software platform for two distinct cancer-screening projects:

- `ONCODIR`
- `ONCOSCREEN`

They share one implementation but keep separate project configuration, operator access, WhatsApp configuration, FAQ content, conversations, tickets, and retention settings. Public interfaces must always use the configured project name rather than a combined product label.

## Current status

Phases 1–8 provide the local platform, project-isolated data foundation, operator authentication, human-support workflow, deterministic FAQ pipeline, configurable Meta WhatsApp adapter, privacy/operations controls, and pre-production assurance:

- FastAPI application with liveness and database-readiness endpoints;
- validated project configuration for ONCODIR and ONCOSCREEN;
- PostgreSQL with pgvector through Docker Compose;
- Alembic migration foundation;
- a network-free mock WhatsApp provider used by default in local development;
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
- public Meta webhook verification with raw-body HMAC-SHA256 authenticity validation;
- authoritative project resolution from the receiving Meta phone-number ID;
- durable webhook deduplication without retaining raw webhook bodies;
- inbound text and configured interactive-reply handling plus metadata-only unsupported-media escalation;
- first-interaction, inactivity, attachment, and deterministic sensitive-content privacy warnings;
- a real Meta Cloud API sender for free-form text and approved templates;
- worker-side 24-hour customer-service-window enforcement and terminal/non-terminal error handling;
- monotonic sent, delivered, read, and failed status processing, including out-of-order reconciliation;
- approved-template listing and sending in the operator panel when the free-form window is closed.
- configurable message redaction and record-retention cleanup with dry-run support;
- cleanup of expired authentication state and aggregate retention audit events;
- administrator-only operations metrics and audit-event visibility;
- privacy-minimizing structured request/worker logging and API security headers;
- production configuration validation and team-owned operational runbooks.
- a synthetic full-system acceptance test from signed webhook through operator resolution and mock delivery;
- GitHub Actions quality gates and automated dependency-update proposals;
- a production-like, synthetic-data-only staging Compose definition;
- machine-checkable staging/production resource-separation manifests;
- a compiled static frontend image and initial accessibility improvements/checks;
- release-acceptance, staging, and project-onboarding runbooks.

The Meta integration is implemented but intentionally disabled. The repository contains no real phone-number ID, Meta token, app secret, verification token, approved template, or public webhook address. It contains the reviewed ONCODIR LIP-01 v1 FAQ collection, but still has no ONCOSCREEN FAQ, MFA, or production deployment configuration.

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
- `GET /webhooks/whatsapp` (Meta subscription verification when configured)
- `POST /webhooks/whatsapp` (signed Meta webhook deliveries when configured)

For temporary Meta callback verification from a private VM, see
`infrastructure/runbooks/meta-quick-tunnel.md`. The Quick Tunnel exposes only the
WhatsApp webhook path and is not a production endpoint.

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

Semantic retrieval is intentionally disabled for both projects until reviewed Romanian evaluation sets exist and project-specific thresholds are calibrated. Exact matches can return only currently valid, published answers. Every uncertain, ambiguous, expired, or unconfigured result escalates.

The reviewed ONCODIR LIP-01 v1 collection is stored at
`backend/content/approved/ONCODIR/faq-v1.csv`. Its provenance and review
mapping are documented beside the file. ONCOSCREEN still has no approved FAQ
collection, and ONCODIR semantic retrieval remains disabled until a labelled
evaluation set is reviewed and calibrated.

Validate an approved UTF-8 CSV without changing the database:

`docker compose exec backend python -m app.commands.import_faqs --project ONCODIR --file /approved/faq.csv`

Publication requires an active administrator membership and an explicit flag:

`docker compose exec backend python -m app.commands.import_faqs --project ONCODIR --administrator-email admin@example.invalid --file /approved/faq.csv --publish`

When embedding calibration begins, set `BACKEND_BUILD_TARGET=development-embeddings`, rebuild the shared backend image, and add `--with-embeddings` to the publication command. The configured CPU model is `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`; no model or threshold is selected silently.

Evaluation labels use `logical_key@version` or `ESCALATE`. Candidate thresholds and best-versus-second-best gaps must be supplied explicitly:

`docker compose exec backend python -m app.commands.evaluate_faqs --project ONCODIR --file /approved/evaluation.csv --thresholds <reviewed-score-candidates> --score-gaps <reviewed-gap-candidates>`

No numeric defaults are recommended. Only values meeting the reviewed precision and high-risk criteria may be copied into project configuration. Expiry processing and emergency withdrawal are available through `app.commands.expire_faqs` and `app.commands.retire_faq`.

## Meta WhatsApp configuration

Local development continues to use `WHATSAPP_PROVIDER=mock`; it performs no network requests. Phase 6 can therefore be exercised before either project has a server or phone number.

Enabling a project later requires its authoritative Meta phone-number ID plus separate opaque credential and webhook binding names in the project JSON. The bindings resolve through a deployment-injected JSON secret file outside Git. Credential bindings contain access tokens; webhook bindings contain app secrets and verification tokens. Two projects may point to the same webhook binding when they share a Meta application, but the implementation does not assume that they do.

For a real Meta connection, deployment configuration must set:

- `WHATSAPP_PROVIDER=meta`;
- `WHATSAPP_SECRET_FILE` to a root-owned or Docker-secret-mounted JSON file;
- `META_GRAPH_API_VERSION` to the explicitly reviewed Meta Graph API version;
- the project-specific phone IDs and opaque bindings;
- separately approved project templates where messages may be sent outside the 24-hour window.

The webhook never downloads unsupported media and does not retain the raw webhook body. It stores only message/status IDs, timestamps, event type, and the minimum attachment or delivery-error metadata needed for deduplication, audit continuity, and operator handling. Invalid signatures, unknown receiving phone IDs, and oversized payloads are rejected before business processing.

Free-form text is checked against the 24-hour window both when an operator queues a reply and again when the outbox worker attempts delivery. Outside the window, only a configured, currently approved project template can be queued. No template is included in the repository yet.

Frontend commands are run from `frontend/`:

- `npm install`
- `npm run dev`
- `npm test`
- `npm run build`

## Test-data rule

Files under `backend/tests/fixtures/` are synthetic and must never be imported into production. A production environment with no approved FAQ collection must safely escalate questions rather than use test answers.

## Secrets

Production secrets must be injected at deployment time using Docker secrets where practical or root-owned files outside this repository. Never place Meta tokens, app secrets, database credentials, session keys, or backup keys in Git, frontend variables, images, or documentation.

## Operations and data lifecycle

The production retention values remain provisional until reviewed by the
project owners. Preview the configured cleanup without modifying data:

`docker compose exec backend python -m app.commands.run_retention`

Applying retention requires the explicit `--apply` flag. Configure its
production schedule only after reviewing the preview and confirming a current
encrypted backup. Pending outbound delivery payloads are preserved until they
reach a terminal state, while expired message content is removed from the
conversation record.

Administrators can inspect content-free delivery/retention metrics and
project-scoped audit events through **Operațiuni și audit**. Infrastructure
backup, certificate, disk, and host monitoring remains an operational
responsibility rather than an in-application substitute.

Phase 7 runbooks:

- [operations](infrastructure/runbooks/operations.md);
- [backup and restore](infrastructure/runbooks/backup-restore.md);
- [incident response](infrastructure/runbooks/incident-response.md);
- [production readiness](infrastructure/runbooks/production-readiness.md).

Phase 8 assurance and onboarding:

- [staging](infrastructure/runbooks/staging.md);
- [release acceptance](infrastructure/runbooks/release-acceptance.md);
- [project onboarding](infrastructure/runbooks/project-onboarding.md).

Phase 9A team-managed VM operations:

- [Debian VM security baseline](infrastructure/runbooks/vm-hardening.md);
- [VM-test maintenance, restart, and rollback](infrastructure/runbooks/vm-maintenance.md).

For the temporary Debian VM without stable DNS or HTTPS, use the
[internal VM-test deployment](infrastructure/runbooks/vm-test.md). It serves
compiled images with generated deployment secrets and binds HTTP only to the
VM loopback interface for access through an SSH tunnel. It is strictly limited
to synthetic data and the mock WhatsApp provider.

Validate the example staging/production isolation declarations:

`docker compose run --rm --no-deps -v <absolute-repository-path>/infrastructure:/workspace/infrastructure:ro backend python -m app.commands.validate_environment_separation --staging /workspace/infrastructure/environments/staging.manifest.example.json --production /workspace/infrastructure/environments/production.manifest.example.json`

CI supplies the absolute repository path automatically. On a server, pass
deployment-owned manifests instead. They contain resource identities only,
never secret values.

The backup technology and remote destination cannot be selected until the
server/storage environment exists. Production nevertheless requires tested
daily full/base backups plus continuous WAL or equivalent incremental capture;
a daily logical dump alone does not satisfy the provisional one-hour RPO.
