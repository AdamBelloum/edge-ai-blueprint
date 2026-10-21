# Module 2 reference authentication service; educational, not production-ready.
# Run ../setup_local_keys.sh first, then start Python from auth_service/.
# Direct execution uses localhost:5001 with workshop-only Flask debug mode.
# Accounts are process-local and disappear on restart.
# Passwords use unsalted SHA-256; production needs a dedicated password hash.
# Keep generated private keys out of Git and out of the shortener service.

from flask import Flask, jsonify, request
import os
import json
import base64
import time
import hashlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding


app = Flask(__name__)

# username -> password_hash
users_dict = {}

PRIVATE_KEY_FILE = "keys/private_key.pem"
PUBLIC_KEY_FILE = "keys/public_key.pem"


# Encode JWT segments without trailing padding; this does not encrypt them.
def base64url_encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


# Return the exercise's SHA-256 password digest, not a production-safe hash.
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


# Reuse both existing key files without validating that they form a pair.
# If either file is missing, replace both with a new 2048-bit RSA pair.
# The caller must create keys/; setup_local_keys.sh also applies permissions.
def ensure_keys_exist():
    if os.path.exists(PRIVATE_KEY_FILE) and os.path.exists(PUBLIC_KEY_FILE):
        return

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )
    public_key = private_key.public_key()

    with open(PRIVATE_KEY_FILE, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
        )

    with open(PUBLIC_KEY_FILE, "wb") as f:
        f.write(
            public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )


# Read the unencrypted PKCS8 PEM signing key relative to the working directory.
def load_private_key():
    with open(PRIVATE_KEY_FILE, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


# Issue an RS256 token with username subject and a one-hour expiration.
# Sign the encoded header and payload using RSA PKCS#1 v1.5/SHA-256.
# Token claims remain readable; signing provides authenticity, not secrecy.
def generate_jwt(username):
    header = {
        "alg": "RS256",
        "typ": "JWT"
    }

    now = int(time.time())
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + 3600
    }

    header_b64 = base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

    private_key = load_private_key()
    signature = private_key.sign(
        signing_input,
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    signature_b64 = base64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


# Register an in-memory username after checking required fields and duplicates.
# Input types are not comprehensively validated.
@app.route("/users", methods=["POST"])
def create_user():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"detail": "Content of body was empty"}), 400

    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"detail": "username or password missing"}), 400

    if username in users_dict:
        return jsonify({"detail": "duplicate"}), 409

    users_dict[username] = hash_password(password)
    return jsonify({"message": "User created successfully"}), 201


# Require the existing password before changing its stored digest.
# Previously issued tokens are not revoked by this operation.
@app.route("/users", methods=["PUT"])
def update_user_password():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"detail": "Content of body was empty"}), 400

    username = data.get("username")
    old_password = data.get("old_password")
    new_password = data.get("new_password")

    if not username or not old_password or not new_password:
        return jsonify({"detail": "username or password missing"}), 400

    if username not in users_dict:
        return jsonify({"detail": "forbidden"}), 403

    if users_dict[username] != hash_password(old_password):
        return jsonify({"detail": "forbidden"}), 403

    users_dict[username] = hash_password(new_password)
    return jsonify({"message": "Password updated successfully"}), 200


# Verify credentials and return a signed token in the token response field.
# No rate limiting or account-lockout mechanism is implemented.
@app.route("/users/login", methods=["POST"])
def login_user():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"detail": "Content of body was empty"}), 400

    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"detail": "username or password missing"}), 400

    if username not in users_dict:
        return jsonify({"detail": "forbidden"}), 403

    if users_dict[username] != hash_password(password):
        return jsonify({"detail": "forbidden"}), 403

    token = generate_jwt(username)
    return jsonify({"token": token}), 200


if __name__ == "__main__":
    ensure_keys_exist()
    app.run(host="127.0.0.1", port=5001, debug=True)
