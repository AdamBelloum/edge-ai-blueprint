#!/usr/bin/env bash
# Prepare participant-local RSA key material for this Module 2 track.
#
# The authentication service owns the private signing key. The shortener
# receives only the public verification key.

set -euo pipefail

track_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
auth_dir="$track_root/auth_service"
shortener_dir="$track_root/shortener_service"

mkdir -p "$auth_dir/keys" "$shortener_dir/keys"

(
  cd "$auth_dir"
  python -c 'import auth; auth.ensure_keys_exist()'
)

chmod 0600 "$auth_dir/keys/private_key.pem"
chmod 0644 "$auth_dir/keys/public_key.pem"

cp "$auth_dir/keys/public_key.pem" \
  "$shortener_dir/keys/public_key.pem"
chmod 0644 "$shortener_dir/keys/public_key.pem"

printf '%s\n' \
  'Generated participant-local authentication keys.' \
  'Copied only auth_service/keys/public_key.pem to shortener_service/keys/.'
