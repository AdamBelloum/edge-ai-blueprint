"""URL-shortener service with multi-user support (JWT authentication).

Reference solution for Assignment 2: the API of Assignment 1, where every
mapping belongs to the user who created it. Assignment 3 (Module 3) runs this
same file in a container; there, DATA_DIR is set so that mappings are kept
on disk.

    GET    /:id                   301 to the URL, for anyone | 404
    PUT    /:id   {"url": ...}    200 | 400 invalid URL | 403 | 404
    DELETE /:id                   204 | 403 | 404
    GET    /                      200 {"keys": [the caller's ids]} | 403
    POST   /      {"value": ...}  201 {"id": ...} | 400 invalid URL | 403
    DELETE /                      404, after deleting the caller's mappings | 403

POST also accepts the URL as "url", and PUT as "value".

All requests except GET /:id need a token from the authentication service,
sent as "Authorization: Bearer <token>". This service checks the token with
the authentication service's public key (keys/public_key.pem); the private
key stays in the authentication service. 403 means that the token is
missing or invalid, or that the mapping belongs to another user. A mapping's
owner is the user id in the token (never the username, which a new account
could take over after the authentication service lost its data).

Identifiers and URL validation work as in Assignment 1. Identifiers come from
a counter written in base 62, so they are as short as possible, unique, and
never reused after a delete. URLs must match a regular expression.

Environment variables:
    HOST, PORT  address to listen on (default 127.0.0.1 and 5000)
    DATA_DIR    keep the mappings in DATA_DIR/urls.json instead of in memory,
                so that they survive restarts and replicas that share the
                directory see the same data (Assignment 3)
    POD_NAME    if set (Kubernetes), returned in the X-Served-By header

Run bash ../setup_local_keys.sh once, then python shortener.py.
"""
import base64
import json
import os
import re
import signal
import sys
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from flask import Flask, jsonify, request
from werkzeug.urls import iri_to_uri

try:
    import fcntl  # POSIX only: lets processes that share DATA_DIR take turns
except ImportError:  # Windows
    fcntl = None

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_KEY_FILE = os.path.join(BASE_DIR, "keys", "public_key.pem")
DATA_DIR = os.environ.get("DATA_DIR")
POD_NAME = os.environ.get("POD_NAME")

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

# An absolute http or https URL whose host is an ASCII domain name with a
# top-level domain (internationalised names in their xn-- form), localhost or
# an IPv4 address. The path, query string and fragment may contain any
# character except whitespace and control characters, including non-ASCII
# characters such as the dash in https://en.wikipedia.org/wiki/Bellman–Ford_algorithm.
# Not accepted, by choice: IPv6 addresses, user:password@ and single-label
# host names such as http://intranet/.
URL_PATTERN = re.compile(
    r"""
    [hH][tT][tT][pP][sS]?://
    (?:
        (?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+      # labels, e.g. www.uva.
        (?:[a-zA-Z]{2,63}|[xX][nN]--[a-zA-Z0-9-]{1,59})\.?        # top-level domain, e.g. nl
      | localhost
      | (?:(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\.){3}
        (?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])           # IPv4 address
    )
    (?::(?:[1-9][0-9]{0,3}|[1-5][0-9]{4}|6[0-4][0-9]{3}
          |65[0-4][0-9]{2}|655[0-2][0-9]|6553[0-5]))?             # port 1-65535
    (?:[/?\#][^\s\x00-\x1f\x7f-\x9f\ud800-\udfff]*)?              # path, query, fragment
    """,
    re.VERBOSE,
)
JWT_PART = re.compile(r"[A-Za-z0-9_-]+")

# The service's data, kept here when DATA_DIR is not set:
#   next_id  number of identifiers handed out so far; it only grows
#   urls     short id -> {"url": ..., "owner": user id}
urls_in_memory = {"next_id": 0, "urls": {}}
thread_lock = threading.Lock()
public_key = None


@contextmanager
def urls_db(write=False):
    """Give one request at a time the service's data.

    Without DATA_DIR, the data lives in memory. With DATA_DIR, it is read
    from DATA_DIR/urls.json for every request and, if write is True, written
    back afterwards. A restarted container, or another replica that shares
    the directory, therefore sees the same mappings. The file lock makes
    processes take turns, so that two replicas cannot hand out the same
    identifier or overwrite each other's changes.
    """
    with thread_lock:
        if not DATA_DIR:
            yield urls_in_memory
            return
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "urls.json")
        with open(path + ".lock", "a") as lock_file:
            if fcntl:
                fcntl.flock(lock_file, fcntl.LOCK_EX)
            data = read_json(path)
            data.setdefault("next_id", 0)
            data.setdefault("urls", {})
            yield data
            if write:
                write_json(path, data)


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


def is_it_an_url(value):
    """Return True if value matches URL_PATTERN and fits in a Location header."""
    if not isinstance(value, str) or URL_PATTERN.fullmatch(value) is None:
        return False
    try:
        host = urlsplit(value).hostname or ""
        iri_to_uri(value)  # the redirect needs an ASCII form of the URL
    except ValueError:
        return False
    return len(host) <= 253


def to_base62(number):
    """Write a non-negative integer with the 62 characters of ALPHABET."""
    digits = ""
    while True:
        number, remainder = divmod(number, 62)
        digits = ALPHABET[remainder] + digits
        if number == 0:
            return digits


def generate_short_id(data):
    """Take the next identifier from the counter in data.

    An identifier only gets longer once all shorter ones are used (62 of one
    character, then 3,844 of two, ...). The counter is never decreased, so
    a deleted identifier is not handed out again. Identifiers are therefore
    predictable; short links are public anyway.
    """
    short_id = to_base62(data["next_id"])
    data["next_id"] += 1
    return short_id


