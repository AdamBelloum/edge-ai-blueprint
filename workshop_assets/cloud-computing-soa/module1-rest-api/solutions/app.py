"""Assignment 1 reference solution: a RESTful URL-shortener service.

Run with ``python app.py``; the service listens on http://127.0.0.1:5000
(set HOST and PORT to change that). Mappings are kept in memory, so
restarting the process clears them.

    GET    /:id   301 with the URL (Location header and JSON body) | 404
    PUT    /:id   {"url": ...}    200 | 400 invalid URL | 404     ("value" works too)
    DELETE /:id                   204 | 404
    GET    /                      200 {"keys": [...]}
    POST   /      {"value": ...}  201 {"id": ...} | 400 invalid URL  ("url" works too)
    DELETE /                      404, after deleting every mapping

Two design decisions give the full points of the assignment:

* Identifiers come from a counter written in base 62 (0-9, a-z, A-Z). An
  identifier only gets longer once all shorter ones are used: 62 identifiers
  of one character, then 3,844 of two characters, and so on. Creating one
  takes constant time, two URLs never get the same identifier, and Python
  integers do not overflow. The counter is never decreased, so the identifier
  of a deleted mapping is not handed out again and an old short link cannot
  start pointing to a different URL.
* A URL must match a regular expression (URL_PATTERN) before a mapping is
  created or updated.
"""
import os
import re
import threading
from urllib.parse import urlsplit

from flask import Flask, jsonify, request
from werkzeug.urls import iri_to_uri

app = Flask(__name__)

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

# short id -> URL
shared_dict = {}
# Number of identifiers handed out so far.
id_counter = 0
# Flask handles requests in several threads; the lock makes each change to
# the counter and the dictionary happen as one step.
lock = threading.Lock()


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


def generate_short_id():
    """Return the next identifier. The caller must hold the lock."""
    global id_counter
    short_id = to_base62(id_counter)
    id_counter += 1
    return short_id


def request_data():
    """Return the JSON object in the request body, or {} if there is none.

    force=True also accepts JSON sent without a Content-Type header.
    """
    try:
        data = request.get_json(force=True, silent=True)
    except RecursionError:  # absurdly deep nesting
        data = None
    return data if isinstance(data, dict) else {}


def invalid_url():
    return jsonify({"detail": "error", "reason": "not a valid http(s) URL"}), 400


def not_found():
    return jsonify({"detail": "not found"}), 404


@app.route("/", methods=["GET"])
def read_root():
    with lock:
        keys = list(shared_dict)
    return jsonify({"keys": keys}), 200


@app.route("/<id>", methods=["GET"])
def read_item(id):
    url = shared_dict.get(id)
    if url is None:
        return not_found()
    # A real redirect: browsers follow the Location header, and clients that
    # do not follow redirects find the URL in the body. Header values must be
    # ASCII, so iri_to_uri percent-encodes other characters.
    response = jsonify({"value": url})
    response.headers["Location"] = iri_to_uri(url)
    return response, 301


@app.route("/<id>", methods=["PUT"])
def update_item(id):
    body = request_data()
    url = body.get("url") or body.get("value")
    with lock:
        if id not in shared_dict:
            return not_found()
        if not is_it_an_url(url):
            return invalid_url()
        shared_dict[id] = url
    return jsonify({"id": id, "value": url}), 200


@app.route("/<id>", methods=["DELETE"])
def delete_item(id):
    with lock:
        if shared_dict.pop(id, None) is None:
            return not_found()
    return "", 204


@app.route("/", methods=["POST"])
def create_root():
    body = request_data()
    url = body.get("value") or body.get("url")
    if not is_it_an_url(url):
        return invalid_url()
    with lock:
        short_id = generate_short_id()
        shared_dict[short_id] = url
    return jsonify({"id": short_id}), 201


@app.route("/", methods=["DELETE"])
def delete_root():
    # The specification asks for 404. The counter is not reset, so deleted
    # identifiers are still not reused.
    with lock:
        shared_dict.clear()
    return jsonify({"detail": "all mappings deleted"}), 404


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")))
