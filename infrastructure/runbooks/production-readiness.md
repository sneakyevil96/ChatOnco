# Production-readiness checklist

Do not process real participant data until every applicable item has an owner,
evidence, and explicit approval. The current retention, availability, and
recovery values are provisional engineering defaults, not institutional
policy.

## Product and content

- ONCODIR and ONCOSCREEN public names, contacts, warnings, fallback messages,
  retention values, branding, and templates are approved separately.
- Approved Romanian FAQ versions and labelled evaluation sets exist for each
  enabled project.
- Exact/semantic retrieval meets the reviewed precision and high-risk criteria;
  otherwise semantic retrieval remains disabled.
- No test FAQ or production participant data is present in the wrong
  environment.

## Meta and messaging

- Each enabled project has an authoritative receiving phone-number ID.
- Meta tokens, app secrets, verification tokens, templates, and Graph API
  version are reviewed and injected outside Git.
- Webhook authenticity, deduplication, statuses, retry behavior, and the
  24-hour window have been tested with the approved non-production setup.
- Delivery failure and webhook failure alerts reach an accountable person.

## Identity and access

- First administrator bootstrap is complete and temporary credentials changed.
- Operator and administrator memberships have least-privilege project access.
- Production panel exposure has VPN, allowlisting, identity-aware proxy, or
  equivalent protection. If publicly reachable, MFA is enabled.
- SSH uses authorized public keys; password authentication is disabled.
- PostgreSQL has no public listener/port and only required reverse-proxy ports
  are exposed.

## Platform and secrets

- Production and staging have separate databases, volumes, Meta bindings,
  session secrets, credentials, backup keys, and routes.
- HTTPS, encrypted volumes, encrypted off-host backups, firewall, log rotation,
  disk monitoring, certificate monitoring, and update ownership are verified.
- Secrets are Docker secrets or restricted root-owned files outside Git and
  images; backup keys are separate from backup data.
- Application docs are disabled and browser origins/cookies are HTTPS-only.

## Recovery and lifecycle

- Selected backup technology demonstrably meets daily full/base backup,
  one-hour RPO, four-hour RTO, and 30-day retention targets.
- Backup alerts and a successful isolated restore test are recorded.
- Retention dry run is reviewed, scheduled apply execution is monitored, and
  all configured values have project-owner approval.
- Incident contacts, escalation path, credential-rotation process, and
  operational schedule are complete.

## Release evidence

- Backend, frontend, integration, migration, and end-to-end tests pass.
- `docker compose config` and container health checks pass.
- `python -m app.commands.validate_deployment` returns no errors in the
  production environment.
- A release owner records the deployed revision, approval, backup timestamp,
  health results, and rollback decision.
