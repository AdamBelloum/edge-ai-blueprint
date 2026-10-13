# Module 2 reference URL shortener; educational, not production-ready.
# Run ../setup_local_keys.sh first, then start Python from shortener_service/.
# Direct execution uses localhost:5000 with workshop-only Flask debug mode.
# Mappings are process-local and disappear on restart.
# Management routes use locally verified JWTs; redirects are public.
# Only the authentication public key belongs in this service.
# Known limitation: submitting another user's identical URL can take ownership.

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


# Check only type and HTTP(S) prefix, not full URL syntax or safety.
def is_it_an_url(string):
    return isinstance(string, str) and (
        string.startswith("http://") or string.startswith("https://")
    )


# Use six MD5 hexadecimal characters as a compact, non-security identifier.
def generate_short_id(url):
    return hashlib.md5(url.encode()).hexdigest()[:6]


# Restore omitted padding before decoding a JWT segment.
def base64url_decode(data):
    padding_needed = 4 - (len(data) % 4)
    if padding_needed != 4:
        data += "=" * padding_needed
    return base64.urlsafe_b64decode(data.encode("utf-8"))


# Read the copied PEM verification key relative to the working directory.
def load_public_key():
    with open(PUBLIC_KEY_FILE, "rb") as f:
        return serialization.load_pem_public_key(f.read())


# Prefer Authorization: Bearer; otherwise accept x-access-token.
def get_token_from_request():
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1].strip()

    token = request.headers.get("x-access-token")
    if token:
        return token.strip()

    return None


# Verify the signature locally with fixed RSA PKCS#1 v1.5/SHA-256.
# Require exp and sub, but do not validate header, issuer, audience,
# issued-at time, or subject type. No account lookup or revocation occurs.
# The expiration comparison accepts the exact expiration second.
# Failures, including key-loading errors, are returned as no valid user.
def verify_jwt(token):
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


# Extract and verify a token; return its subject or None on failure.
def get_current_user():
    token = get_token_from_request()
    if not token:
        return None
    return verify_jwt(token)


# List only mapping IDs whose recorded owner matches the token subject.
@app.route("/", methods=["GET"])
def read_root():
    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    # only return the keys owned by the current user
    user_keys = [key for key, value in shared_dict.items() if value["owner"] == username]
    return jsonify({"keys": user_keys}), 200


# Redirect publicly with HTTP 301; ownership is not checked here.
@app.route("/<id>", methods=["GET"])
def read_item(id):
    value = shared_dict.get(id)

    if value is not None:
        # public endpoint for redirection, no need to check ownership here
        return redirect(value["url"], code=301)
    else:
        return jsonify({"detail": "Key not found in shared dictionary"}), 404


# Delete only the current user's mappings.
# HTTP 404 after deletion is the exercise contract, not normal REST success.
@app.route("/", methods=["DELETE"])
def delete_root():
    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    # only delete the entries owned by the current user
    ids_to_delete = [key for key, value in shared_dict.items() if value["owner"] == username]
    for key in ids_to_delete:
        del shared_dict[key]

    return jsonify({"detail": "All your shortened URLs have been deleted"}), 404


# Require ownership before deletion; return an empty HTTP 204 on success.
@app.route("/<id>", methods=["DELETE"])
def delete_item(id):
    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    if id not in shared_dict:
        return jsonify({"detail": "Key not found in shared dictionary"}), 404

    if shared_dict[id]["owner"] != username:
        return jsonify({"detail": "forbidden"}), 403

    del shared_dict[id]
    return "", 204


# Accept value or, as a fallback, url in the request body.
# Rehash when an occupied ID points to a different URL.
# An identical URL bypasses that loop and overwrites the recorded owner.
# This collision strategy therefore does not ensure ownership isolation.
@app.route("/", methods=["POST"])
def create_root():
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

    # To prevent direct overwriting in case of hash collisions
    while short_id in shared_dict and shared_dict[short_id]["url"] != str(long_url):
        short_id = hashlib.md5((str(long_url) + short_id).encode()).hexdigest()[:6]

    shared_dict[short_id] = {
        "url": str(long_url),
        "owner": username
    }

    return jsonify({"id": short_id}), 201


# Require ownership and a url field; retain the existing ID after updating.
@app.route("/<id>", methods=["PUT"])
def update_item(id):
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
