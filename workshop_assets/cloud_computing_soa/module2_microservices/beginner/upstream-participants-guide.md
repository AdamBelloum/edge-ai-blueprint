# Workshop: RESTful Microservices Architecture with JWT (Multi-User URL Shortener)


Compared with restful api, the system is now split into two services:

1. an **authentication service**
2. a **URL shortener service**

The authentication service creates users and issues JWTs.
The shortener service verifies JWTs locally with a **public key** and only allows a user to manage their own mappings.

---

# 1. Tutorial goals

The main changes in this tutorial are:

- add a separate authentication service
- support multiple users
- use JWTs for authentication
- sign JWTs with **RS256**
- validate JWTs in the shortener using a **public key**
- keep the signing secret in the authentication service
- make mappings user-specific so only the owner can manage them

---

# 2. Suggested local project structure

```
project/
├── auth_service/
│   ├── auth.py
│   ├── keys/
│   │   ├── private_key.pem
│   │   └── public_key.pem
├── shortener_service/
│   ├── shortener.py
│   ├── keys/
│   │   └── public_key.pem
```

For this tutorial, both services may still keep their state in memory.

---

# 3. Dependencies

Install the required libraries with:

~~~bash
pip install flask cryptography
~~~

---

# 4. Authentication service

The authentication service is responsible for:

- registering users
- updating user passwords
- logging users in
- generating JWTs signed with RS256

Its three main endpoints are:

- `POST /users`
- `PUT /users`
- `POST /users/login`

The implementation stores users in memory and creates RSA keys locally.

---

## 4.1 Imports and global variables

Start with the imports and a few global variables:

~~~python
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
~~~

### Explanation

- `Flask`, `jsonify`, and `request` are used to build the REST API.
- `os` is used to check whether the key files already exist.
- `json`, `base64`, and `time` are needed to manually build JWTs.
- `hashlib` is used to hash passwords.
- `cryptography` provides the RSA key generation and signature functions.

The dictionary `users_dict` stores users in memory as:

~~~python
users_dict[username] = password_hash
~~~

This is sufficient for this tutorial because the assignment still allows in-memory storage.

---

## 4.2 `base64url_encode(data)`

~~~python
def base64url_encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")
~~~

### What this function does

JWTs use **base64url encoding**, not normal base64.
This function:

1. encodes bytes using the URL-safe base64 alphabet
2. removes the trailing `=`
3. converts the result into a string

### Why it is needed

A JWT has the structure:

~~~text
header.payload.signature
~~~

Each part must be encoded in base64url format.

---

## 4.3 `hash_password(password)`

~~~python
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()
~~~

### What this function does

It hashes a password with SHA-256 and returns the hex representation.

### Why it is needed

We should not store raw passwords directly.
Instead of this:

~~~python
users_dict["alice"] = "mypassword"
~~~

we store:

~~~python
users_dict["alice"] = "<sha256 hash>"
~~~

This is a basic but much safer approach for the assignment.

---

## 4.4 `ensure_keys_exist()`

~~~python
def ensure_keys_exist():
    if os.path.exists(PRIVATE_KEY_FILE) and os.path.exists(PUBLIC_KEY_FILE):
        return

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )
    public_key = private_key.public_key()

    with open(PRIVATE_KEY_FILE, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
        )

    with open(PUBLIC_KEY_FILE, "wb") as f:
        f.write(
            public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
~~~

### What this function does

This function checks whether the key files already exist.

- if they already exist, it does nothing
- otherwise, it generates a new RSA key pair and writes both keys to disk

### Why it is needed

This tutorial requires JWT signing and validation.
Using RS256 means:

- the **private key** is used to sign
- the **public key** is used to verify

This function ensures that the authentication service has the required keys.

### Important design point

The authentication service uses both files, but the shortener should only use the **public key**.

---

## 4.5 `load_private_key()`

~~~python
def load_private_key():
    with open(PRIVATE_KEY_FILE, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)
~~~

### What this function does

It reads the private key from the PEM file and loads it into a Python object.

### Why it is needed

The private key is required when signing JWTs in the login endpoint.

---

## 4.6 `generate_jwt(username)`

~~~python
def generate_jwt(username):
    header = {
        "alg": "RS256",
        "typ": "JWT"
    }

    now = int(time.time())
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + 3600
    }

    header_b64 = base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

    private_key = load_private_key()
    signature = private_key.sign(
        signing_input,
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    signature_b64 = base64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"
~~~

### What this function does

This is the core JWT creation function. It:

1. defines the header
2. defines the payload
3. base64url-encodes both parts
4. concatenates them as `header.payload`
5. signs that data with the private key
6. base64url-encodes the signature
7. returns the final JWT string

### JWT header

~~~python
header = {
    "alg": "RS256",
    "typ": "JWT"
}
~~~

This states that:

- the token type is JWT
- the signing algorithm is RS256

### JWT payload

~~~python
payload = {
    "sub": username,
    "iat": now,
    "exp": now + 3600
}
~~~

This token stores only:

- `sub`: the username
- `iat`: issued-at timestamp
- `exp`: expiration timestamp

### Why this payload is small

This tutorial explicitly suggest not to put unnecessary information in the JWT.
So this implementation does **not** store:

- password
- password hash
- role
- email
- extra metadata

Only the minimum needed identity information is included.

### Why the function manually constructs the JWT

The tutorial explicitly says not to use a library that fully implements JWTs for you.
So here we manually assemble the token:

- JSON
- base64url
- signature

while still using `cryptography` for the RSA signing itself.

---

## 4.7 `create_user()` for `POST /users`

~~~python
@app.route("/users", methods=["POST"])
def create_user():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"detail": "Content of body was empty"}), 400

    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"detail": "username or password missing"}), 400

    if username in users_dict:
        return jsonify({"detail": "duplicate"}), 409

    users_dict[username] = hash_password(password)
    return jsonify({"message": "User created successfully"}), 201
