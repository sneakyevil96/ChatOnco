# Staging runbook

Staging is a production-like environment for synthetic data only. It must not
contain copied production databases, participant messages, real medical
documents, or production credentials.

## Before provisioning

Assign unique staging identities for:

- PostgreSQL database and volume;
- project configuration;
- application signing/hash secrets;
- Meta test credentials and phone number, if used;
- backup destination and encryption key;
- public hostname and reverse-proxy route.

Record the identities in an environment manifest and compare it with the
production manifest:

`python -m app.commands.validate_environment_separation --staging <staging-manifest> --production <production-manifest>`

The manifests contain identifiers, not secret values. The validator rejects
shared protected resources and a staging configuration that permits
participant data.

## Secret files

Create root-owned files outside Git:

- a PostgreSQL password file containing only the password;
- an application JSON file containing exactly `database_url`,
  `csrf_signing_key`, and `security_hash_key`.

Use independent random values. The database URL must contain the same staging
password and database selected for PostgreSQL. Set owner-only permissions,
record the authorized custodian, and never copy either file into the image,
frontend, runbook, or environment manifest.

Copy `infrastructure/staging.env.example` to a root-owned deployment location
and point it at those files. The example contains no usable secret.

## Deployment

From a reviewed repository revision:

`docker compose --env-file <staging-env-file> --file infrastructure/compose.staging.yml config`

`docker compose --env-file <staging-env-file> --file infrastructure/compose.staging.yml up -d --build`

The staging definition uses:

- a compiled static frontend image rather than the Vite development server;
- the production backend image and migrations;
- a dedicated worker, PostgreSQL volume, and Caddy state;
- HTTPS and secure browser cookies;
- the mock WhatsApp provider unless a separately approved Meta test setup is
  available.

Bootstrap a staging administrator through the server-side command, immediately
change the temporary password, and create only synthetic tickets/FAQ content.
The local synthetic-ticket command intentionally refuses to run in staging;
staging fixtures must enter through an approved acceptance setup or Meta test
number so they exercise production-like boundaries.

## Acceptance and teardown

Run the release-acceptance checklist. Record the revision, environment
manifest, migration revision, test results, browser/accessibility results,
security review, and approver.

If staging and production initially share a physical host, confirm separate
containers, databases, credentials, session secrets, Meta bindings, backup
keys, storage volumes, and proxy routes. A staging compromise must not grant
access to any production resource.
