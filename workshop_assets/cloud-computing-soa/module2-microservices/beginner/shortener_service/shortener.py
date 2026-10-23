"""Beginner multi-user URL shortener for Module 2.

Run from shortener_service/ after running ../setup_local_keys.sh.
Listens on participant-local 127.0.0.1:5000 when executed directly.
Mappings are process-local and disappear on restart.

Management routes verify tokens locally using the copied public key;
GET /<id> redirects publicly. No live authentication-service lookup occurs.
This is teaching code, not a production-ready JWT verifier or web server."""

from flask import Flask, jsonify, request, redirect
import hashlib
import json
import base64
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.exceptions import InvalidSignature


app = Flask(__name__)

# original: shared_dict[id] = url
# updated: shared_dict[id] = {"url": xxx, "owner": username}
shared_dict = {}

PUBLIC_KEY_FILE = "keys/public_key.pem"


def is_it_an_url(string):
    """Check only that a string starts with http:// or https://.

    This is a lightweight exercise check, not comprehensive URL validation."""
    return isinstance(string, str) and (
        string.startswith("http://") or string.startswith("https://")
    )


def generate_short_id(url):
    """Derive a deterministic six-character ID from the URL.

    MD5 is used for a compact identifier, not as a security mechanism.
    Different URLs can collide; create_root handles that case separately."""
    return hashlib.md5(url.encode()).hexdigest()[:6]


def base64url_decode(data):
    """Restore missing JWT padding and decode a Base64url component to bytes."""
    padding_needed = 4 - (len(data) % 4)
    if padding_needed != 4:
        data += "=" * padding_needed
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def load_public_key():
    """Load the authentication service's copied public key.

    The relative path requires running from shortener_service/.
    The private signing key must never be copied here."""
    with open(PUBLIC_KEY_FILE, "rb") as f:
        return serialization.load_pem_public_key(f.read())


def get_token_from_request():
    """Read a Bearer token, falling back to the x-access-token header.

    Return None when neither supported header supplies a token."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1].strip()

    token = request.headers.get("x-access-token")
    if token:
        return token.strip()

    return None


def verify_jwt(token):
    """Verify the signature and return the payload subject, or None on failure.

    Verification always uses RSA PKCS#1 v1.5 with SHA-256. This example does
    not parse or validate the JWT header, issuer, audience, or subject type.
    It requires exp and sub, and rejects exp only when current time exceeds it.
    Any verification or key-loading exception becomes an authentication failure.

    There is no live user lookup or revocation check: changing a password
    does not invalidate a token while its signature and expiry remain accepted."""
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
    """Extract and verify the request token; return its subject or None."""
    token = get_token_from_request()
    if not token:
        return None
    return verify_jwt(token)


@app.route("/", methods=["GET"])
def read_root():
    """List only the authenticated user's mapping IDs; reject missing/invalid tokens."""
    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    # only return the keys owned by the current user
    user_keys = [key for key, value in shared_dict.items() if value["owner"] == username]
    return jsonify({"keys": user_keys}), 200


@app.route("/<id>", methods=["GET"])
def read_item(id):
    """Publicly redirect an existing ID with HTTP 301, or return 404.

    Resolution does not require a JWT or an ownership check."""
    value = shared_dict.get(id)

    if value is not None:
        # public endpoint for redirection, no need to check ownership here
        return redirect(value["url"], code=301)
    else:
        return jsonify({"detail": "Key not found in shared dictionary"}), 404


@app.route("/", methods=["DELETE"])
def delete_root():
    """Delete only mappings owned by the authenticated user.

    Successful bulk deletion returns 404 under the existing assignment
    contract; this is not conventional REST success semantics."""
    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    # only delete the entries owned by the current user
    ids_to_delete = [key for key, value in shared_dict.items() if value["owner"] == username]
    for key in ids_to_delete:
        del shared_dict[key]

    return jsonify({"detail": "All your shortened URLs have been deleted"}), 404


@app.route("/<id>", methods=["DELETE"])
def delete_item(id):
    """Delete an owned mapping with 204.

    Return 403 for authentication/ownership failure or 404 for an unknown ID."""
    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    if id not in shared_dict:
        return jsonify({"detail": "Key not found in shared dictionary"}), 404

    if shared_dict[id]["owner"] != username:
        return jsonify({"detail": "forbidden"}), 403

    del shared_dict[id]
    return "", 204


@app.route("/", methods=["POST"])
def create_root():
    """Create a mapping from JSON value, falling back to url.

    Require authentication and return the generated ID with 201.
    Collision handling rehashes until the ID is free, or already holds the
    same URL for the same owner, so another user's mapping is never
    overwritten."""
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

    return jsonify({"id": short_id}), 201


@app.route("/<id>", methods=["PUT"])
def update_item(id):
    """Update an owned mapping's URL while retaining its existing ID.

    Return 403 for authentication/ownership failure, 404 for an unknown ID,
    400 for invalid input, or 200 on success. JSON parsing is forced even
    without the usual content-type header."""
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
    return jsonify({"message": "Item updated successfully"}), 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