~~~

### What this function does

This endpoint creates a new user.

### Step-by-step behavior

1. read the JSON body
2. reject empty bodies with `400`
3. extract `username` and `password`
4. reject missing fields with `400`
5. reject duplicate usernames with `409, "duplicate"`
6. hash the password
7. store the user
8. return `201`

### Example request

~~~bash
curl -X POST http://127.0.0.1:5001/users \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"test123"}'
~~~

---

## 4.8 `update_user_password()` for `PUT /users`

~~~python
@app.route("/users", methods=["PUT"])
def update_user_password():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"detail": "Content of body was empty"}), 400

    username = data.get("username")
    old_password = data.get("old_password")
    new_password = data.get("new_password")

    if not username or not old_password or not new_password:
        return jsonify({"detail": "username or password missing"}), 400

    if username not in users_dict:
        return jsonify({"detail": "forbidden"}), 403

    if users_dict[username] != hash_password(old_password):
        return jsonify({"detail": "forbidden"}), 403

    users_dict[username] = hash_password(new_password)
    return jsonify({"message": "Password updated successfully"}), 200
~~~

### What this function does

This endpoint updates the password of an existing user.

### Step-by-step behavior

1. read the JSON body
2. reject empty body with `400`
3. extract:
   - `username`
   - `old_password`
   - `new_password`
4. reject missing fields with `400`
5. if the user does not exist, return `403`
6. if the old password is wrong, return `403`
7. otherwise update the stored password hash
8. return `200`

### Why it returns `403`

The assignment specification for `PUT /users` explicitly says:

- return `200` on success
- return `403, "forbidden"` if the correct old password is not presented

So this implementation uses `403` for failed authorization.

---

## 4.9 `login_user()` for `POST /users/login`

~~~python
@app.route("/users/login", methods=["POST"])
def login_user():
    data = request.get_json(silent=True)

    if not data:
        return jsonify({"detail": "Content of body was empty"}), 400

    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"detail": "username or password missing"}), 400

    if username not in users_dict:
        return jsonify({"detail": "forbidden"}), 403

    if users_dict[username] != hash_password(password):
        return jsonify({"detail": "forbidden"}), 403

    token = generate_jwt(username)
    return jsonify({"token": token}), 200
~~~

### What this function does

This endpoint authenticates a user and returns a JWT.

### Step-by-step behavior

1. read the JSON body
2. reject empty body with `400`
3. extract `username` and `password`
4. reject missing fields with `400`
5. if the username does not exist, return `403`
6. if the password is wrong, return `403`
7. otherwise generate a JWT
8. return the JWT with `200`

### Why the response contains a token

After a successful login, the client must present this JWT to the shortener service when calling protected endpoints.

### Example request

~~~bash
curl -X POST http://127.0.0.1:5001/users/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"test123"}'
~~~

Example response:

~~~json
{
  "token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
}
~~~

---

## 4.10 Main block

~~~python
if __name__ == "__main__":
    ensure_keys_exist()
    app.run(host="127.0.0.1", port=5001, debug=True)
~~~

### What this does

Before the auth service starts, it ensures that the RSA keys exist.

