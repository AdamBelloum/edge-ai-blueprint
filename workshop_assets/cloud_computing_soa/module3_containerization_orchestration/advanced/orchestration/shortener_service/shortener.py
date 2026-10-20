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

# original: shared_dict[id] = url
# updated: shared_dict[id] = {"url": xxx, "owner": username}
shared_dict = {}


# TODO:
# Build robust absolute paths based on this file location.
# Expected files:
# - keys/public_key.pem
# - data/urls.json
#
# Hint:
# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# PUBLIC_KEY_FILE = os.path.join(...)
# DATA_FILE = os.path.join(...)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_KEY_FILE = os.path.join(BASE_DIR, "keys", "public_key.pem")
DATA_FILE = os.path.join(BASE_DIR, "data", "urls.json")


def ensure_parent_dir(path):
    """
    TODO:
    Create the parent directory for `path` if it does not exist.
    """
    # os.makedirs(..., exist_ok=True)
    pass


def load_urls():
    """
    TODO:
    Load URL mappings from DATA_FILE into shared_dict.

    Expected behavior:
    - Ensure parent directory exists
    - If file is missing, create it with {}
    - Load JSON into shared_dict
    - If loaded content is not a dict, reset to {}
    - On parse/read errors, reset to {}
    """
    global shared_dict

    # TODO:
    # ensure_parent_dir(DATA_FILE)
    #
    # if ...:
    #     with open(DATA_FILE, "w", encoding="utf-8") as f:
    #         json.dump({}, f)
    #
    # try:
    #     with open(DATA_FILE, "r", encoding="utf-8") as f:
    #         shared_dict = json.load(f)
    #     if ...:
    #         shared_dict = {}
    # except Exception:
    #     shared_dict = {}
    pass


def save_urls():
    """
    TODO:
    Persist shared_dict to DATA_FILE as JSON.
    """
    # ensure_parent_dir(DATA_FILE)
    # with open(DATA_FILE, "w", encoding="utf-8") as f:
    #     json.dump(shared_dict, f, indent=2)
    pass


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
    # TODO:
    # Load persisted URLs before reading.
    # load_urls()

    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    user_keys = [key for key, value in shared_dict.items() if value["owner"] == username]
    return jsonify({"keys": user_keys}), 200


@app.route("/<id>", methods=["GET"])
def read_item(id):
    # TODO:
    # load_urls()

    value = shared_dict.get(id)

    if value is not None:
        return redirect(value["url"], code=301)
    else:
        return jsonify({"detail": "Key not found in shared dictionary"}), 404


@app.route("/", methods=["DELETE"])
def delete_root():
    # TODO:
    # load_urls()

    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    ids_to_delete = [key for key, value in shared_dict.items() if value["owner"] == username]
    for key in ids_to_delete:
        del shared_dict[key]

    # TODO:
    # Persist deletion.
    # save_urls()

    return jsonify({"detail": "All your shortened URLs have been deleted"}), 404


@app.route("/<id>", methods=["DELETE"])
def delete_item(id):
    # TODO:
    # load_urls()

    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    if id not in shared_dict:
        return jsonify({"detail": "Key not found in shared dictionary"}), 404

    if shared_dict[id]["owner"] != username:
        return jsonify({"detail": "forbidden"}), 403

    del shared_dict[id]

    # TODO:
    # Persist deletion.
    # save_urls()

    return "", 204


@app.route("/", methods=["POST"])
def create_root():
    # TODO:
    # load_urls()

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

    while short_id in shared_dict and shared_dict[short_id]["url"] != str(long_url):
        short_id = hashlib.md5((str(long_url) + short_id).encode()).hexdigest()[:6]

    shared_dict[short_id] = {
        "url": str(long_url),
        "owner": username
    }

    # TODO:
    # Persist new mapping.
    # save_urls()

    return jsonify({"id": short_id}), 201


@app.route("/<id>", methods=["PUT"])
def update_item(id):
    # TODO:
    # load_urls()

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

    # TODO:
    # Persist updated mapping.
    # save_urls()

    return jsonify({"message": "Item updated successfully"}), 200


if __name__ == "__main__":
    # TODO:
    # 1) load_urls()
    # 2) app.run(host="0.0.0.0", port=5000, debug=False)
    pass
