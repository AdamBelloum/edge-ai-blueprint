"""Beginner practical: authenticated URL shortening with JSON persistence.

Run step by step:
1. From the parent containerization directory, follow setup_local_keys.sh
   instructions to prepare keys and copy the public key to this service.
2. On your assigned Docker-capable host, run:
       docker compose up --build -d
3. Create a user and log in through the authentication service on host
   port 5001 by default. Keep the returned token private.
4. Send protected requests to the shortener on host port 5000 by default
   with the header: Authorization: Bearer <token>
   Replace <token> with your login token; do not include angle brackets.
   The alternative x-access-token header is also accepted.
5. Follow docker-compose.yml instructions to test data persistence.
   Use configured host ports if you override the defaults.

API overview:
- GET /: list the authenticated user's IDs (200).
- POST /: create a mapping using JSON {"url": "https://example.org"}
  or the alternative "value" field; return its ID (201).
- GET /<id>: public redirect (301), or missing ID (404); no token required.
- PUT /<id>: owner-only update using JSON with a "url" field (200).
- DELETE /<id>: owner-only removal (204).
- DELETE /: remove this user's mappings; currently returns 404 even
  after successful deletion. This documents existing behaviour.
Protected routes return 403 when authentication fails.
POST and PUT expect JSON objects but do not explicitly validate the
parsed JSON type. Some non-object inputs can cause server errors
rather than the documented 400 responses for rejected fields.

Storage and security:
Paths are relative to this file, not the shell's working directory.
data/urls.json maps IDs to objects containing "url" and "owner".
Compose mounts persistent storage at /app/data and a read-only public
verification key at /app/keys. Never supply the private signing key.
Requests reload storage; writes replace the JSON file without locking
or atomic replacement. This is not safe concurrent multi-writer storage.

JWT verification uses RSA PKCS#1 v1.5 with SHA-256, checks expiration
and subject presence, and returns no user on verification errors.
This teaching implementation is not a complete production JWT validator.
URL validation checks only the http:// or https:// prefix.
The Flask development server is for the practical, not production hosting.
"""

from flask import Flask, jsonify, request, redirect
import hashlib
import json
import base64
import time
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.exceptions import InvalidSignature


app = Flask(__name__)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_KEY_FILE = os.path.join(BASE_DIR, "keys", "public_key.pem")
DATA_FILE = os.path.join(BASE_DIR, "data", "urls.json")

def ensure_parent_dir(path):
    """Create the parent directory of a file path if needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)

def load_urls():
    """Load stored URL mappings into the global shared_dict.

    Create an empty JSON object only when storage is missing.
    Raise RuntimeError for unreadable JSON or a non-object root;
    do not silently reset existing data. Individual records are
    not schema-validated here."""
    global shared_dict
    ensure_parent_dir(DATA_FILE)

    # Initialise missing storage, but never overwrite an existing file.
    if not os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "x", encoding="utf-8") as stream:
                json.dump({}, stream)
        except FileExistsError:
            pass

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as stream:
            loaded = json.load(stream)
    except (OSError, ValueError) as error:
        raise RuntimeError(
            f"Cannot load persisted data from {DATA_FILE}; "
            "inspect the file before continuing."
        ) from error

    if not isinstance(loaded, dict):
        raise RuntimeError(
            f"Invalid persisted data in {DATA_FILE}: expected a JSON object."
        )

    shared_dict = loaded

def save_urls():
    """Write the current shared_dict to DATA_FILE as formatted JSON.

    Replace the file contents; filesystem errors propagate.
    No locking or atomic replacement is provided, so concurrent
    writers can lose updates."""
    ensure_parent_dir(DATA_FILE)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(shared_dict, f, indent=2)

def is_it_an_url(string):
    """Return True for strings starting with http:// or https://.

    This prefix check does not validate the hostname or URL reachability."""
    return isinstance(string, str) and (
        string.startswith("http://") or string.startswith("https://")
    )


def generate_short_id(url):
    """Return six hexadecimal characters from the URL's MD5 digest.

    This deterministic identifier is not a security hash and can collide.
    The creation handler separately resolves conflicts in stored mappings."""
    return hashlib.md5(url.encode()).hexdigest()[:6]


def base64url_decode(data):
    """Restore omitted Base64 padding and decode a URL-safe string to bytes.

    Used for JWT segments; decoding alone does not verify authenticity."""
    padding_needed = 4 - (len(data) % 4)
    if padding_needed != 4:
        data += "=" * padding_needed
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def load_public_key():
    """Load the PEM verification key from PUBLIC_KEY_FILE.

    Return the deserialized public key; file and parsing errors propagate.
    setup_local_keys.sh copies this key from the authentication service.
    No private signing key is needed by the shortener."""
    with open(PUBLIC_KEY_FILE, "rb") as f:
        return serialization.load_pem_public_key(f.read())


def get_token_from_request():
    """Extract a token from the active Flask request, or return None.

    Prefer an Authorization header starting with the exact text
    'Bearer '; otherwise try x-access-token. Strip surrounding
    token whitespace. Extraction does not verify the token."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1].strip()

    token = request.headers.get("x-access-token")
    if token:
        return token.strip()

    return None