Then it runs the Flask app on port `5001`.

---

# 5. URL shortener service

The shortener service now supports multiple users.
The key idea is that every mapping has an owner.

Instead of:

~~~python
shared_dict[id] = url
~~~

we now store:

~~~python
shared_dict[id] = {
    "url": long_url,
    "owner": username
}
~~~

This lets us enforce owner-specific behavior.

---

## 5.1 Imports and global variables

~~~python
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
~~~

### Explanation

- `redirect` is used to return a real HTTP `301` redirect
- `shared_dict` stores all mappings in memory
- `PUBLIC_KEY_FILE` points to the key used for local JWT verification

The shortener only uses the **public key**, not the private key.

---

## 5.2 `is_it_an_url(string)`

~~~python
def is_it_an_url(string):
    return isinstance(string, str) and (
        string.startswith("http://") or string.startswith("https://")
    )
~~~

### What this function does

It performs a simple URL validity check by verifying that:

- the value is a string
- it starts with `http://` or `https://`

### Why it is needed

The shortener should reject invalid URLs when creating or updating mappings.

### Note

This is a minimal validity check.
For a more complete version, a regex could be used, but for this implementation the simple prefix check is enough.

---

## 5.3 `generate_short_id(url)`

~~~python
def generate_short_id(url):
    return hashlib.md5(url.encode()).hexdigest()[:6]
~~~

### What this function does

It creates a short ID by:

1. hashing the URL with MD5
2. taking the first 6 hexadecimal characters

### Why it is needed

The service needs a deterministic way to assign an ID to a URL.

### Example

If the long URL is:

~~~text
https://example.com
~~~

then the service hashes it and uses the first 6 characters as the short ID.

### Note about collisions

Because only 6 characters are used, collisions are possible.
The implementation handles this in `create_root()` by rehashing if needed.

---

## 5.4 `base64url_decode(data)`

~~~python
def base64url_decode(data):
    padding_needed = 4 - (len(data) % 4)
    if padding_needed != 4:
        data += "=" * padding_needed
    return base64.urlsafe_b64decode(data.encode("utf-8"))
~~~

### What this function does

It reverses base64url encoding.

### Why the padding logic is needed

JWT parts are stored without trailing `=` characters.
To decode them correctly, we sometimes need to add the padding back.

This function makes sure the token parts can be decoded properly.

---

## 5.5 `load_public_key()`

~~~python
def load_public_key():
    with open(PUBLIC_KEY_FILE, "rb") as f:
        return serialization.load_pem_public_key(f.read())
~~~

### What this function does

It loads the public key from disk.

### Why it is needed

The shortener uses this key to verify JWT signatures locally.

This means the shortener does not need to contact the authentication service on every protected request.

---

## 5.6 `get_token_from_request()`

~~~python
def get_token_from_request():
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1].strip()

    token = request.headers.get("x-access-token")
    if token:
        return token.strip()

    return None
~~~

### What this function does

It extracts a token from the request headers.

It supports two formats:

1. `Authorization: Bearer <token>`
2. `x-access-token: <token>`

### Why it is needed

Protected endpoints need a way to read the JWT that the client sends.

### Why `Bearer` is used

`Authorization: Bearer ...` is the most common and standard style for sending JWTs.

---

## 5.7 `verify_jwt(token)`

~~~python
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
~~~

### What this function does

This is the core verification function. It:

1. splits the token into 3 parts
2. reconstructs the signed input
3. decodes the signature
4. loads the public key
5. verifies the RSA signature
6. decodes the payload JSON
7. checks whether the token is expired
8. checks whether `sub` exists
9. returns the username stored in `sub`

If anything goes wrong, it returns `None`.

### Why local verification matters

This tutorial explicitly suggests for a design where the shortener can validate tokens itself using the public key.
This avoids contacting the auth service for every operation.

### What is returned

If the token is valid, the function returns:

~~~python
payload["sub"]
~~~

which is the username.

If the token is invalid, it returns `None`.

---

## 5.8 `get_current_user()`

~~~python
def get_current_user():
    token = get_token_from_request()
    if not token:
        return None
    return verify_jwt(token)
~~~

### What this function does

It combines two earlier functions:

1. extract the token from the request
2. verify the token

### What it returns

- the username if the token is valid
- `None` if the token is missing or invalid

### Why it is useful

Most protected endpoints can simply call:

~~~python
username = get_current_user()
~~~

and then reject the request if `username is None`.

---

## 5.9 `read_root()` for `GET /`

