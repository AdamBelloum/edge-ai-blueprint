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
    """
    TODO:
    Encode bytes using base64url encoding and remove trailing '=' padding.
    Return a UTF-8 string.

    Hint:
    - Look at Python's base64 urlsafe helpers.
    - JWT parts should not keep the normal '=' suffix.
    """
    # return ...
    pass


def hash_password(password):
    """
    TODO:
    Hash the password string with SHA-256 and return the hexadecimal digest.

    Hint:
    - Convert the string to bytes first.
    - Use hashlib.sha256(...).hexdigest()
    """
    # return ...
    pass


def ensure_keys_exist():
    """
    TODO:
    Make sure both the private key file and public key file exist.

    Expected behavior:
    - If both files already exist, do nothing.
    - Otherwise:
      1. generate a new RSA private key
      2. derive the public key from it
      3. write the private key to PRIVATE_KEY_FILE in PEM format
      4. write the public key to PUBLIC_KEY_FILE in PEM format

    Hints:
    - rsa.generate_private_key(...)
    - private_key.private_bytes(...)
    - public_key.public_bytes(...)
    """
    # if ...:
    #     return
    #
    # private_key = ...
    # public_key = ...
    #
    # with open(PRIVATE_KEY_FILE, "wb") as f:
    #     f.write(...)
    #
    # with open(PUBLIC_KEY_FILE, "wb") as f:
    #     f.write(...)
    pass


def load_private_key():
    """
    TODO:
    Read the private key from PRIVATE_KEY_FILE and load it.

    Hint:
    - Open the file in binary mode.
    - Use serialization.load_pem_private_key(...)
    """
    # with open(PRIVATE_KEY_FILE, "rb") as f:
    #     return ...
    pass


def generate_jwt(username):
    """
    TODO:
    Manually construct a JWT signed with RS256.

    Required ideas:
    - header should include alg=RS256 and typ=JWT
    - payload should at least include:
        * sub: username
        * iat: current timestamp
        * exp: expiration timestamp
    - base64url encode header and payload
    - create signing input: "<header_b64>.<payload_b64>"
    - sign the input using the private key and SHA256
    - base64url encode the signature
    - return "<header_b64>.<payload_b64>.<signature_b64>"

    Hints:
    - Use json.dumps(..., separators=(",", ":")) for compact JSON
    - Use your base64url_encode helper
    - Use private_key.sign(...)
    """
    # header = ...
    # now = ...
    # payload = ...
    #
    # header_b64 = ...
    # payload_b64 = ...
    # signing_input = ...
    #
    # private_key = ...
    # signature = ...
    # signature_b64 = ...
    #
    # return ...
    pass


@app.route("/users", methods=["POST"])
def create_user():
    """
    TODO:
    Create a new user.

    Expected behavior:
    - Read JSON body
    - If body is empty -> 400
    - If username or password is missing -> 400
    - If username already exists -> 409 with "duplicate"
    - Otherwise:
        * hash the password
        * store it in users_dict
        * return 201
    """
    data = request.get_json(silent=True)

    # TODO: fill in validation and creation logic
    #
    # if ...:
    #     return jsonify({"detail": ...}), 400
    #
    # username = ...
    # password = ...
    #
    # if ...:
    #     return jsonify({"detail": ...}), 400
    #
    # if ...:
    #     return jsonify({"detail": "duplicate"}), 409
    #
    # users_dict[username] = ...
    # return jsonify({"message": ...}), 201
    pass


@app.route("/users", methods=["PUT"])
def update_user_password():
    """
    TODO:
    Update an existing user's password.

    Expected behavior:
    - Read JSON body
    - Validate username, old_password, new_password
    - If user does not exist -> 403 forbidden
    - If old password is incorrect -> 403 forbidden
    - Otherwise update stored password hash and return 200
    """
    data = request.get_json(silent=True)

    # TODO: fill in password update logic
    #
    # if ...:
    #     return jsonify({"detail": ...}), 400
    #
    # username = ...
    # old_password = ...
    # new_password = ...
    #
    # if ...:
    #     return jsonify({"detail": ...}), 400
    #
    # if ...:
    #     return jsonify({"detail": "forbidden"}), 403
    #
    # if ...:
    #     return jsonify({"detail": "forbidden"}), 403
    #
    # users_dict[username] = ...
    # return jsonify({"message": ...}), 200
    pass


@app.route("/users/login", methods=["POST"])
def login_user():
    """
    TODO:
    Authenticate a user and return a JWT.

    Expected behavior:
    - Read JSON body
    - Validate username and password
    - If credentials are invalid -> 403 forbidden
    - Otherwise generate a JWT and return it with status 200
    """
    data = request.get_json(silent=True)

    # TODO: fill in login logic
    #
    # if ...:
    #     return jsonify({"detail": ...}), 400
    #
    # username = ...
    # password = ...
    #
    # if ...:
    #     return jsonify({"detail": ...}), 400
    #
    # if ...:
    #     return jsonify({"detail": "forbidden"}), 403
    #
    # if ...:
    #     return jsonify({"detail": "forbidden"}), 403
    #
    # token = ...
    # return jsonify({"token": token}), 200
    pass


if __name__ == "__main__":
    ensure_keys_exist()
    app.run(host="127.0.0.1", port=5001, debug=True)