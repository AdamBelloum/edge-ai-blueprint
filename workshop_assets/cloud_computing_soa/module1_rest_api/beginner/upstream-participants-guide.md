# RESTful URL Shortener Workshop with Flask

This guide provides a complete walkthrough for building a simple RESTful URL shortener in Flask. It is written to match the tutorial skeleton and the final implementation used in this workshop.

---

## 1. Understanding thea Problem & Architecture

### The Problem

A long URL can be inconvenient to share. A URL shortener solves this by storing a mapping between:

- a short ID
- a long URL

When a client accesses the short ID, the service finds the corresponding long URL and returns it.

In this workshop we store the mappings in a simple in-memory Python dictionary.

---

### The API Interface (Endpoints)

We use different HTTP methods to perform different actions:


| HTTP method | Endpoint | Description                               |
| ------------- | ---------- | ------------------------------------------- |
| GET         | /        | Return all stored short IDs               |
| GET         | /        | Return the URL stored for a specific ID   |
| POST        | /        | Create a new short ID for a submitted URL |
| PUT         | /        | Update the URL behind an existing ID      |
| DELETE      | /        | Delete one specific ID/URL mapping        |
| DELETE      | /        | Delete all stored mappings                |

---

### Response Codes Used in This Tutorial


| Status code | Meaning in this project                                             |
| ------------- | --------------------------------------------------------------------- |
| 200         | Request succeeded                                                   |
| 201         | New entry created successfully                                      |
| 204         | Entry deleted successfully, no content returned                     |
| 301         | Existing ID found; URL value returned                               |
| 400         | Invalid or missing request data                                     |
| 404         | ID not found, or global delete returns 404 in this assignment setup |

> Note: In a more typical web application, `GET /<id>` might perform a real redirect using the `Location` header. In this workshop the implementation returns a JSON body with status code `301` because that matches the required test behavior.

---

## 2. Flask 101: Setup & First Code

### What is Flask?

Flask is a lightweight Python web framework. It helps you define routes such as `/` and `/<id>`, receive HTTP requests, and send HTTP responses.

To check whether Flask is installed:

```bash
python3 -m flask --version
```

If Flask is not installed:

```bash
pip install flask
```

### The First Flask App

Create a file called `app.py`:

```python
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Server is running!"

if __name__ == "__main__":
    app.run(debug=True)
```

Run it:

```bash
python3 app.py
```

Then visit: `http://127.0.0.1:5000` — you should see `Server is running!`.

---

## 3. Step-by-Step Implementation from the Skeleton

This section fills in the TODO parts from the skeleton version.

### Step 1: Data Storage

In this tutorial we use a global dictionary as a temporary in-memory database.

Skeleton idea:

```python
shared_dict = {}
```

What it stores

The dictionary maps `short_id -> long_url`.

Example:

```json
{
  "1a": "https://example.com",
  "2a": "https://openai.com"
}
```

Final code:

```python
shared_dict = {}
```

### Step 2: URL Validation (is_it_an_url)

The skeleton asks you to implement a helper function that checks whether a string looks like a valid URL.

Minimal implementation for the workshop:

```python
def is_it_an_url(string):
    """
    Return True only when the input looks like a valid URL.
    Minimum expected logic:
    - input should be a string
    - should start with "http://" or "https://"
    """
    return isinstance(string, str) and (
        string.startswith("http://") or string.startswith("https://")
    )
```

This is intentionally simple and sufficient for the tests used in the workshop.

### Step 3: GET / — Return All Keys

Return information about all stored entries.

```python
@app.route("/", methods=["GET"])
def read_root():
    return jsonify({"keys": list(shared_dict.keys())}), 200
```

Example response:

```json
{
  "keys": ["1a", "2a"]
}
```

### Step 4: GET / — Return the Stored URL

Return the URL for a given short ID.

```python
@app.route("/<id>", methods=["GET"])
def read_item(id):
    value = shared_dict.get(id)
    if value is not None:
        return jsonify({"value": value}), 301
    else:
        return jsonify({"detail": "Key not found in shared dictionary"}), 404
```

Success example:

```json
{
  "value": "https://example.com"
}
```

Error example:

```json
{
  "detail": "Key not found in shared dictionary"
}
```

