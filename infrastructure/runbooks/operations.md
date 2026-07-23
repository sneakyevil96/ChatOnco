# Operations runbook

This runbook covers the team-managed Linux host for the shared ONCODIR and
ONCOSCREEN platform. The retention, availability, and recovery values are
provisional engineering defaults until the project owners approve them for
real participant data.

## Responsibilities

The development/project team owns:

- operating-system, Docker, image, and dependency security updates;
- firewall rules, SSH public-key access, and disabling password-based SSH;
- HTTPS certificate renewal monitoring;
- database availability, encrypted off-host backups, and restore tests;
- deployment secrets and Meta credential rotation;
- application, webhook, outbox, disk-space, and backup-success monitoring;
- log rotation, vulnerability review, incident response, and evidence keeping;
- operator account administration and project memberships;
- scheduled data-retention execution and review.

Only the reverse proxy may expose public ports. PostgreSQL must not be
published. Restrict the production operator panel with a VPN, IP allowlist,
identity-aware proxy, or reverse-proxy authentication where practical. A
publicly reachable production panel requires MFA before real participant data
is used.

## Routine cadence

Daily:

- review service/database health, disk use, certificate status, webhook
  failures, terminal outbox failures, and backup alerts;
- confirm the outbox worker is running and no delivery item is stale;
- review security and authentication alerts.

Weekly:

- apply the normal OS and dependency update process after staging validation;
- review operator accounts, project memberships, and unusual audit events;
- verify log rotation and backup capacity.

Monthly:

- run a documented restore exercise with synthetic data;
- review and rotate secrets that are due;
- review vulnerabilities, firewall rules, SSH keys, and incident contacts;
- confirm retention settings still match the documented provisional policy.

## Retention

Preview all configured projects and security-state cleanup without changing
data:

`docker compose exec backend python -m app.commands.run_retention`

Preview one project:

`docker compose exec backend python -m app.commands.run_retention --project ONCODIR`

Apply the configured policies:

`docker compose exec backend python -m app.commands.run_retention --apply`

The command is deliberately a dry run unless `--apply` is supplied. Schedule
the apply form on the production host only after a successful encrypted backup
and a reviewed dry-run result. Monitor its exit status and aggregate JSON
result. Run it repeatedly until all batch-limited counts are zero when a large
backlog is first cleaned.

Message content is redacted after the project-specific message-content period.
Old ticket and conversation records are later deleted according to the
project's ticket period. Pending or processing outbox payloads retain the
minimum content needed to preserve an accepted delivery intent; they become
eligible for redaction after reaching a terminal state. Cleanup events contain
aggregate counts, not message content.

## Deployment checks

Before a production release:

1. validate staging tests, migrations, and the production-like deployment;
2. complete the production-readiness checklist;
3. run `python -m app.commands.validate_deployment` in the deployment
   environment;
4. confirm a current backup and tested rollback procedure;
5. deploy, then check liveness, readiness, worker logs, webhook delivery, and
   the administrator operations page.

The validation command checks declared application and operational
preconditions. It cannot prove firewall, encryption, backup, or access-proxy
configuration; an authorized operator must verify those controls before
setting their confirmation flags.
