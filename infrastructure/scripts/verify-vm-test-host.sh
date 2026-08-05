#!/bin/sh
set -u

failures=0
warnings=0

pass() { printf 'PASS: %s\n' "$1"; }
warn() { warnings=$((warnings + 1)); printf 'WARN: %s\n' "$1" >&2; }
fail() { failures=$((failures + 1)); printf 'FAIL: %s\n' "$1" >&2; }

check_service() {
    service_name="$1"
    if systemctl is-enabled --quiet "$service_name" && systemctl is-active --quiet "$service_name"; then
        pass "$service_name is enabled and active"
    else
        fail "$service_name must be enabled and active"
    fi
}

check_sshd_value() {
    key="$1"
    expected="$2"
    actual="$(printf '%s\n' "$sshd_effective" | awk -v key="$key" '$1 == key { print $2; exit }')"
    if [ "$actual" = "$expected" ]; then
        pass "SSH $key is $expected"
    else
        fail "SSH $key expected $expected, found ${actual:-missing}"
    fi
}

if [ "$(id -u)" -ne 0 ]; then
    printf 'Run through sudo so SSH, firewall, and secret permissions can be verified.\n' >&2
    exit 2
fi

for command_name in sshd systemctl ufw ss timedatectl apt-config stat df curl; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        fail "required command is missing: $command_name"
    fi
done
if [ "$failures" -ne 0 ]; then
    printf 'Host verification stopped: %s required command(s) missing.\n' "$failures" >&2
    exit 1
fi

if sshd -t; then pass "SSH configuration syntax is valid"; else fail "SSH configuration syntax is invalid"; fi
sshd_effective="$(sshd -T)"
check_sshd_value passwordauthentication no
check_sshd_value kbdinteractiveauthentication no
check_sshd_value permitemptypasswords no
check_sshd_value pubkeyauthentication yes
check_sshd_value permitrootlogin no
check_sshd_value x11forwarding no
check_sshd_value allowagentforwarding no
check_sshd_value allowtcpforwarding local
check_sshd_value permittunnel no
check_sshd_value maxauthtries 3

ufw_status="$(ufw status verbose)"
if printf '%s\n' "$ufw_status" | grep -q '^Status: active$'; then pass "UFW is active"; else fail "UFW is not active"; fi
if printf '%s\n' "$ufw_status" | grep -q 'Default: deny (incoming), allow (outgoing)'; then
    pass "UFW default policies deny inbound and allow outbound"
else
    fail "UFW default policies are not the expected deny-inbound/allow-outbound pair"
fi
if printf '%s\n' "$ufw_status" | grep -Eq '^22/tcp[[:space:]]+ALLOW( IN)?[[:space:]]+'; then
    pass "UFW has an inbound SSH allow rule"
else
    fail "UFW has no visible inbound SSH allow rule"
fi

check_service ssh
check_service docker
check_service ufw
check_service unattended-upgrades

if [ "$(timedatectl show -p NTPSynchronized --value)" = "yes" ]; then pass "system clock is synchronized"; else fail "system clock is not synchronized"; fi

apt_configuration="$(apt-config dump)"
if printf '%s\n' "$apt_configuration" | grep -q 'APT::Periodic::Unattended-Upgrade "1";'; then
    pass "daily unattended upgrades are configured"
else
    fail "daily unattended upgrades are not configured"
fi
if printf '%s\n' "$apt_configuration" | grep -q 'Unattended-Upgrade::Automatic-Reboot "false";'; then
    pass "automatic reboot after upgrades is disabled"
else
    fail "automatic reboot policy is not explicitly disabled"
fi

listening_addresses="$(ss -lntH | awk '{print $4}')"
if printf '%s\n' "$listening_addresses" | grep -Eq '(^|:)5432$'; then fail "PostgreSQL port 5432 is published on the host"; else pass "PostgreSQL is not published on the host"; fi
if printf '%s\n' "$listening_addresses" | grep -q '^127\.0\.0\.1:8080$'; then pass "VM-test HTTP is bound to IPv4 loopback"; else fail "VM-test HTTP is not listening on 127.0.0.1:8080"; fi
non_loopback_http="$(printf '%s\n' "$listening_addresses" | grep ':8080$' | grep -v '^127\.0\.0\.1:8080$')"
if [ -n "$non_loopback_http" ]; then fail "VM-test HTTP port 8080 is exposed beyond IPv4 loopback"; else pass "VM-test HTTP port 8080 has no non-loopback listener"; fi

secret_directory="/etc/oncodir-oncoscreen/vm-test"
for secret_file in postgres-password application.json vm-test.env; do
    secret_path="$secret_directory/$secret_file"
    if [ ! -f "$secret_path" ]; then fail "required deployment file is missing: $secret_path"; continue; fi
    ownership_and_mode="$(stat -c '%U:%G:%a' "$secret_path")"
    if [ "$ownership_and_mode" = "root:root:600" ]; then pass "$secret_file is root-owned with mode 600"; else fail "$secret_file permissions expected root:root:600, found $ownership_and_mode"; fi
done

root_usage="$(df -P / | awk 'NR == 2 { gsub(/%/, "", $5); print $5 }')"
if [ -n "$root_usage" ] && [ "$root_usage" -lt 80 ]; then pass "root filesystem usage is below 80% (${root_usage}%)"; else fail "root filesystem usage is at or above 80% (${root_usage:-unknown}%)"; fi

if curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8080/api/v1/health/ready >/dev/null; then pass "application readiness endpoint responds"; else fail "application readiness endpoint does not respond"; fi

if [ -f /var/run/reboot-required ]; then warn "the operating system reports that a controlled reboot is required"; else pass "no operating-system reboot is currently required"; fi

printf 'Summary: %s failure(s), %s warning(s).\n' "$failures" "$warnings"
[ "$failures" -eq 0 ]
