"""
A minimal Flask REST API for storing URL values.

This application is intentionally small: it demonstrates how a REST API maps
HTTP methods and URL paths to Python functions. Data is stored only in memory,
so restarting the Flask process clears all records.

Run locally with:

    python app.py

The API listens at http://127.0.0.1:5000.
"""

from flask import Flask, jsonify, request
import hashlib


# Flask uses this object to register routes and start the web application.
app = Flask(__name__)

# This dictionary is our temporary data store:
#     short identifier -> URL value
#
# A real application would normally store this information in a database.
shared_dict = {}


def is_it_an_url(value):
    """Return True only when *value* looks like an HTTP or HTTPS URL."""
    return isinstance(value, str) and (
        value.startswith("http://") or value.startswith("https://")
    )


def generate_short_id(url):
    """
    Create a deterministic six-character identifier for a URL.

    hashlib.md5() converts the text into a hexadecimal hash. We retain only
    its first six characters to make an identifier that is easy to use in a
    route such as GET /abc123.
    """
    return hashlib.md5(url.encode()).hexdigest()[:6]


@app.route("/", methods=["GET"])
def read_root():
    """
    Return the identifiers currently stored by the API.

    jsonify() converts the Python dictionary into a JSON HTTP response.
    HTTP 200 means that the request completed successfully.
    """
    return jsonify({"keys": list(shared_dict.keys())}), 200


@app.route("/<id>", methods=["GET"])
def read_item(id):
    """
    Look up one stored value by its identifier.

    The <id> part of the route becomes the id function argument. For example,
    a request to GET /abc123 calls read_item("abc123").
    """
    value = shared_dict.get(id)

    if value is not None:
        # HTTP 301 is retained because it is part of this workshop's API
        # contract and automated tests. In most ordinary read APIs, 200 would
        # be the more conventional success status.
        return jsonify({"value": value}), 301

    # HTTP 404 means that the requested resource does not exist.
    return jsonify({"detail": "Key not found in shared dictionary"}), 404


@app.route("/", methods=["DELETE"])
def delete_root():
    """
    Remove every record from the temporary data store.

    This endpoint is useful during development and automated testing.
    """
    shared_dict.clear()

    # The workshop test contract expects HTTP 404 for this operation.
    return jsonify({"detail": "Shared dictionary has been emptied"}), 404


@app.route("/<id>", methods=["DELETE"])
def delete_item(id):
    """Remove one record, identified by its short id."""
    if id in shared_dict:
        del shared_dict[id]

        # HTTP 204 means successful deletion. A 204 response must not include
        # a response body, hence the empty string.
        return "", 204

    return jsonify({"detail": "Key not found in shared dictionary"}), 404


@app.route("/", methods=["POST"])
def create_root():
    """
    Create a new stored URL.

    Expected JSON request body:

        {"value": "https://example.org"}

    silent=True prevents Flask from returning its own error response for
    malformed JSON; this function can instead return a clear workshop-specific
    HTTP 400 response.
    """
    data = request.get_json(silent=True)

    # Reject an absent body, invalid JSON, or a missing/empty "value" field.
    if not data or not data.get("value"):
        return jsonify({"detail": "Content of body was empty"}), 400

    # Generate an id, store the supplied value, and report that a resource was
    # created. HTTP 201 is the standard status for successful creation.
    short_id = generate_short_id(data.get("value"))
    shared_dict[short_id] = data.get("value")
    return jsonify({"id": short_id}), 201


@app.route("/<id>", methods=["PUT"])
def update_item(id):
    """
    Replace the URL stored for one existing identifier.

    Expected JSON request body:

        {"url": "https://new-example.org"}
    """
    # force=True also accepts JSON sent by the workshop test client as raw
    # request data. silent=True lets us return our own HTTP 400 message.
    data = request.get_json(force=True, silent=True)

    # A PUT update may only change an existing resource.
    if id not in shared_dict:
        return jsonify({"detail": "id doesn't exist"}), 404

    # Validate both the expected field and a simple HTTP/HTTPS URL format.
    if not data or "url" not in data:
        return jsonify({"detail": "Update failed, invalid url"}), 400

    if not is_it_an_url(str(data["url"])):
        return jsonify({"detail": "Update failed, invalid url"}), 400

    shared_dict[id] = str(data["url"])
    return jsonify({"message": "Item updated successfully"}), 200


if __name__ == "__main__":
    # debug=True enables useful local error messages during the workshop.
    # host="127.0.0.1" exposes the server only on the local machine.
    app.run(host="127.0.0.1", port=5000, debug=True)
