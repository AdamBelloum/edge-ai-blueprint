"""Beginner practical: user registration and RSA-signed login tokens.

Run step by step:
1. From the parent containerization directory, follow setup_local_keys.sh
   instructions and prepare both services' keys before starting Compose.
2. On your assigned Docker-capable host, run:
       docker compose up --build -d
3. Send requests to http://<docker-host>:5001 by default, replacing
   <docker-host> with your assigned host address. Use your configured
   host port if you override AUTH_HOST_PORT.
4. Register through POST /users, then log in through POST /users/login.
   Both expect a JSON object with "username" and "password".
5. Use the returned token with the shortener's Authorization header:
       Bearer <token>
   Replace <token> with the token value. Keep tokens and passwords private.

API overview:
- POST /users: create a user (201); duplicate username (409).
- PUT /users: change a password (200), supplying "username",
  "old_password", and "new_password"; incorrect credentials return 403.
- POST /users/login: return JSON containing "token" (200), or 403
  for incorrect credentials.
Missing required fields or empty input return 400. These handlers expect
JSON objects and do not comprehensively validate input types.

Storage and keys:
Paths are relative to this file. data/users.json maps usernames to
password hashes. Users are loaded at startup; changes update the in-memory
dictionary and save it to disk. Requests do not reload the file.
Compose mounts persistent storage at /app/data and read-only keys at
/app/keys. Prepare a complete key pair before starting containers.
The startup helper preserves a valid, matching key pair and generates
keys only when neither file exists. It refuses incomplete, invalid, or
mismatched pairs without replacing existing files. Generation cannot write
through the read-only Compose key mount.
Only the public key belongs in the shortener; never share the private key.

Teaching limitations:
Passwords use unsalted SHA-256, not production-safe password hashing.
The private key is stored as unencrypted PEM; protect it outside Git.
Login tokens use RS256 with sub, iat, and a one-hour exp claim.
Changing a password does not revoke previously issued tokens.
JSON writes have no locking or atomic replacement, and multiple processes
do not share a synchronized user dictionary. No TLS is configured here.
Use disposable lab credentials and the Flask server only for the practical.
"""

from flask import Flask, jsonify, request
import os
import stat
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
    """Create the parent directory of the supplied file path if needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)

def load_users():
    """Load persisted password hashes into the global users_dict.

    Initialize missing storage with an empty JSON object.
    Raise RuntimeError for unreadable data or a non-object root;
    individual records are not schema-validated.
    Called at startup, not on each request: external file changes
    remain unseen until another load, normally after a restart."""
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
    """Replace DATA_FILE with the current users_dict as formatted JSON.

    Create its parent directory if needed; filesystem errors propagate.
    No locking, atomic replacement, or merge with external edits is
    provided. Saving stale in-memory data can overwrite such edits."""
    ensure_parent_dir(DATA_FILE)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(users_dict, f, indent=2)


def base64url_encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def ensure_keys_exist():
    """Validate an existing RSA key pair, or create one if neither file exists.

    Existing files must be regular, unencrypted PEM RSA keys of at least
    2048 bits, and the public key must match the private key. Incomplete or
    invalid pairs are never replaced. Newly created private and public files
    use restrictive and public-readable permissions, respectively.
    """
    ensure_parent_dir(PRIVATE_KEY_FILE)
    ensure_parent_dir(PUBLIC_KEY_FILE)

    private_exists = os.path.lexists(PRIVATE_KEY_FILE)
    public_exists = os.path.lexists(PUBLIC_KEY_FILE)

    if private_exists != public_exists:
        raise RuntimeError(
            "Incomplete authentication key pair; refusing to replace either "
            "existing key file. Inspect and repair the pair before starting."
        )

    if private_exists:
        try:
            if not stat.S_ISREG(os.lstat(PRIVATE_KEY_FILE).st_mode):
                raise ValueError("Private key is not a regular file.")
            if not stat.S_ISREG(os.lstat(PUBLIC_KEY_FILE).st_mode):
                raise ValueError("Public key is not a regular file.")

            with open(PRIVATE_KEY_FILE, "rb") as f:
                private_key = serialization.load_pem_private_key(
                    f.read(), password=None
                )
            with open(PUBLIC_KEY_FILE, "rb") as f:
                public_key = serialization.load_pem_public_key(f.read())

            if not isinstance(private_key, rsa.RSAPrivateKey):
                raise ValueError("Private key is not an RSA key.")
            if not isinstance(public_key, rsa.RSAPublicKey):
                raise ValueError("Public key is not an RSA key.")
            if private_key.key_size < 2048 or public_key.key_size < 2048:
                raise ValueError("RSA keys must be at least 2048 bits.")
            if private_key.public_key().public_numbers() != public_key.public_numbers():
                raise ValueError("Public key does not match private key.")
        except Exception as exc:
            raise RuntimeError(
                "Existing authentication keys are invalid or do not match; "
                "refusing to replace them. Inspect and repair the pair."
            ) from exc
        return

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    created_files = []
    try:
        for key_path, contents, mode in (
            (PRIVATE_KEY_FILE, private_pem, 0o600),
            (PUBLIC_KEY_FILE, public_pem, 0o644),
        ):
            fd = os.open(
                key_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                mode
            )
            created_files.append(key_path)
            with os.fdopen(fd, "wb") as f:
                f.write(contents)
    except OSError as exc:
        for created_path in reversed(created_files):
            try:
                os.unlink(created_path)
            except OSError:
                pass
        raise RuntimeError(
            "Could not create a complete authentication key pair. Cleanup "
            "was attempted; inspect the key directory before retrying."
        ) from exc


def load_private_key():
    """Load an unencrypted PEM private key from PRIVATE_KEY_FILE.

    Return the deserialized private-key object. File-reading and
    key-loading errors propagate to the caller; no keys are generated.
    """
    with open(PRIVATE_KEY_FILE, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def generate_jwt(username):
    """Return an RS256-signed JWT string for the supplied username.

    Set sub to username, iat to the current Unix time in seconds,
    and exp to one hour later. Encode the header, payload, and
    signature using URL-safe Base64 without trailing padding.

    Load the private key on each call and sign with RSA PKCS#1 v1.5
    and SHA-256. Key-loading and signing errors propagate to the caller.
    This helper does not verify credentials or encrypt the payload.
    """
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
