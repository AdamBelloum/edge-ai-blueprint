"""Grading script for Assignments 2 and 3 (URL shortener with authentication).

The script sends HTTP requests to the running services and checks the
answers against the assignments. Every check belongs to a line of the
grading rubric. Run the file directly to see the points per line.

Assignment 2, with the services on this machine or at the given URLs:

    python test_microservices.py
    python test_microservices.py --url http://HOST:5000 --auth-url http://HOST:5001

Assignment 3.1 (Docker Compose). Run it in the folder with docker-compose.yml;
the script restarts the containers to check that the data persists:

    python test_microservices.py --assignment 3.1 --restart "docker compose down && docker compose up -d"

Assignment 3.2 (Kubernetes). Pass the URLs of the Services, and run it where
kubectl works (for example on the control-plane VM) to check the cluster:

    python test_microservices.py --assignment 3.2 --url http://HOST:PORT --auth-url http://HOST:PORT --namespace NAMESPACE

    python -m unittest -v        # pass/fail only, for all test files here

test_ownership_isolation.py holds the multi-user checks, which count for the
shortener's points in Assignment 2. The checks create accounts and mappings.
They delete their mappings afterwards; the accounts remain, since the API has
no way to delete them.

Requests follow the course test script: JSON bodies, {"value": URL} for
POST / and {"url": URL} for PUT /<id>. The token from POST /users/login (a
"token", "access_token" or "jwt" field, or the plain body) is sent as
"Authorization: Bearer <token>"; if the shortener does not accept that, the
token alone in Authorization, or in an x-access-token header, is tried. For
GET /<id>, status 301 with either a Location header or the URL in a JSON
body counts.

Only what can be observed over HTTP and with kubectl is tested. The points
that need the TA's judgement are listed after the results. Requires the
requests package.
"""
import argparse
import base64
import collections
import csv
import json
import os
import random
import re
import shlex
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path
from urllib.parse import unquote

import requests

