# Incident response runbook

## Priorities

Protect participants, stop unauthorized access or unintended messaging,
preserve trustworthy evidence, restore safely, and document decisions. Do not
copy message content, phone numbers, credentials, or raw webhook payloads into
chat, tickets, or general-purpose logs.

## Response

1. Confirm the alert and appoint an incident lead and recorder.
2. Classify the affected environment, projects, data types, accounts,
   credentials, and time window.
3. Contain the incident with the least destructive control: restrict panel
   access, disable an account, stop the outbox worker, disable a Meta binding,
   or isolate the host as appropriate.
4. Preserve relevant structured logs, audit-event identifiers, deployment
   version, database timestamps, and backup status. Keep evidence access
   restricted.
5. Rotate exposed session, database, Meta, backup, email, or signing secrets.
   Revoking an operator or resetting a password must invalidate sessions.
6. Assess whether project leadership, clinical/privacy representatives,
   affected users, Meta, hosting providers, or authorities must be notified.
   Notification obligations require organizational/legal review.
7. Recover from a known-good version or backup, verify project isolation,
   readiness, outbox state, and webhook behavior, then restore access gradually.
8. Record the timeline, impact, decisions, evidence locations, and follow-up
   owners. Complete a blameless post-incident review.

## Specific containment notes

- Suspected incorrect automatic answers: disable semantic retrieval for the
  affected project or withdraw the FAQ version; preserve its version and
  evaluation evidence.
- Unexpected outbound messages: stop the outbox worker before stopping the API,
  inspect idempotency keys and delivery status, and coordinate credential
  rotation with Meta.
- Cross-project exposure: restrict panel access immediately, preserve relevant
  audit events and API deployment version, and treat it as a privacy incident.
- Backup compromise: revoke destination credentials, rotate the separately
  stored encryption key when appropriate, and establish a new clean backup
  chain.

The incident contact list and escalation tree must be filled with real,
approved names and out-of-band contact methods before production.
