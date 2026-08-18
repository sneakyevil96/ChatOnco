#!/bin/sh
set -eu

secret_directory="${1:-/etc/oncodir-oncoscreen/vm-test}"
compose_project_name="${VM_TEST_COMPOSE_PROJECT_NAME:-screening-platform-vm-test}"

case "$compose_project_name" in
    *[!a-z0-9_-]* | "")
        echo "VM_TEST_COMPOSE_PROJECT_NAME must contain only lowercase letters, digits, underscores, or hyphens." >&2
        exit 1
        ;;
esac

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this command through sudo so the secret files are root-owned." >&2
    exit 1
fi
if ! command -v openssl >/dev/null 2>&1; then
    echo "openssl is required to generate deployment secrets." >&2
    exit 1
fi

postgres_password_file="$secret_directory/postgres-password"
application_secret_file="$secret_directory/application.json"
environment_file="$secret_directory/vm-test.env"

if [ -e "$postgres_password_file" ] || [ -e "$application_secret_file" ]; then
    echo "Refusing to overwrite existing VM-test secrets in $secret_directory." >&2
    exit 1
fi

install -d -m 0700 -o root -g root "$secret_directory"
umask 077
postgres_password="$(openssl rand -hex 32)"
csrf_signing_key="$(openssl rand -hex 48)"
security_hash_key="$(openssl rand -hex 48)"

printf '%s\n' "$postgres_password" > "$postgres_password_file"
printf '{\n  "database_url": "postgresql+psycopg://screening_vm_test:%s@postgres:5432/screening_vm_test",\n  "csrf_signing_key": "%s",\n  "security_hash_key": "%s"\n}\n' \
    "$postgres_password" \
    "$csrf_signing_key" \
    "$security_hash_key" > "$application_secret_file"
printf 'VM_TEST_COMPOSE_PROJECT_NAME=%s\nVM_TEST_BIND_ADDRESS=127.0.0.1\nVM_TEST_PORT=8080\nVM_TEST_LOG_LEVEL=INFO\nVM_TEST_POSTGRES_PASSWORD_FILE=%s\nVM_TEST_APPLICATION_SECRET_FILE=%s\n' \
    "$compose_project_name" \
    "$postgres_password_file" \
    "$application_secret_file" > "$environment_file"

chmod 0600 "$postgres_password_file" "$application_secret_file" "$environment_file"
echo "VM-test secret files created under $secret_directory. Secret values were not displayed."
echo "Compose environment file: $environment_file"
