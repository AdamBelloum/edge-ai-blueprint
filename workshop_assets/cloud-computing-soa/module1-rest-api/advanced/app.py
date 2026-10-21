from flask import Flask, jsonify, request
import re
import hashlib

app = Flask(__name__)

# TODO:
# Use a global in-memory dictionary to store short-id -> URL mappings.
# Example idea:
# {
#     "1a": "https://example.com",
#     "2a": "https://openai.com"
# }
shared_dict = {}


def is_it_an_url(string):
    """
    TODO:
    Return True only when the input looks like a valid URL for this assignment.

    Minimum expected logic:
    - input should be a string
    - should start with "http://" or "https://"

    You may keep the validation simple for the tutorial,
    or make it stricter with regex.
    We suggest you start with regex solutions.
    """
    pass

def generate_short_id(url):
    """
    TODO:
    Generate a unique 6-character hash of the URL.
    """
    pass


@app.route("/", methods=["GET"])
def read_root():
    """
    GET /

    Goal:
    Return information about all currently stored entries at the global level.

    Suggested behavior:
    - Return status code 200
    - Return a JSON object
    - The JSON can contain:
        * all keys only
        * all URLs only
        * or both
      For this tutorial, a simple structure is enough.

    Example response shape:
    {
        "keys": ["1a", "2a", "3a"]
    }

    TODO:
    - Read all keys from the shared dictionary
    - Wrap them in jsonify(...)
    - Return with status code 200
    """
    pass


@app.route("/<id>", methods=["GET"])
def read_item(id):
    """
    GET /<id>

    Goal:
    Given an ID, return the corresponding stored long URL.

    Expected logic:
    1. Look up the given id in the shared dictionary
    2. If found:
       - return the URL information
       - use status code 301
    3. If not found:
       - return an error message
       - use status code 404

    Example success response shape:
    {
        "value": "https://example.com"
    }

    Example error response shape:
    {
        "detail": "Key not found in shared dictionary"
    }

    TODO:
    - Read the value from shared_dict
    - Handle both found / not found cases
    """
    pass


@app.route("/", methods=["DELETE"])
def delete_root():
    """
    DELETE /

    Goal:
    Remove all entries from the service.

    Tutorial note:
    In a more typical API design, this might return 200 or 204.
    In this assignment/test setup, the chosen behavior is:
    - clear everything
    - return status code 404

    Example response shape:
    {
        "detail": "Shared dictionary has been emptied"
    }

    TODO:
    - Empty the dictionary
    - Return a JSON message
    - Return the required status code
    """
    pass


@app.route("/<id>", methods=["DELETE"])
def delete_item(id):
    """
    DELETE /<id>

    Goal:
    Delete one specific entry by id.

    Expected logic:
    1. Check whether id exists in shared_dict
    2. If yes:
       - delete it
       - return status code 204
       - ideally with an empty body
    3. If no:
       - return an error message
       - return status code 404

    Example error response shape:
    {
        "detail": "Key not found in shared dictionary"
    }

    TODO:
    - Check whether id exists
    - Delete if present
    - Return the correct status code
    """
    pass


@app.route("/", methods=["POST"])
def create_root():
    """
    POST /

    Goal:
    Create a new short id for a URL provided in the request body.

    Expected input shape:
    {
        "value": "https://example.com"
    }

    Expected logic:
    1. Read JSON body from the request
    2. Validate that the body is not empty
    3. Validate that the expected field exists
    4. Validate whether the URL is well formed
    5. Generate a new short id
    6. Store the mapping in shared_dict
    7. Return the new id with status code 201

    Example success response shape:
    {
        "id": "3a"
    }

    Example error response shape:
    {
        "detail": "Content of body was empty"
    }

    Hints:
    - request.get_json(...) is useful here
    - a simple id strategy for this tutorial:
        using hashlib

    TODO:
    - Parse JSON request body
    - Validate input
    - Create new id
    - Save to dictionary
    - Return JSON response with 201
    """
    pass


@app.route("/<id>", methods=["PUT"])
def update_item(id):
    """
    PUT /<id>

    Goal:
    Update the URL stored behind an existing id.

    Expected input shape:
    {
        "url": "https://new-example.com"
    }

    Expected logic:
    1. Parse request body as JSON
    2. Check whether the id exists
       - if not, return 404
    3. Check whether the body contains "url"
       - if not, return 400
    4. Validate whether the new URL is valid
       - if invalid, return 400
    5. Replace the old value in shared_dict
    6. Return a success message with status code 200

    Example success response shape:
    {
        "message": "Item updated successfully"
    }

    Example 404 response shape:
    {
        "detail": "id doesn't exist"
    }

    Example 400 response shape:
    {
        "detail": "Update failed, invalid url"
    }

    Hints:
    - request.get_json(...) can be used to read the request body
    - some tests may send JSON in a non-ideal way, so think about how tolerant
      you want your parser to be in this tutorial

    TODO:
    - Parse input JSON
    - Check id existence
    - Check whether "url" exists
    - Validate URL
    - Update dictionary
    - Return success response
    """
    pass


if __name__ == "__main__":
    """
    TODO:
    Start the Flask development server.

    Suggested config for local testing:
    - host="127.0.0.1"
    - port=5000
    - debug=True
    """
    app.run()