SHORTENER_URL = os.environ.get("SHORTENER_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
AUTH_URL = os.environ.get("AUTH_BASE_URL", "http://127.0.0.1:5001").rstrip("/")
RESTART_COMMAND = os.environ.get("RESTART_COMMAND", "")
NAMESPACE = os.environ.get("K8S_NAMESPACE", "")
KUBECTL = shlex.split(os.environ.get("KUBECTL", "kubectl"))
TIMEOUT = (5, 30)  # seconds to connect, seconds to wait for the answer

API_TESTS = [
    "TestApi.test_get_request_with_id_success",
    "TestApi.test_get_request_with_id_expect_404",
    "TestApi.test_put_id",
    "TestApi.test_deletion_id",
    "TestApi.test_get_all",
    "TestApi.test_post",
    "TestApi.test_deletion_all",
]
AUTH_TESTS = ["TestAuthService.test_create_user", "TestAuthService.test_change_password", "TestAuthService.test_login"]

# Per assignment: title, rubric lines checked here as (description, points,
# tests that must all pass), and the lines that need the TA's judgement.
RUBRICS = {
    "2": (
        "Assignment 2",
        [
            ("Authentication: POST /users (201, 409 \"duplicate\")", 1, ["TestAuthService.test_create_user"]),
            ("Authentication: PUT /users (200, 403 \"forbidden\")", 1, ["TestAuthService.test_change_password"]),
            ("Authentication: POST /users/login (200 JWT, 403 \"forbidden\")", 1, ["TestAuthService.test_login"]),
            ("Shortener: GET /:id (301, 404), public", 1, API_TESTS[:2]),
            ("Shortener: PUT /:id, only by the owner", 1,
             ["TestApi.test_put_id", "TestOwnershipIsolation.test_other_user_cannot_update"]),
            ("Shortener: DELETE /:id, only by the owner", 1,
             ["TestApi.test_deletion_id", "TestOwnershipIsolation.test_other_user_cannot_delete"]),
            ("Shortener: GET / lists only the user's keys", 1,
             ["TestApi.test_get_all", "TestOwnershipIsolation.test_list_shows_only_own_mappings"]),
            ("Shortener: POST /, the same URL keeps users apart", 1,
             ["TestApi.test_post", "TestOwnershipIsolation.test_same_url_keeps_owners_apart"]),
            ("Shortener: DELETE / removes only the user's mappings", 1,
             ["TestApi.test_deletion_all", "TestOwnershipIsolation.test_delete_all_keeps_other_users_mappings"]),
            ("JWT: sensible contents, no password", 1, ["TestJwt.test_token_contents"]),
            ("JWT: changed or unsigned tokens are rejected", 1, ["TestJwt.test_forged_tokens_are_rejected"]),
        ],
        [
            ("Authentication: other relevant functions", 1),
            ("Microservice mentality", 4),
            ("Presentation", 4),
            ("Report", 20),
            ("Questions 3 to 5", 15),
        ],
    ),
    "3.1": (
        "Assignment 3.1, containers",
        [
            ("URL shortener container: the API works", 2, API_TESTS),
            ("URL shortener container: mappings survive a restart", 1,
             ["TestPersistence.test_mappings_survive_restart"]),
            ("Authentication container: the API works", 2, AUTH_TESTS),
            ("Authentication container: accounts survive a restart", 1,
             ["TestPersistence.test_accounts_survive_restart"]),
        ],
        [
            ("Both containers: small images, efficient builds", 2),
            ("Presentation (shared with 3.2)", 4),
            ("Report (shared with 3.2)", 18),
        ],
    ),
    "3.2": (
        "Assignment 3.2, Kubernetes",
        [
            ("Kubernetes cluster: 3 nodes, all Ready", 4, ["TestKubernetes.test_cluster_nodes"]),
            ("Deployments: one per service, all replicas available", 1, ["TestKubernetes.test_deployments"]),
            ("Deployments: 3 replicas of a service, same data from each", 1,
             ["TestKubernetes.test_three_replicas", "TestReplicas.test_consistent_view"]),
            ("Services: one for each Deployment", 1, ["TestKubernetes.test_services"]),
            ("Services: reachable from outside the cluster", 1,
             ["TestKubernetes.test_service_types", "TestReplicas.test_reachable"]),
        ],
        [
            ("Presentation (shared with 3.1)", 4),
            ("Report (shared with 3.1)", 18),
            ("Question: load balancing", 5),
        ],
    ),
}

CSV_ROWS = []
NOTES = []  # observations printed after the points


def setUpModule():
    path = Path(__file__).with_name("read_from.csv")
    with path.open(encoding="utf-8", newline="") as stream:
        CSV_ROWS.extend(row for row in csv.DictReader(stream) if row.get("url_to_shorten_1"))


def call(method, url, **kwargs):
    """Send a request. Redirects are not followed."""
    try:
        return requests.request(method, url, allow_redirects=False, timeout=TIMEOUT, **kwargs)
    except requests.ConnectionError:
        raise AssertionError(f"{method} {url}: cannot connect; is the service running?") from None
    except requests.Timeout:
        raise AssertionError(f"{method} {url}: no answer within {TIMEOUT[1]} seconds") from None


def body_of(response):
    """The decoded JSON body of a response, or None."""
    try:
        return response.json()
    except ValueError:
        return None


def describe(response):
    """Status code and the start of the body, for failure messages."""
    text = " ".join(response.text.split())
    if len(text) > 100:
        text = text[:97] + "..."
    return f"{response.status_code} {text}".strip()


def returned_id(response):
    """The identifier in the answer to POST /, or None."""
    body = body_of(response)
    if isinstance(body, dict):
        for key in ("id", "key", "short_id", "identifier"):
            value = body.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value):
                return str(value)
        values = [value for value in body.values() if isinstance(value, str) and value]
        return values[0] if len(values) == 1 else None
    if isinstance(body, (str, int)) and not isinstance(body, bool):
        return str(body)
    text = response.text.strip()
    if body is None and text and len(text) <= 64 and not any(char.isspace() for char in text):
        return text
    return None


def target_of(response):
    """The URL a 301 answer points to: the Location header, or the URL in the JSON body."""
    location = response.headers.get("Location")
    if location:
        return location
    body = body_of(response)
    if isinstance(body, dict):
        for key in ("value", "url", "long_url", "target"):
            if isinstance(body.get(key), str):
                return body[key]
        values = [value for value in body.values() if isinstance(value, str)]
        return values[0] if len(values) == 1 else None
    return body if isinstance(body, str) else None


