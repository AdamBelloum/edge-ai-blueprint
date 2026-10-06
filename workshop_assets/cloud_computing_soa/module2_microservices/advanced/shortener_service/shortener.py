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
    """
    TODO:
    Implement a minimal URL validity check.

    Expected behavior:
    - return True only if the input is a string
    - and starts with either "http://" or "https://"
    """
    # return ...
    pass


def generate_short_id(url):
    """
    TODO:
    Generate a short identifier from a URL.

    Hint:
    - Use an md5 hash of the URL
    - Keep only the first 6 characters
    """
    # return ...
    pass


def base64url_decode(data):
    """
    TODO:
    Decode a base64url-encoded string.

    Important:
    - JWT parts may omit '=' padding
    - add the missing padding back before decoding
    """
    # padding_needed = ...
    # if ...:
    #     data += ...
    # return ...
    pass


def load_public_key():
    """
    TODO:
    Read and load the public key from PUBLIC_KEY_FILE.

    Hint:
    - Open in binary mode
    - Use serialization.load_pem_public_key(...)
    """
    # with open(PUBLIC_KEY_FILE, "rb") as f:
    #     return ...
    pass


def get_token_from_request():
    """
    TODO:
    Extract a token from the incoming request.

    Supported formats:
    1. Authorization: Bearer <token>
    2. x-access-token: <token>

    Return:
    - token string if found
    - None otherwise
    """
    # auth_header = ...
    # if ...:
    #     return ...
    #
    # token = ...
    # if ...:
    #     return ...
    #
    # return None
    pass


def verify_jwt(token):
    """
    TODO:
    Verify a JWT locally using the public key.

    Expected steps:
    1. Split token into 3 parts
    2. Rebuild signing input
    3. Decode signature
    4. Verify signature using the public key
    5. Decode payload JSON
    6. Check 'exp'
    7. Check 'sub'
    8. Return the username in 'sub' if valid
    9. Return None on failure

    Hints:
    - public_key.verify(...)
    - catch InvalidSignature and parsing errors
    """
    try:
        # parts = ...
        # if ...:
        #     return None
        #
        # header_b64, payload_b64, signature_b64 = ...
        # signing_input = ...
        # signature = ...
        #
        # public_key = ...
        # public_key.verify(...)
        #
        # payload = ...
        #
        # if ...:
        #     return None
        #
        # if ...:
        #     return None
        #
        # return ...
        pass

    except (InvalidSignature, ValueError, KeyError, json.JSONDecodeError):
        return None
    except Exception:
        return None


def get_current_user():
    """
    TODO:
    Use the request token and verify it.

    Return:
    - username if the token is valid
    - None otherwise
    """
    # token = ...
    # if ...:
    #     return None
    # return ...
    pass


@app.route("/", methods=["GET"])
def read_root():
    """
    TODO:
    Return the keys that belong only to the current authenticated user.

    Expected behavior:
    - If token invalid/missing -> 403 forbidden
    - Otherwise return a JSON object containing the current user's keys
    """
    username = get_current_user()

    # TODO:
    # if ...:
    #     return jsonify({"detail": "forbidden"}), 403
    #
    # user_keys = ...
    # return jsonify({"keys": user_keys}), 200
    pass


@app.route("/<id>", methods=["GET"])
def read_item(id):
    """
    TODO:
    Resolve a short ID to the original URL.

    Expected behavior:
    - If id exists -> return 301 redirect (or equivalent 301 behavior if you choose)
    - If id does not exist -> 404

    Note:
    In this version, this endpoint is treated as the public resolution endpoint.
    """
    value = shared_dict.get(id)

    # TODO:
    # if ...:
    #     return redirect(..., code=301)
    # else:
    #     return jsonify({"detail": ...}), 404
    pass


@app.route("/", methods=["DELETE"])
def delete_root():
    """
    TODO:
    Delete only the URL mappings owned by the current authenticated user.

    Expected behavior:
    - Invalid/missing token -> 403
    - Delete only this user's entries
    - Return 404 after deletion, following the chosen assignment behavior
    """
    username = get_current_user()

    # TODO:
    # if ...:
    #     return jsonify({"detail": "forbidden"}), 403
    #
    # ids_to_delete = ...
    # for key in ids_to_delete:
    #     del shared_dict[key]
    #
    # return jsonify({"detail": ...}), 404
    pass


@app.route("/<id>", methods=["DELETE"])
def delete_item(id):
    """
    TODO:
    Delete a single mapping, but only if it belongs to the current user.

    Expected behavior:
    - Invalid/missing token -> 403
    - Non-existing id -> 404
    - Existing but owned by someone else -> 403
    - Success -> 204 with empty body
    """
    username = get_current_user()

    # TODO:
    # if ...:
    #     return jsonify({"detail": "forbidden"}), 403
    #
    # if ...:
    #     return jsonify({"detail": ...}), 404
    #
    # if ...:
    #     return jsonify({"detail": "forbidden"}), 403
    #
    # del shared_dict[id]
    # return "", 204
    pass


@app.route("/", methods=["POST"])
def create_root():
    """
    TODO:
    Create a new short URL for the authenticated user.

    Expected behavior:
    - Invalid/missing token -> 403
    - Missing/invalid body -> 400
    - Accept either "value" or "url" as the long URL field
    - Validate the URL
    - Generate a short id
    - Handle collisions so a different URL does not overwrite an existing one
    - Store both url and owner
    - Return 201 with the new id
    """
    username = get_current_user()

    # TODO:
    # if ...:
    #     return jsonify({"detail": "forbidden"}), 403
    #
    # data = request.get_json(silent=True)
    # if ...:
    #     return jsonify({"detail": "error"}), 400
    #
    # long_url = ...
    # if long_url is None:
    #     long_url = ...
    #
    # if ...:
    #     return jsonify({"detail": "error"}), 400
    #
    # if ...:
    #     return jsonify({"detail": "error"}), 400
    #
    # short_id = ...
    #
    # while ...:
    #     short_id = ...
    #
    # shared_dict[short_id] = {
    #     "url": ...,
    #     "owner": ...
    # }
    #
    # return jsonify({"id": short_id}), 201
    pass


@app.route("/<id>", methods=["PUT"])
def update_item(id):
    """
    TODO:
    Update the long URL behind an existing short ID.

    Expected behavior:
    - Invalid/missing token -> 403
    - Non-existing id -> 404
    - Existing but owned by someone else -> 403
    - Missing or invalid new url -> 400
    - Success -> update and return 200
    """
    username = get_current_user()
    data = request.get_json(force=True, silent=True)

    # TODO:
    # if ...:
    #     return jsonify({"detail": "forbidden"}), 403
    #
    # if ...:
    #     return jsonify({"detail": ...}), 404
    #
    # if ...:
    #     return jsonify({"detail": "forbidden"}), 403
    #
    # if ...:
    #     return jsonify({"detail": "error"}), 400
    #
    # if ...:
    #     return jsonify({"detail": "error"}), 400
    #
    # shared_dict[id]["url"] = ...
    # return jsonify({"message": ...}), 200
    pass


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)