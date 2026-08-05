# VM-test maintenance, restart, and rollback

This procedure applies only to the synthetic VM-test deployment. Use the
production release, backup, and incident procedures before real participant
data is introduced.

## Reviewed update

1. Confirm the target commit passed CI and record the current commit with
   `git rev-parse HEAD`.
2. Confirm the working tree is clean with `git status --short`.
3. Run the host checker and confirm a successful application readiness check.
4. Pull only a fast-forward update with `git pull --ff-only`.
5. Review the new commit with `git log -1 --oneline`.
6. Validate Compose before building.
7. Run `up -d --build`, inspect service health, and repeat the host checker.

From `/opt/oncodir-oncoscreen`, use the deployment-owned environment file:

`sudo docker compose --env-file /etc/oncodir-oncoscreen/vm-test/vm-test.env --file infrastructure/compose.vm-test.yml config --quiet`

`sudo docker compose --env-file /etc/oncodir-oncoscreen/vm-test/vm-test.env --file infrastructure/compose.vm-test.yml up -d --build`

Never run `down --volumes` during an update. Database migrations run before
the API starts. A schema migration may make application rollback unsafe, so
review migrations and take an appropriate backup before any non-synthetic
deployment.

## Controlled restart

Do not reboot a DHCP-addressed VM unless the post-reboot address is known or
an authorized administrator has hypervisor console access.

Before reboot:

1. notify current testers and stop interactive acceptance work;
2. record `ip -br address`, `git rev-parse HEAD`, and service status;
3. run `sudo sh infrastructure/scripts/verify-vm-test-host.sh`;
4. confirm `ssh`, `ufw`, and `docker` are enabled;
5. confirm no update, backup, or administrative command is running.

Issue `sudo systemctl reboot` from the VM. After the host returns, establish a
new key-only SSH session and verify:

- the expected address and host-key fingerprint;
- `ssh`, `ufw`, `docker`, and `unattended-upgrades` are active;
- all Compose services are running and health checks pass;
- `curl --fail http://127.0.0.1:8080/api/v1/health/ready` succeeds;
- the operator panel remains reachable only through the SSH tunnel;
- PostgreSQL has no host listener.

Run the host verification script as the final check.

## Application rollback

Rollback is an incident decision, not an automatic `git reset`. Preserve logs
and record the failed and target revisions. Determine first whether the failed
release applied a database migration.

If no incompatible migration was applied, check out a reviewed release tag or
commit in a separate clean deployment worktree, validate its Compose model,
and rebuild from that revision. Do not overwrite deployment secrets and do not
delete the PostgreSQL volume.

If an incompatible migration was applied, stop and follow the database restore
procedure. Restore into an isolated environment first, validate the target
application and schema together, and only then approve service restoration.
Never improvise a schema downgrade or restore production data into staging.

After either path, verify readiness, worker operation, ticket access, audit
events, and outbound delivery state; then document the incident and recovery
point.
