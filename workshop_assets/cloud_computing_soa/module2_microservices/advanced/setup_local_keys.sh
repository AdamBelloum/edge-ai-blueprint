#!/usr/bin/env bash
# Prepare participant-local RSA key material for this Module 2 track.
#
# The authentication service owns the private signing key. The shortener
# receives only the public verification key.

# Use an environment with Flask and cryptography installed.
# Stop on command failures, unset variables, or failed pipelines.
set -euo pipefail

# Resolve paths from this script, not the caller's working directory.
track_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
auth_dir="$track_root/auth_service"
shortener_dir="$track_root/shortener_service"

# The Python key-generation function expects these directories to exist.
mkdir -p "$auth_dir/keys" "$shortener_dir/keys"

# Importing auth does not start Flask: its main guard prevents startup.
# Run from auth_service/ because its key paths are relative.
# Advanced participants must first implement ensure_keys_exist().
# The completed implementation reuses both existing files; if either
# is missing, it replaces the pair. This does not check key-pair validity.
(
  cd "$auth_dir"
  python -c 'import auth; auth.ensure_keys_exist()'
)

# Restrict the unencrypted private key after generation or reuse.
# These permissions are applied here, not by the Python key writer.
chmod 0600 "$auth_dir/keys/private_key.pem"
chmod 0644 "$auth_dir/keys/public_key.pem"

# Refresh the verification copy on every successful run.
# Never copy the private key to the shortener or commit generated keys.
cp "$auth_dir/keys/public_key.pem" \
  "$shortener_dir/keys/public_key.pem"
chmod 0644 "$shortener_dir/keys/public_key.pem"

# The message below is also printed when existing keys were reused.
printf '%s\n' \
  'Generated participant-local authentication keys.' \
  'Copied only auth_service/keys/public_key.pem to shortener_service/keys/.'
