#!/bin/sh
set -u

repository_directory="${VM_TEST_REPOSITORY:-/opt/oncodir-oncoscreen}"
environment_file="${VM_TEST_ENV_FILE:-/etc/oncodir-oncoscreen/vm-test/vm-test.env}"
compose_file="$repository_directory/infrastructure/compose.vm-test.yml"
failures=0

fail() {
    failures=$((failures + 1))
    printf 'FAIL: %s\n' "$1" >&2
}

if ! systemctl is-active --quiet docker; then
    fail "Docker service is not active"
fi

root_usage="$(df -P / | awk 'NR == 2 { gsub(/%/, "", $5); print $5 }')"
if [ -z "$root_usage" ] || [ "$root_usage" -ge 80 ]; then
    fail "root filesystem usage is at or above 80% (${root_usage:-unknown}%)"
fi

if ! curl --fail --silent --show-error --max-time 5 \
    http://127.0.0.1:8080/api/v1/health/ready >/dev/null; then
    fail "application readiness endpoint does not respond"
fi

if [ ! -r "$environment_file" ] || [ ! -r "$compose_file" ]; then
    fail "deployment environment or Compose file is not readable"
else
    running_services="$(docker compose \
        --env-file "$environment_file" \
        --file "$compose_file" \
        ps --services --status running 2>/dev/null)"
    for service_name in postgres backend outbox-worker frontend caddy; do
        if ! printf '%s\n' "$running_services" | grep -qx "$service_name"; then
            fail "Compose service is not running: $service_name"
        fi
    done
fi

if [ "$failures" -ne 0 ]; then
    printf 'VM-test health check failed with %s error(s).\n' "$failures" >&2
    exit 1
fi

printf 'VM-test health check passed.\n'