def base64url_decode(text):
    """Decode base64url, adding the '=' padding that JWTs leave out."""
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def load_public_key():
    """The authentication service's public key, read once."""
    global public_key
    if public_key is None:
        with open(PUBLIC_KEY_FILE, "rb") as stream:
            public_key = serialization.load_pem_public_key(stream.read())
    return public_key


def get_token_from_request():
    """The token from "Authorization: Bearer <token>".

    A token sent without "Bearer", or in an x-access-token header, is
    accepted too.
    """
    header = request.headers.get("Authorization", "").strip()
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return header or request.headers.get("x-access-token", "").strip() or None


def verify_jwt(token):
    """Return the user id in a valid token, or None.

    Valid means: three base64url parts, an RS256 header, a signature that the
    public key accepts, a user id, and an expiry time in the future. The
    check needs no call to the authentication service, so a token stays valid
    until it expires, also after a password change.
    """
    parts = token.split(".")
    if len(token) > 4096 or len(parts) != 3 or not all(JWT_PART.fullmatch(part) for part in parts):
        return None
    header_b64, payload_b64, signature_b64 = parts
    try:
        header = json.loads(base64url_decode(header_b64))
        if not isinstance(header, dict) or header.get("alg") != "RS256":
            return None
        load_public_key().verify(
            base64url_decode(signature_b64),
            f"{header_b64}.{payload_b64}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        payload = json.loads(base64url_decode(payload_b64))
    except (ValueError, InvalidSignature, RecursionError):
        return None
    if not isinstance(payload, dict):
        return None
    user_id, expires = payload.get("sub"), payload.get("exp")
    if not isinstance(user_id, str) or not isinstance(expires, (int, float)) or expires <= time.time():
        return None
    return user_id


def get_current_user():
    token = get_token_from_request()
    return verify_jwt(token) if token else None


def request_data():
    """The JSON object in the request body, or {} if there is none."""
    try:
        data = request.get_json(force=True, silent=True)
    except RecursionError:  # absurdly deep nesting
        data = None
    return data if isinstance(data, dict) else {}


def invalid_url():
    return jsonify({"detail": "error", "reason": "not a valid http(s) URL"}), 400


def forbidden():
    return jsonify({"detail": "forbidden"}), 403


def not_found():
    return jsonify({"detail": "not found"}), 404


@app.after_request
def add_served_by(response):
    # Shows which replica answered (Assignment 3.2, load balancing).
    if POD_NAME:
        response.headers["X-Served-By"] = POD_NAME
    return response


@app.route("/", methods=["GET"])
def read_root():
    user_id = get_current_user()
    if user_id is None:
        return forbidden()
    with urls_db() as data:
        keys = [key for key, mapping in data["urls"].items() if mapping["owner"] == user_id]
    return jsonify({"keys": keys}), 200


@app.route("/<id>", methods=["GET"])
def read_item(id):
    # Public: anyone with the short link can follow it.
    with urls_db() as data:
        mapping = data["urls"].get(id)
    if mapping is None:
        return not_found()
    # A real redirect: browsers follow the Location header, and clients that
    # do not follow redirects find the URL in the body. Header values must be
    # ASCII, so iri_to_uri percent-encodes other characters.
    response = jsonify({"value": mapping["url"]})
    response.headers["Location"] = iri_to_uri(mapping["url"])
    return response, 301


@app.route("/<id>", methods=["PUT"])
def update_item(id):
    user_id = get_current_user()
    if user_id is None:
        return forbidden()
    body = request_data()
    url = body.get("url") or body.get("value")
    with urls_db(write=True) as data:
        mapping = data["urls"].get(id)
        if mapping is None:
            return not_found()
        if mapping["owner"] != user_id:
            return forbidden()
        if not is_it_an_url(url):
            return invalid_url()
        mapping["url"] = url
    return jsonify({"id": id, "value": url}), 200


@app.route("/<id>", methods=["DELETE"])
def delete_item(id):
    user_id = get_current_user()
    if user_id is None:
        return forbidden()
    with urls_db(write=True) as data:
        mapping = data["urls"].get(id)
        if mapping is None:
            return not_found()
        if mapping["owner"] != user_id:
            return forbidden()
        del data["urls"][id]
    return "", 204


@app.route("/", methods=["POST"])
def create_root():
    user_id = get_current_user()
    if user_id is None:
        return forbidden()
    body = request_data()
    url = body.get("value") or body.get("url")
    if not is_it_an_url(url):
        return invalid_url()
    with urls_db(write=True) as data:
        short_id = generate_short_id(data)
        data["urls"][short_id] = {"url": url, "owner": user_id}
    return jsonify({"id": short_id}), 201


@app.route("/", methods=["DELETE"])
def delete_root():
    # Deletes only the caller's mappings. The specification asks for 404.
    user_id = get_current_user()
    if user_id is None:
        return forbidden()
    with urls_db(write=True) as data:
        data["urls"] = {key: mapping for key, mapping in data["urls"].items() if mapping["owner"] != user_id}
    return jsonify({"detail": "your mappings were deleted"}), 404


if __name__ == "__main__":
    try:
        load_public_key()
    except (OSError, ValueError) as error:
        sys.exit(f"Cannot read the public key {PUBLIC_KEY_FILE} ({error}). Run setup_local_keys.sh first.")
    # Docker and Kubernetes stop a container with SIGTERM: exit at once.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")))
