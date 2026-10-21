from flask import Flask, jsonify, request
import os
import json
import base64
import time
import hashlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding


app = Flask(__name__)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRIVATE_KEY_FILE = os.path.join(BASE_DIR, "keys", "private_key.pem")
PUBLIC_KEY_FILE = os.path.join(BASE_DIR, "keys", "public_key.pem")
DATA_FILE = os.path.join(BASE_DIR, "data", "users.json")   # auth

def ensure_parent_dir(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)

def load_users():
    global users_dict
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

    users_dict = loaded

def save_users():
    ensure_parent_dir(DATA_FILE)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(users_dict, f, indent=2)


def base64url_encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def ensure_keys_exist():
    ensure_parent_dir(PRIVATE_KEY_FILE)
    ensure_parent_dir(PUBLIC_KEY_FILE)
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
    with open(PRIVATE_KEY_FILE, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


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
    save_users()
    return jsonify({"message": "User created successfully"}), 201


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
    save_users()
    return jsonify({"message": "Password updated successfully"}), 200


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
    load_users()
    ensure_keys_exist()
    app.run(host="0.0.0.0", port=5001, debug=False)