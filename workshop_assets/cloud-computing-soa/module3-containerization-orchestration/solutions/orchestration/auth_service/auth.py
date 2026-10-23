"""Authentication service: user accounts and JSON Web Tokens (RS256).

Reference solution for Assignment 2. Assignment 3 (Module 3) runs this same
file in a container; there, DATA_DIR is set so that accounts are kept on disk.

    POST /users        {"username", "password"}                     201 | 400 | 409 "duplicate"
    PUT  /users        {"username", "old_password", "new_password"}  200 | 400 | 403 "forbidden"
    POST /users/login  {"username", "password"}                     200 {"token": JWT} | 400 | 403 "forbidden"

PUT /users also accepts the old password as "password" or "old-password",
and the new one as "new-password".

Tokens are signed with the private key in keys/private_key.pem, which never
leaves this service. The URL shortener checks them with the public key that
setup_local_keys.sh copies to it. A token holds only the user's id and when
it was issued and expires. The id is a random value given to each new
account and never reused, so a new account with the name of a lost one
cannot take over that account's mappings.

Environment variables:
    HOST, PORT  address to listen on (default 127.0.0.1 and 5001)
    DATA_DIR    keep the accounts in DATA_DIR/users.json instead of in memory,
                so that they survive restarts (Assignment 3)
    POD_NAME    if set (Kubernetes), returned in the X-Served-By header

Run bash ../setup_local_keys.sh once, then python auth.py.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import signal
import sys
import threading
import time
import uuid
from contextlib import contextmanager

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from flask import Flask, jsonify, request

try:
    import fcntl  # POSIX only: lets processes that share DATA_DIR take turns
except ImportError:  # Windows
    fcntl = None

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRIVATE_KEY_FILE = os.path.join(BASE_DIR, "keys", "private_key.pem")
PUBLIC_KEY_FILE = os.path.join(BASE_DIR, "keys", "public_key.pem")
DATA_DIR = os.environ.get("DATA_DIR")
POD_NAME = os.environ.get("POD_NAME")

TOKEN_LIFETIME = 3600  # seconds
PBKDF2_ITERATIONS = 100_000

# username -> {"id": ..., "salt": ..., "password_hash": ...}, used when
# DATA_DIR is not set
users_in_memory = {}
thread_lock = threading.Lock()


@contextmanager
def users_db(write=False):
    """Give one request at a time the table of accounts.

    Without DATA_DIR, the table lives in memory. With DATA_DIR, it is read
    from DATA_DIR/users.json for every request and, if write is True,
    written back afterwards. A restarted container, or a replica that shares
    the directory, therefore sees the same accounts. The file lock makes
    processes take turns, so that two of them cannot overwrite each other's
    changes.
    """
    with thread_lock:
        if not DATA_DIR:
            yield users_in_memory
            return
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "users.json")
        with open(path + ".lock", "a") as lock_file:
            if fcntl:
                fcntl.flock(lock_file, fcntl.LOCK_EX)
            users = read_json(path)
            yield users
            if write:
                write_json(path, users)


def read_json(path):
    """Return the JSON object in path, or {} if the file does not exist."""
    try:
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} does not contain a JSON object")
    return data


def write_json(path, data):
    """Replace path in one step, so that a reader never sees half a file."""
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def hash_password(password, salt):
    """PBKDF2-HMAC-SHA256 of the password with a per-user salt, as hex."""
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return digest.hex()


def password_record(password):
    """What is stored for a password: a new random salt and the hash."""
    salt = secrets.token_hex(16)
    return {"salt": salt, "password_hash": hash_password(password, salt)}


def password_matches(record, password):
    """Compare in constant time, so the answer time does not reveal the hash."""
    return hmac.compare_digest(record["password_hash"], hash_password(password, record["salt"]))


def base64url_encode(data):
    """Base64url without the '=' padding, as JWTs use it."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def ensure_keys_exist():
    """Create an RSA key pair in keys/ unless both files already exist."""
    if os.path.exists(PRIVATE_KEY_FILE) and os.path.exists(PUBLIC_KEY_FILE):
        return
    os.makedirs(os.path.dirname(PRIVATE_KEY_FILE), exist_ok=True)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with open(PRIVATE_KEY_FILE, "wb") as stream:
        stream.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    with open(PUBLIC_KEY_FILE, "wb") as stream:
        stream.write(private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ))


def load_private_key():
    with open(PRIVATE_KEY_FILE, "rb") as stream:
        return serialization.load_pem_private_key(stream.read(), password=None)


def generate_jwt(user_id):
    """Return header.payload.signature, each part base64url-encoded.

    The signature is RSA with SHA-256 (RS256) over "header.payload". The
    payload holds no more than the shortener needs: the user's id (sub) and
    when the token was issued (iat) and expires (exp).
    """
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {"sub": user_id, "iat": now, "exp": now + TOKEN_LIFETIME}
    signing_input = ".".join(
        base64url_encode(json.dumps(part, separators=(",", ":")).encode("utf-8"))
        for part in (header, payload)
    )
    signature = load_private_key().sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{base64url_encode(signature)}"


def request_data():
    """The JSON object in the request body, or {} if there is none."""
    try:
        data = request.get_json(force=True, silent=True)
    except RecursionError:  # absurdly deep nesting
        data = None
    return data if isinstance(data, dict) else {}


def field(data, *names):
    """The first non-empty string among data[name] for the given names.

    Strings that are not valid text (a lone surrogate sent as \\ud800 in
    JSON) count as missing.
    """
    for name in names:
        value = data.get(name)
        if isinstance(value, str) and value:
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                return None
            return value
    return None


def bad_request(reason):
    return jsonify({"detail": "error", "reason": reason}), 400


def forbidden():
    return jsonify({"detail": "forbidden"}), 403


@app.after_request
def add_served_by(response):
    # Shows which replica answered (Assignment 3.2, load balancing).
    if POD_NAME:
        response.headers["X-Served-By"] = POD_NAME
    return response


@app.route("/users", methods=["POST"])
def create_user():
    data = request_data()
    username, password = field(data, "username"), field(data, "password")
    if not username or not password:
        return bad_request("username and password are required")
    record = dict(password_record(password), id=uuid.uuid4().hex)
    with users_db(write=True) as users:
        if username in users:
            return jsonify({"detail": "duplicate"}), 409
        users[username] = record
    return jsonify({"username": username}), 201


@app.route("/users", methods=["PUT"])
def update_user_password():
    data = request_data()
    username = field(data, "username")
    old_password = field(data, "old_password", "old-password", "password")
    new_password = field(data, "new_password", "new-password")
    if not username or not old_password or not new_password:
        return bad_request("username, old_password and new_password are required")
    record = password_record(new_password)
    with users_db(write=True) as users:
        if username not in users or not password_matches(users[username], old_password):
            return forbidden()
        users[username].update(record)  # the user's id stays the same
    return jsonify({"username": username}), 200


@app.route("/users/login", methods=["POST"])
def login_user():
    data = request_data()
    username, password = field(data, "username"), field(data, "password")
    if not username or not password:
        return bad_request("username and password are required")
    with users_db() as users:
        record = users.get(username)
    if record is None or not password_matches(record, password):
        return forbidden()
    return jsonify({"token": generate_jwt(record["id"])}), 200


if __name__ == "__main__":
    try:
        ensure_keys_exist()
        load_private_key()
    except (OSError, ValueError) as error:
        sys.exit(f"Cannot use the signing key {PRIVATE_KEY_FILE} ({error}). Run setup_local_keys.sh first.")
    # Docker and Kubernetes stop a container with SIGTERM: exit at once.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5001")))