### Step 5: DELETE / — Delete Everything

Clear the whole dictionary.

```python
@app.route("/", methods=["DELETE"])
def delete_root():
    shared_dict.clear()
    return jsonify({"detail": "Shared dictionary has been emptied"}), 404
```

Note: Returning `404` here matches the assignment/test expectations, even though it's unusual for real APIs.

### Step 6: DELETE / — Delete One Entry

Delete a specific mapping.

```python
@app.route("/<id>", methods=["DELETE"])
def delete_item(id):
    if id in shared_dict:
        del shared_dict[id]
        return "", 204
    else:
        return jsonify({"detail": "Key not found in shared dictionary"}), 404
```

### Step 7: POST / — Create a New Short ID

Create a new mapping from a submitted URL. Expected input:

```json
{ "value": "https://example.com" }
```

Implementation:

```python
@app.route("/", methods=["POST"])
def create_root():
    data = request.get_json(silent=True)

    # Check if the request body is empty
    if not data or not data.get("value"):
        return jsonify({"detail": "Content of body was empty"}), 400

    short_id = generate_short_id(data.get("value"))
    shared_dict[short_id] = data.get("value")
    return jsonify({"id": short_id}), 201
```

Example `curl`:

```bash
curl -X POST http://127.0.0.1:5000/ \
  -H "Content-Type: application/json" \
  -d '{"value":"https://google.com"}'
```

### Step 8: PUT / — Update an Existing URL

Update the stored URL behind an existing ID. Expected input:

```json
{ "url": "https://new-example.com" }
```

Implementation:

```python
@app.route("/<id>", methods=["PUT"])
def update_item(id):
    data = request.get_json(force=True, silent=True)
    if id not in shared_dict:
        return jsonify({"detail": "id doesn't exist"}), 404
    if not data or "url" not in data:
        return jsonify({"detail": "Update failed, invalid url"}), 400
    if is_it_an_url(str(data["url"])) is False:
        return jsonify({"detail": "Update failed, invalid url"}), 400

    shared_dict[id] = str(data["url"])
    return jsonify({"message": "Item updated successfully"}), 200
```

---

## 4. Complete Final Code (example)

```python
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

```

---

## 5. How to Run

Save the code as `app.py`, then start the server:

```bash
python3 app.py
```

The server will run at: `http://127.0.0.1:5000`

---

## 6. How to Test Each Endpoint

Create a new entry

```bash
curl -X POST http://127.0.0.1:5000/ \
  -H "Content-Type: application/json" \
  -d '{"value":"https://google.com"}'
```

Get all keys

```bash
curl http://127.0.0.1:5000/
```

Get one URL by ID

```bash
curl http://127.0.0.1:5000/1a
```

Update one URL

```bash
curl -X PUT http://127.0.0.1:5000/1a \
  -H "Content-Type: application/json" \
  -d '{"url":"https://openai.com"}'
```

Delete one URL

```bash
curl -X DELETE http://127.0.0.1:5000/1a
```

Delete all mappings

```bash
curl -X DELETE http://127.0.0.1:5000/
```

---

## 7. Notes About Design Choices

**Why use a dictionary?** Because it is simple and easy to understand. A production system would use a real database.

**Why is the generated ID so simple?** The goal of this tutorial is to practice REST APIs and Flask routing, not ID optimization.

**Why does** `DELETE /` **return 404?** This is not typical REST design, but it matches the assignment/test behavior used in this tutorial.

**Why does** `GET /<id>` **return JSON instead of a real redirect?** Because this implementation is designed to be compatible with the expected test behavior. A more standard implementation could use Flask’s `redirect(...)`.

---

## 6. References

1. [Flask quickstart](https://flask.palletsprojects.com/en/stable/quickstart/)
2. [Flask Cheat Sheet](https://realpython.com/flask-blueprint/)
3. [Regular expresssion 101](https://regex101.com/)
4. [Learn RegEx](https://github.com/ziishaned/learn-regex/blob/master/README.md)
5. [iHateRegEx](https://ihateregex.io/expr/url/)
6. [HTTP status code](https://www.restapitutorial.com/httpstatuscodes)
7. [HTTP response status code](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Status)