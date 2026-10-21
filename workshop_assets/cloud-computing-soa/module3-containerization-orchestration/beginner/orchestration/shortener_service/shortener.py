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
    os.makedirs(os.path.dirname(path), exist_ok=True)

def load_urls():
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
    ensure_parent_dir(DATA_FILE)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(shared_dict, f, indent=2)

def is_it_an_url(string):
    return isinstance(string, str) and (
        string.startswith("http://") or string.startswith("https://")
    )


def generate_short_id(url):
    return hashlib.md5(url.encode()).hexdigest()[:6]


def base64url_decode(data):
    padding_needed = 4 - (len(data) % 4)
    if padding_needed != 4:
        data += "=" * padding_needed
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def load_public_key():
    with open(PUBLIC_KEY_FILE, "rb") as f:
        return serialization.load_pem_public_key(f.read())


def get_token_from_request():
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1].strip()

    token = request.headers.get("x-access-token")
    if token:
        return token.strip()

    return None


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


def get_current_user():
    token = get_token_from_request()
    if not token:
        return None
    return verify_jwt(token)


@app.route("/", methods=["GET"])
def read_root():
    load_urls()
    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    # only return the keys owned by the current user
    user_keys = [key for key, value in shared_dict.items() if value["owner"] == username]
    return jsonify({"keys": user_keys}), 200


@app.route("/<id>", methods=["GET"])
def read_item(id):
    load_urls()
    value = shared_dict.get(id)

    if value is not None:
        # public endpoint for redirection, no need to check ownership here
        return redirect(value["url"], code=301)
    else:
        return jsonify({"detail": "Key not found in shared dictionary"}), 404


@app.route("/", methods=["DELETE"])
def delete_root():
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