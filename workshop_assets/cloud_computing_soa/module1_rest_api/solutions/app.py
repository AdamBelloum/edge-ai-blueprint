from flask import Flask, jsonify, request, make_response
import re
import hashlib

app = Flask(__name__)

shared_dict = {}


def is_it_an_url(string):
    return isinstance(string, str) and (
        string.startswith("http://") or string.startswith("https://")
    )

def generate_short_id(url):
    # Create a unique 6-character hash of the URL
    return hashlib.md5(url.encode()).hexdigest()[:6]

@app.route("/", methods=["GET"])
def read_root():
    # Return all keys from the shared dictionary
    return jsonify({"keys": list(shared_dict.keys())}), 200


@app.route("/<id>", methods=["GET"])
def read_item(id):
    value = shared_dict.get(id)

    if value is not None:
        return jsonify({"value": value}), 301
    else:
        return jsonify({"detail": "Key not found in shared dictionary"}), 404


@app.route("/", methods=["DELETE"])
def delete_root():
    # Empty the shared dictionary
    shared_dict.clear()
    # Test script requires a 404 response here
    return jsonify({"detail": "Shared dictionary has been emptied"}), 404


@app.route("/<id>", methods=["DELETE"])
def delete_item(id):
    # Remove the record with key 'id' from the shared dictionary
    if id in shared_dict:
        del shared_dict[id]
        # 204 should not include a response body
        return "", 204
    else:
        return jsonify({"detail": "Key not found in shared dictionary"}), 404


@app.route("/", methods=["POST"])
def create_root():
    data = request.get_json(silent=True)

    # Check if the request body is empty
    if not data or not data.get("value"):
        return jsonify({"detail": "Content of body was empty"}), 400

    # Add the value from the request body to the shared dictionary with a numeric key
    short_id = generate_short_id(data.get("value"))
    shared_dict[short_id] = data.get("value")
    return jsonify({"id": short_id}), 201


@app.route("/<id>", methods=["PUT"])
def update_item(id):
    # force=True is for compatibility with test requests.put(..., data=json.dumps(...))
    data = request.get_json(force=True, silent=True)

    if id not in shared_dict:
        return jsonify({"detail": "id doesn't exist"}), 404

    if not data or "url" not in data:
        return jsonify({"detail": "Update failed, invalid url"}), 400

    if is_it_an_url(str(data["url"])) is False:
        return jsonify({"detail": "Update failed, invalid url"}), 400

    shared_dict[id] = str(data["url"])
    return jsonify({"message": "Item updated successfully"}), 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)