~~~python
@app.route("/", methods=["GET"])
def read_root():
    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    # only return the keys owned by the current user
    user_keys = [key for key, value in shared_dict.items() if value["owner"] == username]
    return jsonify({"keys": user_keys}), 200
~~~

### What this function does

This endpoint returns the list of IDs owned by the currently authenticated user.

### Step-by-step behavior

1. get the current user from the JWT
2. if no valid user exists, return `403`
3. filter `shared_dict` to only the mappings owned by that user
4. return those keys with `200`

### Why it is protected

The updated specification explicitly includes `403, "forbidden"` for `GET /`.
This is one of the endpoints that should require authentication.

---

## 5.10 `read_item(id)` for `GET /<id>`

~~~python
@app.route("/<id>", methods=["GET"])
def read_item(id):
    value = shared_dict.get(id)

    if value is not None:
        # public endpoint for redirection, no need to check ownership here
        return redirect(value["url"], code=301)
    else:
        return jsonify({"detail": "Key not found in shared dictionary"}), 404
~~~

### What this function does

This endpoint resolves a short ID into the original URL.

### Step-by-step behavior

1. look up the ID in `shared_dict`
2. if it exists, return `301`
3. if it does not exist, return `404`

### Why there is no ownership check here

This implementation treats `GET /<id>` as the public resolution endpoint.
The user-specific restrictions are applied to the management endpoints, not the resolution itself.

### Why `redirect(..., code=301)` is used

The assignment says `GET /:id` should return `301, value`.
A real redirect is a natural interpretation of that behavior for a URL shortener.

---

## 5.11 `delete_root()` for `DELETE /`

~~~python
@app.route("/", methods=["DELETE"])
def delete_root():
    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    # only delete the entries owned by the current user
    ids_to_delete = [key for key, value in shared_dict.items() if value["owner"] == username]
    for key in ids_to_delete:
        del shared_dict[key]

    return jsonify({"detail": "All your shortened URLs have been deleted"}), 404
~~~

### What this function does

It deletes all URL mappings owned by the current user.

### Step-by-step behavior

1. authenticate the user
2. return `403` if the token is invalid
3. collect all IDs owned by that user
4. delete those entries
5. return `404`

### Why it returns `404`

This follows the 01 restapi tutorial style and the table, where `DELETE /` returns `404`.

### Important multi-user behavior

This function does **not** clear the entire dictionary.
It only deletes the entries of the current user.

That is one of the key changes that make the shortener multi-user.

---

## 5.12 `delete_item(id)` for `DELETE /<id>`

~~~python
@app.route("/<id>", methods=["DELETE"])
def delete_item(id):
    username = get_current_user()
    if username is None:
        return jsonify({"detail": "forbidden"}), 403

    if id not in shared_dict:
        return jsonify({"detail": "Key not found in shared dictionary"}), 404

    if shared_dict[id]["owner"] != username:
        return jsonify({"detail": "forbidden"}), 403

    del shared_dict[id]
    return "", 204
~~~

### What this function does

It deletes one specific shortened URL, but only if the current user owns it.

### Step-by-step behavior

1. authenticate the user
2. reject invalid or missing token with `403`
3. reject non-existing IDs with `404`
4. reject requests for another user's mapping with `403`
5. delete the mapping
6. return `204`

### Why owner checks are needed

Without this check, any authenticated user could delete any shortened URL.

This line is the core ownership check:

~~~python
if shared_dict[id]["owner"] != username:
    return jsonify({"detail": "forbidden"}), 403
~~~

---

## 5.13 `create_root()` for `POST /`

~~~python
@app.route("/", methods=["POST"])
def create_root():
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

    # To prevent direct overwriting in case of hash collisions
    while short_id in shared_dict and shared_dict[short_id]["url"] != str(long_url):
        short_id = hashlib.md5((str(long_url) + short_id).encode()).hexdigest()[:6]

    shared_dict[short_id] = {
        "url": str(long_url),
        "owner": username
    }

    return jsonify({"id": short_id}), 201
~~~

### What this function does

This endpoint creates a new short ID for a long URL.

### Step-by-step behavior

1. authenticate the user
2. reject invalid token with `403`
3. parse the JSON body
4. reject missing body with `400`
5. accept either:
   - `value`
   - or `url`
6. reject missing URL with `400`
7. validate the URL
8. generate a short ID
9. avoid direct overwrite in case of collision
10. store both:
    - the URL
    - the owner
11. return the generated ID with `201`

### Why both `value` and `url` are accepted