def verify_jwt(token):
    """Return the signed subject claim, or None when verification fails.

    Require three token segments and verify their signature using
    the local public key with RSA PKCS#1 v1.5 and SHA-256.
    Require exp and sub; reject when current integer time exceeds exp.
    All caught errors, including key-loading errors, return None.
    The JWT header, issuer, audience, and subject type are not validated;
    this is a teaching implementation, not a complete JWT validator."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, signature_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        signature = base64url_decode(signature_b64)

        public_key = load_public_key()
        public_key.verify(
            signature,
            signing_input,
            padding.PKCS1v15(),
            hashes.SHA256()
        )

        payload = json.loads(base64url_decode(payload_b64).decode("utf-8"))

        if "exp" not in payload or int(time.time()) > int(payload["exp"]):
            return None

        if "sub" not in payload:
            return None

        return payload["sub"]

    except (InvalidSignature, ValueError, KeyError, json.JSONDecodeError):
        return None
    except Exception:
        return None


def get_current_user():
    """Extract and verify this request's token to obtain its subject.

    Return None for a missing or invalid token. No user-database lookup
    is performed; route handlers use the subject for ownership checks."""
    token = get_token_from_request()
    if not token:
        return None
    return verify_jwt(token)


@app.route("/", methods=["GET"])
def read_root():
    """Handle GET /: list IDs owned by the authenticated user.

    Reload stored mappings before checking the token.
    Return JSON with a keys list and status 200, or 403 when
    authentication fails. An empty list is a successful response."""
    load_urls()
    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    # only return the keys owned by the current user
    user_keys = [key for key, value in shared_dict.items() if value["owner"] == username]
    return jsonify({"keys": user_keys}), 200


@app.route("/<id>", methods=["GET"])
def read_item(id):
    """Handle GET /<id>: publicly redirect to a stored destination.

    Reload mappings and return a permanent redirect (301) when
    the ID exists, otherwise a JSON error (404).
    No token or ownership check is required; anyone who knows
    the ID can follow it. Clients may cache permanent redirects."""
    load_urls()
    value = shared_dict.get(id)

    if value is not None:
        # public endpoint for redirection, no need to check ownership here
        return redirect(value["url"], code=301)
    else:
        return jsonify({"detail": "Key not found in shared dictionary"}), 404


@app.route("/", methods=["DELETE"])
def delete_root():
    """Handle DELETE /: remove all mappings owned by this user.

    Reload storage and return 403 when authentication fails.
    Otherwise remove only this user's entries and save the result.
    The current implementation returns a confirmation with status
    404 even after successful deletion; this is existing behaviour,
    not a recommended success status."""
    load_urls()
    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    # only delete the entries owned by the current user
    ids_to_delete = [key for key, value in shared_dict.items() if value["owner"] == username]
    for key in ids_to_delete:
        del shared_dict[key]
    save_urls()

    return jsonify({"detail": "All your shortened URLs have been deleted"}), 404


@app.route("/<id>", methods=["DELETE"])
def delete_item(id):
    """Handle DELETE /<id>: remove one mapping owned by this user.

    Reload storage and require authentication (otherwise 403).
    Return 404 for an unknown ID or 403 for another user's mapping.
    On success, save the remaining mappings and return an empty
    response with status 204."""
    load_urls()
    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    if id not in shared_dict:
        return jsonify({"detail": "Key not found in shared dictionary"}), 404

    if shared_dict[id]["owner"] != username:
        return jsonify({"detail": "forbidden"}), 403

    del shared_dict[id]
    save_urls()
    return "", 204


@app.route("/", methods=["POST"])
def create_root():
    """Handle POST /: create or reuse a mapping for this user.

    Reload storage and require authentication (otherwise 403).
    Expect a JSON object containing 'value', or 'url' when 'value'
    is absent or null. Return 400 for missing or rejected input.
    Convert the destination to a string and check its HTTP(S) prefix.
    Reuse an existing ID only when destination and owner both match;
    otherwise derive another candidate without replacing ownership.
    Save the mapping and return JSON containing its ID with status 201,
    including when an existing mapping is reused."""
    load_urls()
    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    data = request.get_json(silent=True)

    if not data:
        return jsonify({"detail": "error"}), 400

    long_url = data.get("value")
    if long_url is None:
        long_url = data.get("url")

    if not long_url:
        return jsonify({"detail": "error"}), 400

    if not is_it_an_url(str(long_url)):
        return jsonify({"detail": "error"}), 400

    short_id = generate_short_id(str(long_url))

    # Reuse an ID only when both the URL and its owner match.
    # A different user must never overwrite an existing mapping's ownership.
    while short_id in shared_dict and (
        shared_dict[short_id]["url"] != str(long_url)
        or shared_dict[short_id]["owner"] != username
    ):
        short_id = hashlib.md5((str(long_url) + short_id).encode()).hexdigest()[:6]

    shared_dict[short_id] = {
        "url": str(long_url),
        "owner": username
    }
    save_urls()

    return jsonify({"id": short_id}), 201


@app.route("/<id>", methods=["PUT"])
def update_item(id):
    """Handle PUT /<id>: change the destination of an owned mapping.

    Reload storage and require authentication (otherwise 403).
    Attempt JSON parsing regardless of the request content type.
    Return 404 for an unknown ID or 403 for another user's mapping.
    Require a JSON object with 'url' and an HTTP(S)-prefixed value;
    rejected input returns 400. Save the new destination under the
    same ID and owner, then return a confirmation with status 200."""
    load_urls()
    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    data = request.get_json(force=True, silent=True)

    if id not in shared_dict:
        return jsonify({"detail": "id doesn't exist"}), 404

    if shared_dict[id]["owner"] != username:
        return jsonify({"detail": "forbidden"}), 403

    if not data or "url" not in data:
        return jsonify({"detail": "error"}), 400

    if is_it_an_url(str(data["url"])) is False:
        return jsonify({"detail": "error"}), 400

    shared_dict[id]["url"] = str(data["url"])
    save_urls()
    return jsonify({"message": "Item updated successfully"}), 200


if __name__ == "__main__":
    load_urls()
    app.run(host="0.0.0.0", port=5000, debug=False)
