# Backup and restore runbook

The provisional production targets are a one-hour recovery point, a four-hour
recovery time, daily full backups, encrypted backup data, and 30-day retention.
Backups must use a destination separate from the application server, and the
encryption key must be stored separately from the backup data.

The exact backup product and remote destination are intentionally not selected
until the server and storage provider exist. A daily logical database dump
alone does not meet the one-hour recovery-point target.

## Required design

Select a PostgreSQL-compatible solution that provides:

- at least daily base/full backups;
- continuous WAL archiving or an equivalent incremental capture whose tested
  worst-case data loss is no more than one hour;
- encryption before or during transfer and at rest;
- an off-host destination with access isolated from the application host;
- automated failure and archive-lag alerts;
- integrity verification and documented point-in-time recovery;
- automatic 30-day expiry without deleting the only viable recovery chain.

PostgreSQL documents that base backups combined with archived write-ahead logs
support point-in-time recovery. It also notes that `pg_dump` is a logical
backup and cannot form part of WAL replay. See the official
[continuous archiving and PITR documentation](https://www.postgresql.org/docs/current/continuous-archiving.html)
and [SQL dump documentation](https://www.postgresql.org/docs/current/backup-dump.html).

## Implementation acceptance

Before production participant data:

1. record the selected tool, version, repository, credentials owner, encryption
   method, key location, schedule, and retention configuration;
2. demonstrate daily full/base backup plus incremental or WAL capture;
3. alert on backup failure, excessive archive lag, low local disk space, and
   inaccessible remote storage;
4. restrict backup credentials to the required destination and operations;
5. confirm staging and production use separate backup keys and locations;
6. set readiness confirmation flags only after evidence is recorded.

## Restore exercise

Perform restore tests in an isolated restore environment. Never restore
production participant data into ordinary staging.

1. choose an authorized backup and a target time;
2. provision an empty, isolated PostgreSQL instance with matching compatible
   software and extensions;
3. obtain the decryption key through the separate authorized path;
4. restore the base/full backup and replay incremental/WAL data to the target;
5. run database consistency checks, migrations/current-revision checks, and
   application readiness checks;
6. verify project isolation and representative record counts without copying
   sensitive values into the test report;
7. record start/end time, achieved recovery point, errors, and approver;
8. securely destroy the temporary restored environment and credentials.

The exercise passes only if the measured data-loss window is at most one hour
and service restoration completes within four hours. Record exceptions and
remediation; do not claim the targets solely because backups were created.