To stay compatible with the earlier Assignment 1 style and tests, this implementation first tries:

~~~python
data.get("value")
~~~

and then falls back to:

~~~python
data.get("url")
~~~

### Why the owner is stored here

This is the moment where the shortener becomes multi-user:

~~~python
shared_dict[short_id] = {
    "url": str(long_url),
    "owner": username
}
~~~

Every mapping is now tied to the user who created it.

### How collisions are handled

If two different URLs produce the same first 6 MD5 characters, the code rehashes with an adjusted input until the collision is avoided.

---

## 5.14 `update_item(id)` for `PUT /<id>`

~~~python
@app.route("/<id>", methods=["PUT"])
def update_item(id):
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
    return jsonify({"message": "Item updated successfully"}), 200
~~~

### What this function does

It updates the long URL behind an existing short ID.

### Step-by-step behavior

1. authenticate the user
2. reject invalid token with `403`
3. parse the JSON body
4. reject non-existing ID with `404`
5. reject updates to another user's mapping with `403`
6. reject invalid body with `400`
7. reject invalid URL with `400`
8. update the stored URL
9. return `200`

### Why `force=True` is used

This makes the function more tolerant when clients send JSON in slightly inconsistent ways.

### Why owner validation matters

This is another core multi-user check:

~~~python
if shared_dict[id]["owner"] != username:
    return jsonify({"detail": "forbidden"}), 403
~~~

Without it, one user could edit another user's mappings.

---

## 5.15 Main block

~~~python
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
~~~

### What this does

It starts the shortener service on port `5000`.

Before running it, make sure the public key file exists:

~~~text
keys/public_key.pem
~~~

---

# 6. Running the system

## Step 1: start the authentication service

~~~bash
python auth.py
~~~

This will also generate the key pair if the files do not exist yet.

## Step 2: start the shortener service

~~~bash
python shortener.py
~~~

The shortener expects the public key at:

~~~text
keys/public_key.pem
~~~

---

# 7. Typical request flow

## 7.1 Create a user

~~~bash
curl -X POST http://127.0.0.1:5001/users \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"test123"}'
~~~

## 7.2 Login and get a token

~~~bash
curl -X POST http://127.0.0.1:5001/users/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"test123"}'
~~~

Example response:

~~~json
{
  "token": "YOUR_JWT_TOKEN"
}
~~~

## 7.3 Create a shortened URL

~~~bash
curl -X POST http://127.0.0.1:5000/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{"value":"https://en.wikipedia.org/wiki/Docker_(software)"}'
~~~

## 7.4 List your own keys

~~~bash
curl http://127.0.0.1:5000/ \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
~~~

## 7.5 Update one of your mappings

~~~bash
curl -X PUT http://127.0.0.1:5000/abc123 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -d '{"url":"https://en.wikipedia.org/wiki/Flask_(web_framework)"}'
~~~

## 7.6 Delete one of your mappings

~~~bash
curl -X DELETE http://127.0.0.1:5000/abc123 \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
~~~

## 7.7 Resolve a short URL

~~~bash
curl -i http://127.0.0.1:5000/abc123
~~~

If the ID exists, the service returns `301`.

---

# 8. What changed compared with restful api tutorial

The key changes are:

1. the system is now split into two services
2. users can register and log in
3. the authentication service issues JWTs
4. JWTs are signed with RS256
5. the shortener validates JWTs locally with the public key
6. each URL mapping now stores an owner
7. only the owner can manage the mapping

So the biggest conceptual shift is:

- Tutorial 1: one shared in-memory dictionary for everyone
- Tutorial 2: one shared dictionary, but each entry belongs to a specific user

---

# 9. Final remarks

This implementation stays close to the tutorial 1 style while introducing the core requirements of tutorial 2:

- separate authentication service
- manual JWT construction
- RS256 signing
- public key verification
- multi-user URL management

Because the code is still kept in memory and uses simple Flask routes, it is also a good base for the next assignment, where persistence and containerization will be added.

---
### 10. References

1. [What are microservices?:](https://microservices.io/)
2. [Json Web Tokens (JWT):](https://jwt.io/introduction/)
3. [A Practical Guide for JWT Authentication using Nodejs and Express](https://medium.com/swlh/a-practical-guide-for-jwt-authentication-using-nodejs-and-express-d48369e7e6d4)
4. [Introduction to microservices:](https://www.nginx.com/blog/introduction-to-microservices/)
5. [An introduction to OAuth 2:](https://www.digitalocean.com/community/tutorials/an-introduction-to-oauth-2)
