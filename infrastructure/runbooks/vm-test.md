# Internal VM test deployment

This deployment exists only for synthetic acceptance testing before the VM has
a stable address, DNS, HTTPS, backups, approved project content, or Meta phone
numbers. It must never process participant data.

The HTTP port binds to `127.0.0.1` on the VM by default. Operators reach it
through an authenticated SSH tunnel; it is not published on the VM's LAN
interface. PostgreSQL has no host port.

## Prepare the server

Install Docker Engine and its Compose plugin from Docker's official Debian
repository. Clone a reviewed repository revision into
`/opt/oncodir-oncoscreen` and keep the directory owned by the deployment user.

Generate root-owned secrets without displaying their values:

`sudo sh infrastructure/scripts/prepare-vm-test-secrets.sh`

The script creates:

- `/etc/oncodir-oncoscreen/vm-test/postgres-password`;
- `/etc/oncodir-oncoscreen/vm-test/application.json`;
- `/etc/oncodir-oncoscreen/vm-test/vm-test.env`.

It refuses to overwrite existing secrets. Do not copy these files into Git,
chat, command output, or the application directory.

## Validate and start

From `/opt/oncodir-oncoscreen`:

`sudo docker compose --env-file /etc/oncodir-oncoscreen/vm-test/vm-test.env --file infrastructure/compose.vm-test.yml config --quiet`

`sudo docker compose --env-file /etc/oncodir-oncoscreen/vm-test/vm-test.env --file infrastructure/compose.vm-test.yml up -d --build`

Inspect health without printing secrets:

`sudo docker compose --env-file /etc/oncodir-oncoscreen/vm-test/vm-test.env --file infrastructure/compose.vm-test.yml ps`

`curl --fail http://127.0.0.1:8080/api/v1/health/ready`

The deployment uses compiled frontend assets, the dependency-minimal backend
image, PostgreSQL with pgvector, Caddy, and a dedicated outbox worker. It has no
source bind mounts, hot reload, test dependencies, embedding model, or Meta
network calls.

## Bootstrap synthetic access

Create the first test administrator and record the generated credential only
in an approved temporary channel:

`sudo docker compose --env-file /etc/oncodir-oncoscreen/vm-test/vm-test.env --file infrastructure/compose.vm-test.yml exec backend python -m app.commands.bootstrap_admin --project ONCODIR --email <test-administrator-email>`

The administrator must change the password at first login. Create a synthetic
ticket if required:

`sudo docker compose --env-file /etc/oncodir-oncoscreen/vm-test/vm-test.env --file infrastructure/compose.vm-test.yml exec backend python -m app.commands.create_synthetic_ticket --project ONCODIR`

## Connect from Windows

Keep this PowerShell session open:

`ssh -N -L 8080:127.0.0.1:8080 -i "$env:USERPROFILE\.ssh\oncodir_vm" oncodir@<vm-address>`

Open `http://localhost:8080`. The browser communicates with the VM only
through the SSH tunnel. A request to `http://<vm-address>:8080` should fail
because the service is not bound to the LAN address.

## Update and stop

For a reviewed update, run `git pull --ff-only`, inspect the revision, then
repeat `up -d --build`. Migrations run before the API starts.

Stop containers without deleting the database volume:

`sudo docker compose --env-file /etc/oncodir-oncoscreen/vm-test/vm-test.env --file infrastructure/compose.vm-test.yml down`

Do not add `--volumes` unless synthetic test data is intentionally being
destroyed. Move to the HTTPS staging definition before any real Meta or
participant testing.
