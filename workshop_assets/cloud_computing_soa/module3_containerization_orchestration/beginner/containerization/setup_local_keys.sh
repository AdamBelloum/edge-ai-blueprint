#!/usr/bin/env bash
# Prepare participant-local RSA key material for this Module 3 practical.
#
# The authentication service owns the private signing key. The shortener
# receives only the public verification key.

# Beginner steps (run from this containerization directory):
# 1. Activate a Python virtual environment for this practical.
# 2. Install the dependencies into that same environment:
#      python -m pip install -r auth_service/requirements.txt
#    Importing auth.py requires Flask and cryptography; it does not start
#    the web server or load user data.
# 3. Inspect auth_service/keys/ before running this script.
#    - Neither key exists: continue to generate a new pair.
#    - Both keys exist: the script preserves them.
#    - Only one key exists: stop and inspect/recover the matching pair.
#      Continuing regenerates BOTH keys, replacing the remaining key.
#      Tokens signed with the previous private key will no longer verify
#      against the new public key.
# 4. Run:
#      bash setup_local_keys.sh
# 5. Check the output and file permissions; do not print private-key contents:
#      ls -l auth_service/keys/ shortener_service/keys/
#    Expected: private_key.pem in auth_service only, with mode 0600;
#    public_key.pem in both services, with mode 0644.
#
# Never commit or distribute private signing keys. The script copies only
# the public key to the shortener and replaces its existing public-key copy.
#
set -euo pipefail
umask 077

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