def same_url(first, second):
    """Compare URLs, ignoring percent-encoding (a Location header must be ASCII)."""
    return first is not None and second is not None and unquote(first) == unquote(second)


def listed_items(value):
    """What a JSON answer lists: dictionary keys, strings, and numbers in lists."""
    if isinstance(value, dict):
        found = {str(key) for key in value}
        for item in value.values():
            found |= listed_items(item)
        return found
    if isinstance(value, list):
        found = set()
        for item in value:
            if isinstance(item, int) and not isinstance(item, bool):
                found.add(str(item))
            else:
                found |= listed_items(item)
        return found
    return {value} if isinstance(value, str) else set()


def unknown_id():
    """An identifier the service does not know.

    read_from.csv has a column not_existing_id ("1", "2"), but those are valid
    identifiers when ids come from a counter, so a random one is used instead.
    """
    return "unknown" + uuid.uuid4().hex[:10]


def base64url_decode(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def base64url_encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def jwt_parts(token):
    """The decoded header and payload of a JWT."""
    try:
        header_b64, payload_b64, _ = token.split(".")
        header = json.loads(base64url_decode(header_b64))
        payload = json.loads(base64url_decode(payload_b64))
    except (AttributeError, ValueError):
        raise AssertionError(f"the login token is not a JWT (header.payload.signature): {token!r:.80}") from None
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise AssertionError(f"the JWT header and payload must be JSON objects: {header!r:.80}, {payload!r:.80}")
    return header, payload


def token_in(response):
    """The token in the answer to POST /users/login, or None."""
    body = body_of(response)
    if isinstance(body, dict):
        for key in ("token", "access_token", "jwt"):
            if isinstance(body.get(key), str) and body[key]:
                return body[key]
        values = [value for value in body.values() if isinstance(value, str) and value]
        return values[0] if len(values) == 1 else None
    if isinstance(body, str):
        return body
    text = response.text.strip()
    return text if body is None and text.count(".") == 2 and " " not in text else None


# Ways to send a token, tried in this order. The first that the shortener
# accepts is used for all requests.
TOKEN_HEADERS = [("Authorization", "Bearer {}"), ("Authorization", "{}"), ("x-access-token", "{}")]
token_header = None


def find_token_header(token):
    """Find out how the shortener expects the token, using a valid one."""
    global token_header
    if token_header is not None:
        return
    response = None
    for name, value in TOKEN_HEADERS:
        response = call("GET", SHORTENER_URL + "/", headers={name: value.format(token)})
        if response.status_code == 200:
            token_header = (name, value)
            NOTES.append(f"Tokens were sent as \"{name}: {value.format('<token>')}\".")
            return
    raise AssertionError(
        f"GET / with a valid token: expected 200, got {describe(response)} (tried "
        "\"Authorization: Bearer <token>\", \"Authorization: <token>\" and \"x-access-token: <token>\")"
    )


def token_headers(token):
    """Headers that carry the token, in the form the shortener accepts."""
    name, value = token_header or TOKEN_HEADERS[0]
    return {name: value.format(token)}


class User:
    """A test account with a unique name."""

    def __init__(self, label):
        self.name = f"{label}_{uuid.uuid4().hex[:10]}"
        self.password = "pw_" + uuid.uuid4().hex[:12]
        self.token = None

    def register(self):
        return call("POST", AUTH_URL + "/users", json={"username": self.name, "password": self.password})

    def login(self, password=None):
        body = {"username": self.name, "password": password or self.password}
        response = call("POST", AUTH_URL + "/users/login", json=body)
        if response.status_code == 200:
            self.token = token_in(response)
        return response

    def change_password(self, old_password, new_password):
        # Implementations name these fields differently, so the common names
        # are all sent: the course test script used "password" and
        # "new_password", the assignment's table :old-password and :new-password.
        body = {
            "username": self.name,
            "password": old_password, "old_password": old_password,
            "old-password": old_password, "oldPassword": old_password,
            "new_password": new_password, "new-password": new_password, "newPassword": new_password,
        }
        return call("PUT", AUTH_URL + "/users", json=body)

    def request(self, method, path, **kwargs):
        """A request to the shortener with this user's token."""
        return call(method, SHORTENER_URL + path, headers=token_headers(self.token), **kwargs)

    def delete_all(self):
        try:
            self.request("DELETE", "/")
        except AssertionError:
            pass


def signed_up(label):
    """A new account that is registered and logged in."""
    user = User(label)
    response = user.register()
    if response.status_code != 201:
        raise AssertionError(f"POST /users for a new account: expected 201, got {describe(response)}")
    response = user.login()
    if response.status_code != 200 or not user.token:
        raise AssertionError(f"POST /users/login: expected 200 and a token, got {describe(response)}")
    find_token_header(user.token)
    return user


def kubectl(*arguments):
    """Run kubectl with -o json and return the parsed output."""
    command = KUBECTL + list(arguments) + ["-o", "json"]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise AssertionError(f"{KUBECTL[0]} not found: run this where kubectl works, or set KUBECTL") from None
    if completed.returncode != 0:
        raise AssertionError(f"{' '.join(command)} failed: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


def wait_until_up(seconds=120):
    """Wait until both services answer HTTP requests again."""
    deadline = time.monotonic() + seconds
    for url in (AUTH_URL + "/users/login", SHORTENER_URL + "/"):
        while True:
            try:
                requests.get(url, timeout=TIMEOUT)  # any answer will do
                break
            except requests.RequestException:
                if time.monotonic() > deadline:
                    raise AssertionError(f"{url} did not answer within {seconds} seconds after the restart")
                time.sleep(2)


class GradingTest(unittest.TestCase):
    longMessage = False

    def assert_status(self, response, expected, action):
        self.assertEqual(expected, response.status_code,
                         f"{action}: expected {expected}, got {describe(response)}")

    def assert_says(self, response, word, action):
        self.assertIn(word, response.text.lower(),
                      f"{action}: the answer should say \"{word}\", got {describe(response)}")

    def create(self, user, url):
        """POST / with url as user, and return the new identifier."""
        response = user.request("POST", "/", json={"value": url})
        self.assert_status(response, 201, f"POST / with {url!r}")
        short_id = returned_id(response)
        self.assertTrue(short_id, f"POST / with {url!r}: no id in the answer {describe(response)}")
        return short_id

    def assert_points_to(self, short_id, url):
        response = call("GET", f"{SHORTENER_URL}/{short_id}")
        self.assert_status(response, 301, f"GET /{short_id}")
        target = target_of(response)
        self.assertTrue(same_url(target, url), f"GET /{short_id}: expected {url!r}, got {target!r}")

    def listed_by(self, user):
        """What GET / returns for user."""
        response = user.request("GET", "/")
        self.assert_status(response, 200, f"GET / as {user.name}")
        return listed_items(body_of(response))


class TestAuthService(GradingTest):
    """The authentication service."""

    def test_create_user(self):
        user = User("create")
        self.assert_status(user.register(), 201, "POST /users with a new username")
        response = user.register()
        self.assert_status(response, 409, "POST /users with the same username again")
        self.assert_says(response, "duplicate", "POST /users with the same username again")

    def test_change_password(self):
        user = User("password")
        self.assert_status(user.register(), 201, "POST /users")
        new_password = "new_" + uuid.uuid4().hex[:12]
        response = user.change_password("wrong_" + user.password, new_password)
        self.assert_status(response, 403, "PUT /users with a wrong old password")
        self.assert_says(response, "forbidden", "PUT /users with a wrong old password")
        response = user.change_password(user.password, new_password)
        self.assert_status(response, 200, "PUT /users with the right old password")
        self.assert_status(user.login(new_password), 200, "POST /users/login with the new password")
        self.assert_status(user.login(), 403, "POST /users/login with the old password")

    def test_login(self):
        user = User("login")
        self.assert_status(user.register(), 201, "POST /users")
        response = user.login()
        self.assert_status(response, 200, "POST /users/login with the right password")
        self.assertTrue(user.token and user.token.count(".") == 2,
                        f"POST /users/login: no JWT in the answer {describe(response)}")
        response = user.login("wrong_" + user.password)
        self.assert_status(response, 403, "POST /users/login with a wrong password")
        self.assert_says(response, "forbidden", "POST /users/login with a wrong password")
        self.assert_status(User("nobody").login(), 403, "POST /users/login with an unknown username")


class TestApi(GradingTest):
    """The seven test functions of the course test script, with a token."""

    @classmethod
    def setUpClass(cls):
        cls.user = signed_up("owner")
        cls.wrong = token_headers("wrong")

    def setUp(self):
        row = random.choice(CSV_ROWS)
        self.url_1 = row["url_to_shorten_1"]
        self.url_2 = row["url_to_shorten_2"]
        self.url_after_update = row["url_after_update"]
        self.invalid_url = row["invalid_url"]
        self.id_1 = self.create(self.user, self.url_1)
        self.id_2 = self.create(self.user, self.url_2)

    def tearDown(self):
        self.user.delete_all()

    def test_get_request_with_id_success(self):
        self.assert_points_to(self.id_1, self.url_1)

    def test_get_request_with_id_expect_404(self):
        self.assert_status(call("GET", f"{SHORTENER_URL}/{unknown_id()}"), 404, "GET /<unknown id>")

    def test_put_id(self):
        path = f"/{self.id_1}"
        response = call("PUT", SHORTENER_URL + path, headers=self.wrong, json={"url": self.url_after_update})
        self.assert_status(response, 403, f"PUT {path} with an invalid token")
        response = self.user.request("PUT", path, json={"url": self.url_after_update})
        self.assert_status(response, 200, f"PUT {path} with a valid URL")
        self.assert_points_to(self.id_1, self.url_after_update)
        response = self.user.request("PUT", path, json={"url": self.invalid_url})
        self.assert_status(response, 400, f"PUT {path} with {self.invalid_url!r}")
        response = self.user.request("PUT", f"/{unknown_id()}", json={"url": self.url_after_update})
        self.assert_status(response, 404, "PUT /<unknown id>")

    def test_deletion_id(self):
        path = f"/{self.id_1}"
        self.assert_status(self.user.request("DELETE", path), 204, f"DELETE {path}")
        response = call("DELETE", SHORTENER_URL + path, headers=self.wrong)
        self.assert_status(response, 403, f"DELETE {path} with an invalid token")
        self.assert_status(self.user.request("DELETE", path), 404, f"DELETE {path} a second time")
        self.assert_status(call("GET", SHORTENER_URL + path), 404, f"GET {path} after deleting it")

    def test_get_all(self):
        response = call("GET", SHORTENER_URL + "/", headers=self.wrong)
        self.assert_status(response, 403, "GET / with an invalid token")
        listed = self.listed_by(self.user)
        for short_id, url in ((self.id_1, self.url_1), (self.id_2, self.url_2)):
            self.assertTrue(short_id in listed or url in listed, f"GET /: id {short_id!r} is not listed")

    def test_post(self):
        url = "https://en.wikipedia.org/wiki/Docker_(software)"
        response = call("POST", SHORTENER_URL + "/", headers=self.wrong, json={"value": url})
        self.assert_status(response, 403, "POST / with an invalid token")
        self.assert_points_to(self.create(self.user, url), url)
        response = self.user.request("POST", "/", json={"value": ""})
        self.assert_status(response, 400, "POST / with an empty URL")

    def test_deletion_all(self):
        response = call("DELETE", SHORTENER_URL + "/", headers=self.wrong)
        self.assert_status(response, 403, "DELETE / with an invalid token")
        self.assert_status(self.user.request("DELETE", "/"), 404, "DELETE /")
        left = self.listed_by(self.user) & {self.id_1, self.id_2, self.url_1, self.url_2}
        self.assertFalse(left, f"GET / after DELETE / still lists {sorted(left)}")
        self.assert_status(call("GET", f"{SHORTENER_URL}/{self.id_1}"), 404, f"GET /{self.id_1} after DELETE /")


class TestJwt(GradingTest):
    """The tokens: sensible contents, and the shortener checks the signature."""

    @classmethod
    def setUpClass(cls):
        cls.user = signed_up("jwt")

    def tearDown(self):
        self.user.delete_all()

    def test_token_contents(self):
        header, payload = jwt_parts(self.user.token)
        algorithm = str(header.get("alg", "none"))
        self.assertNotEqual("none", algorithm.lower(), f"JWT header {header}: the token is not signed")
        self.assertTrue(payload, "the JWT payload is empty: it should identify the user")
        self.assertNotIn(self.user.password, json.dumps(payload), "the JWT contains the password")
        secret = [claim for claim in payload if re.search("pass|pwd|hash|secret", claim, re.IGNORECASE)]
        self.assertFalse(secret, f"JWT payload {payload}: a token should not contain {secret}")
        NOTES.append(f"JWT header {json.dumps(header)}; payload claims: {', '.join(sorted(payload))}.")

    def test_forged_tokens_are_rejected(self):
        url = f"https://example.com/{uuid.uuid4().hex[:8]}/jwt"
        short_id = self.create(self.user, url)
        _, payload = jwt_parts(self.user.token)
        header_b64, payload_b64, signature_b64 = self.user.token.split(".")
        payload["exp"] = int(time.time()) + 365 * 24 * 3600
        changed = base64url_encode(json.dumps(payload).encode("utf-8"))
        unsigned_header = base64url_encode(b'{"alg":"none","typ":"JWT"}')
        forged = {
            "a token whose payload was changed": f"{header_b64}.{changed}.{signature_b64}",
            "an unsigned token (alg none)": f"{unsigned_header}.{payload_b64}.",
        }
        for description, token in forged.items():
            response = call("GET", SHORTENER_URL + "/", headers=token_headers(token))
            self.assert_status(response, 403, f"GET / with {description}")
            response = call("DELETE", f"{SHORTENER_URL}/{short_id}", headers=token_headers(token))
            self.assert_status(response, 403, f"DELETE /{short_id} with {description}")
        self.assert_points_to(short_id, url)


class TestPersistence(GradingTest):
    """Assignment 3.1: the data survives restarting the containers (--restart)."""

    @classmethod
    def setUpClass(cls):
        if not RESTART_COMMAND:
            raise unittest.SkipTest("give --restart to check this")
        cls.user = signed_up("persist")
        cls.url = f"https://example.com/{uuid.uuid4().hex[:8]}/persist"
        response = cls.user.request("POST", "/", json={"value": cls.url})
        cls.short_id = returned_id(response)
        if response.status_code != 201 or not cls.short_id:
            raise AssertionError(f"POST /: expected 201 and an id, got {describe(response)}")
        print(f"\nRestarting the services: {RESTART_COMMAND}", file=sys.stderr, flush=True)
        completed = subprocess.run(RESTART_COMMAND, shell=True)
        if completed.returncode != 0:
            raise AssertionError(f"the restart command failed with exit code {completed.returncode}")
        wait_until_up()

    @classmethod
    def tearDownClass(cls):
        try:
            if cls.user.login().status_code == 200:
                cls.user.delete_all()
        except AssertionError:
            pass

    def test_accounts_survive_restart(self):
        response = self.user.login()
        self.assert_status(response, 200, "POST /users/login after the restart, for an account made before it")

    def test_mappings_survive_restart(self):
        self.assert_points_to(self.short_id, self.url)


class TestReplicas(GradingTest):
    """Assignment 3.2: the services answer through their URLs, and every
    replica gives the same answers."""

    def test_reachable(self):
        user = signed_up("reachable")  # POST /users and /users/login
        self.listed_by(user)  # GET / on the shortener
        user.delete_all()

    def test_consistent_view(self):
        user = signed_up("replicas")
        try:
            run = uuid.uuid4().hex[:8]
            urls = [f"https://example.com/{run}/{number}" for number in range(5)]
            ids = [self.create(user, url) for url in urls]
            served_by = collections.Counter()
            for number in range(30):
                short_id, url = ids[number % 5], urls[number % 5]
                response = call("GET", f"{SHORTENER_URL}/{short_id}")
                served_by[response.headers.get("X-Served-By")] += 1
                self.assert_status(response, 301, f"GET /{short_id} (request {number + 1} of 30)")
                target = target_of(response)
                self.assertTrue(same_url(target, url),
                                f"GET /{short_id} (request {number + 1} of 30): expected {url!r}, got {target!r}")
            for number in range(10):
                missing = set(ids) - self.listed_by(user)
                self.assertFalse(missing, f"GET / (request {number + 1} of 10) does not list {sorted(missing)}")
            if None not in served_by:
                counts = ", ".join(f"{name} {count}" for name, count in sorted(served_by.items()))
                NOTES.append(f"Requests per replica (X-Served-By header): {counts}.")
        finally:
            user.delete_all()


class TestKubernetes(GradingTest):
    """Assignment 3.2: the cluster as kubectl shows it (--namespace)."""

    @classmethod
    def setUpClass(cls):
        if not NAMESPACE:
            raise unittest.SkipTest("give --namespace to check the cluster with kubectl")
        cls.nodes = kubectl("get", "nodes")["items"]
        cls.deployments = kubectl("get", "deployments", "--namespace", NAMESPACE)["items"]
        cls.services = kubectl("get", "services", "--namespace", NAMESPACE)["items"]

    def services_for(self, deployment):
        """The Services whose selector matches the Deployment's pods."""
        labels = deployment["spec"]["template"]["metadata"].get("labels", {})
        return [
            service for service in self.services
            if service["spec"].get("selector")
            and all(labels.get(key) == value for key, value in service["spec"]["selector"].items())
        ]

    def test_cluster_nodes(self):
        not_ready = [
            node["metadata"]["name"] for node in self.nodes
            if not any(condition["type"] == "Ready" and condition["status"] == "True"
                       for condition in node["status"].get("conditions", []))
        ]
        self.assertGreaterEqual(len(self.nodes), 3, f"kubectl get nodes shows {len(self.nodes)} nodes, expected 3")
        self.assertFalse(not_ready, f"nodes that are not Ready: {not_ready}")

    def test_deployments(self):
        names = [deployment["metadata"]["name"] for deployment in self.deployments]
        self.assertGreaterEqual(len(names), 2, f"Deployments in {NAMESPACE}: {names}, expected one per service")
        for deployment in self.deployments:
            wanted = deployment["spec"].get("replicas", 1)
            ready = deployment["status"].get("readyReplicas", 0)
            self.assertGreaterEqual(ready, wanted,
                                    f"Deployment {deployment['metadata']['name']}: {ready} of {wanted} replicas ready")

    def test_three_replicas(self):
        ready = {d["metadata"]["name"]: d["status"].get("readyReplicas", 0) for d in self.deployments}
        self.assertTrue(any(count >= 3 for count in ready.values()), f"no Deployment has 3 ready replicas: {ready}")

    def test_services(self):
        for deployment in self.deployments:
            self.assertTrue(self.services_for(deployment),
                            f"no Service in {NAMESPACE} selects the pods of Deployment {deployment['metadata']['name']}")

    def test_service_types(self):
        for deployment in self.deployments:
            types = {service["spec"]["type"] for service in self.services_for(deployment)}
            self.assertTrue(types & {"NodePort", "LoadBalancer"},
                            f"Deployment {deployment['metadata']['name']} has Services of type {sorted(types)}; "
                            "only NodePort and LoadBalancer are reachable from outside the cluster")
        ports = [
            f"{service['metadata']['name']} {port.get('nodePort')}"
            for service in self.services for port in service["spec"].get("ports", []) if port.get("nodePort")
        ]
        if ports:
            NOTES.append(f"Node ports: {', '.join(ports)}.")


class GradingResult(unittest.TextTestResult):
    """Keeps the outcome of every test for the points table."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}

    def record(self, test, outcome, detail=""):
        if isinstance(test, unittest.TestCase):
            name = f"{type(test).__name__}.{test._testMethodName}"
        else:  # an error in setUpModule or setUpClass
            name = str(test)
        self.outcomes[name] = (outcome, detail)

    def addSuccess(self, test):
        super().addSuccess(test)
        self.record(test, "pass")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.record(test, "fail", str(err[1]))

    def addError(self, test, err):
        super().addError(test, err)
        self.record(test, "error", f"{err[0].__name__}: {err[1]}")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.record(test, "skipped", reason)


def outcome_of(result, test_name):
    """(outcome, detail) of a test, falling back to a failed setUpClass or setUpModule."""
    if test_name in result.outcomes:
        return result.outcomes[test_name]
    class_name = test_name.split(".")[0]
    for name, outcome in result.outcomes.items():
        if name.startswith("setUpClass") and name.endswith(f".{class_name})"):
            return outcome
    for name, outcome in result.outcomes.items():
        if name.startswith("setUpModule"):
            return outcome
    return ("not run", "")


def print_report(result, title, rubric, not_tested):
    """Print the points per rubric line; return True if every line passed."""
    print(f"\n{title}\n")
    print("Points  Rubric line")
    earned = total = not_checked = 0
    for line, points, tests in rubric:
        outcomes = [outcome_of(result, name) for name in tests]
        if all(outcome in ("pass", "skipped") for outcome, _ in outcomes) and \
                any(outcome == "skipped" for outcome, _ in outcomes):
            not_checked += points
            print(f" -/{points:<4} {line}")
        else:
            passed = all(outcome == "pass" for outcome, _ in outcomes)
            earned += points if passed else 0
            total += points
            print(f"{points if passed else 0:>2}/{points:<4} {line}")
        for outcome, detail in dict.fromkeys(outcomes):
            if outcome != "pass":
                detail = " ".join(detail.split())
                print(f"          {outcome}: {detail[:160]}")
    print(f"{earned:>2}/{total:<4} tested by this script")
    if not_checked:
        print(f"{not_checked:>5}   not checked in this run (see above)")
    print()
    print("Not tested by this script:")
    for line, points in not_tested:
        print(f"{points:>5}   {line}")
    if NOTES:
        print("\nNotes:")
        for note in dict.fromkeys(NOTES):
            print(f"  {note}")
    return earned == total


def selected(suite, class_names):
    """The tests in suite whose class is one of class_names."""
    tests = unittest.TestSuite()
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            tests.addTests(selected(test, class_names))
        elif type(test).__name__ in class_names:
            tests.addTest(test)
    return tests


def main():
    global SHORTENER_URL, AUTH_URL, RESTART_COMMAND, NAMESPACE
    parser = argparse.ArgumentParser(description="Grade Assignment 2 or 3 over HTTP.")
    parser.add_argument("--assignment", choices=sorted(RUBRICS), default="2", help="default: %(default)s")
    parser.add_argument("--url", default=SHORTENER_URL,
                        help="base URL of the URL shortener (default: %(default)s, or SHORTENER_BASE_URL)")
    parser.add_argument("--auth-url", default=AUTH_URL,
                        help="base URL of the authentication service (default: %(default)s, or AUTH_BASE_URL)")
    parser.add_argument("--restart", default=RESTART_COMMAND, metavar="COMMAND",
                        help="3.1: shell command that restarts both services (or RESTART_COMMAND)")
    parser.add_argument("--namespace", default=NAMESPACE,
                        help="3.2: namespace of the Deployments, for the kubectl checks (or K8S_NAMESPACE)")
    parser.add_argument("-v", "--verbose", action="store_true", help="list every test while it runs")
    args = parser.parse_args()
    SHORTENER_URL, AUTH_URL = args.url.rstrip("/"), args.auth_url.rstrip("/")
    RESTART_COMMAND, NAMESPACE = args.restart, args.namespace

    # test_ownership_isolation imports this module: let it use this copy
    # (with the settings above) instead of loading a second one.
    sys.modules.setdefault("test_microservices", sys.modules[__name__])
    import test_ownership_isolation

    title, rubric, not_tested = RUBRICS[args.assignment]
    loader = unittest.defaultTestLoader
    everything = unittest.TestSuite([
        loader.loadTestsFromModule(sys.modules[__name__]),
        loader.loadTestsFromModule(test_ownership_isolation),
    ])
    suite = selected(everything, {name.split(".")[0] for _, _, tests in rubric for name in tests})
    runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1, resultclass=GradingResult)
    result = runner.run(suite)
    services = f"shortener {SHORTENER_URL}, authentication {AUTH_URL}"
    passed = print_report(result, f"{title} ({services})", rubric, not_tested)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
