# Release acceptance

This checklist produces evidence for a release decision; passing automated
tests is not by itself authorization to use real participant data.

## Automated gates

The CI workflow must pass:

- all backend unit, PostgreSQL integration, project-isolation, authentication,
  webhook, ticket, outbox, retention, and system-acceptance tests;
- Alembic model-versus-migration verification;
- frontend component/accessibility smoke tests and TypeScript production build;
- static production frontend image build;
- staging Compose and Caddy configuration validation;
- environment-separation manifest validation;
- a data-retention dry run.

The system-acceptance scenario uses synthetic data and covers:

1. authenticated and signed inbound WhatsApp webhook;
2. unknown-question escalation and privacy/fallback messages;
3. masked contact display and cross-project authorization denial;
4. operator claim, approved administrative reply, and resolution;
5. persistent outbox processing through the network-free mock provider.

## Manual functional acceptance

For each project configuration:

- log in, change a first-login password, log out, and confirm session expiry;
- verify project names/branding and that unauthorized projects never appear;
- claim/release a ticket, add an internal note, reply, wait, resolve, close,
  reopen where allowed, and verify administrator reassignment;
- verify a user reply to `WAITING_USER` and a reply within the resolved
  reopening window;
- verify unsupported media produces one warning in a short sequence and stores
  metadata only;
- verify the 24-hour window blocks free text and offers only approved templates;
- verify delivery errors and operations/audit visibility;
- verify exact FAQ matches and every uncertain/high-risk evaluation case
  escalates.

## Accessibility acceptance

The automated smoke test confirms the Romanian document structure, labelled
authentication controls, a main landmark, and keyboard skip navigation. Before
production, manually test:

- keyboard-only navigation, visible focus, modal/menu escape, and logical focus
  order;
- 200% zoom and narrow-screen reflow without lost controls;
- screen-reader headings, landmarks, forms, tables, notifications, status
  changes, and error recovery;
- Romanian wording, error clarity, and color contrast.

Record browser, assistive technology, version, tester, findings, and
remediation. The current automated checks are not a WCAG conformance claim.

## Security and privacy acceptance

- verify HTTPS, secure cookies, CSRF rejection, login throttling/lockout,
  session revocation, restricted production panel access, and MFA decision;
- inspect browser storage and confirm no session credential is in local or
  session storage;
- verify logs exclude query strings, bodies, phone numbers, message content,
  tokens, and exception text;
- test unknown phone IDs, invalid webhook signatures, duplicates, oversized
  payloads, and cross-project object identifiers;
- verify full phone access is limited and audited;
- confirm retention preview, encrypted off-host backup, restore evidence, and
  incident contacts.

## Decision

Record one outcome: accepted for synthetic staging, accepted for production
after all production prerequisites, or rejected with named remediation owners.
The release record must include the Git revision and must never contain
participant content or secret values.
