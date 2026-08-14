#!/bin/sh
set -eu

secret_directory="${1:-/etc/oncodir-oncoscreen/meta}"
secret_file="$secret_directory/whatsapp-webhook.json"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this command through sudo so the secret file is root-owned." >&2
    exit 1
fi
if ! command -v openssl >/dev/null 2>&1; then
    echo "openssl is required to generate the verification token." >&2
    exit 1
fi
if [ -e "$secret_file" ]; then
    echo "Refusing to overwrite the existing secret file: $secret_file" >&2
    exit 1
fi

install -d -m 0700 -o root -g root "$secret_directory"
umask 077
verify_token="$(openssl rand -hex 32)"
printf '{\n  "oncodir-meta-webhook": {\n    "verify_token": "%s"\n  }\n}\n' \
    "$verify_token" > "$secret_file"
chmod 0600 "$secret_file"

echo "Meta webhook secret created at $secret_file."
echo "Copy this Verify Token into Meta now; do not paste it into chat or commit it:"
printf '%s\n' "$verify_token"
