"""Beginner authentication service for Module 2.

Run from auth_service/ after running ../setup_local_keys.sh.
Listens on participant-local 127.0.0.1:5001 when executed directly.
Users are process-local and disappear on restart; RSA keys persist on disk.

This educational implementation manually constructs RS256 JWTs. Unsalted
SHA-256 password hashing and Flask debug mode are not production-safe.
Only the public key should be copied to the shortener service."""

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


def base64url_encode(data):
    """Encode JWT bytes with the URL-safe alphabet and no trailing padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def hash_password(password):
    """Return an unsalted SHA-256 password hash for this exercise.

    Production authentication requires a dedicated password hashing scheme,
    such as Argon2id, rather than this fast, unsalted hash."""
    return hashlib.sha256(password.encode()).hexdigest()


def ensure_keys_exist():
    """Reuse both key files, or generate and write a new RSA key pair.

    Paths are relative to the current working directory. The keys directory
    must already exist; setup_local_keys.sh prepares it and protects the
    private-key file. If either key is missing, both files are replaced."""
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


def load_private_key():
    """Load the unencrypted signing key from the service-local keys directory."""
    with open(PRIVATE_KEY_FILE, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def generate_jwt(username):
    """Sign a manually assembled JWT identifying username for one hour.

    Base64url encoding does not encrypt the header or payload. RS256 signs
    their encoded bytes using RSA PKCS#1 v1.5 and SHA-256. No server-side
    session or token-revocation record is created."""
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


@app.route("/users", methods=["POST"])
def create_user():
    """Register a username and password supplied in a JSON body.

    Return 400 for missing input, 409 for an existing username, or 201
    after storing the password hash in the in-memory dictionary."""
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


@app.route("/users", methods=["PUT"])
def update_user_password():
    """Replace a password after checking old_password against its stored hash.

    The JSON fields are username, old_password, and new_password.
    Return 400 for missing input, 403 for failed credential checks, or 200
    on success. Previously issued JWTs are not revoked by this operation."""
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


@app.route("/users/login", methods=["POST"])
def login_user():
    """Check JSON credentials and return a signed JWT on success.

    Return 400 for missing input, 403 for failed credentials, or 200 with
    a token. Login issues a token rather than creating a live session."""
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
