"""TA audit for Assignment 2 (authentication service and multi-user URL shortener).

    python audit_a2.py --url http://HOST:5000 --auth-url http://HOST:5001 \\
        [--auth-source DIR --shortener-source DIR] [--report findings.md] [--quick]

This is not the students' grading script. It checks the authentication
service, the JWTs (including forged and unsigned tokens), the separation of
users, and then every Assignment 1 check again with a token. With the source
folders it also looks for JWT libraries and a signing secret shared with the
shortener. FAIL is a violation of the assignment or a bug, WARN a
questionable choice to discuss in the oral exam, INFO an observation. See
README.md.

The audit creates accounts and mappings; it deletes the mappings it made.
"""
import argparse
import ast
import base64
import concurrent.futures
import json
import re
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import audit_a1
from audit_common import (
    Client, Context, ServiceUnreachable, gives_url, holds_private_key, is_5xx, listed, print_report, registry,
    returned_id, run_checks, shorten, wait_for, write_markdown,
)

CHECKS, check = registry()

SPEC = "The specification tables of Assignment 2"
TOKEN_STYLES = [
    ("Authorization", "Bearer {token}"), ("Authorization", "{token}"),
    ("x-access-token", "{token}"), ("Authorization", "JWT {token}"),
]
EXPECTED_CLAIMS = {"sub", "username", "user", "name", "uid", "user_id", "userid", "id",
                   "iat", "exp", "nbf", "iss", "aud", "jti", "typ"}


class User:
    def __init__(self, name, password):
        self.name, self.password, self.token = name, password, None


def token_in(response):
    """The token in the answer to POST /users/login, or None."""
    body = response.json()
    if isinstance(body, dict):
        for key in ("token", "access_token", "accessToken", "jwt", "id_token"):
            if isinstance(body.get(key), str) and body[key]:
                return body[key]
        values = [value for value in body.values() if isinstance(value, str) and value]
        return values[0] if len(values) == 1 else None
    if isinstance(body, str):
        return body
    text = response.text.strip()
    return text if body is None and text.count(".") == 2 and " " not in text else None


def b64decode(text):
    """Decode base64url or standard base64, with or without padding."""
    padded = text + "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(padded)
    except ValueError:
        return base64.b64decode(padded)


def b64encode_like(data, example):
    """Encode data the way the example JWT part was encoded."""
    standard = "+" in example or "/" in example
    encoded = (base64.b64encode(data) if standard else base64.urlsafe_b64encode(data)).decode()
    return encoded if example.endswith("=") else encoded.rstrip("=")


def jwt_parts(token):
    """(header, payload, parts) of a JWT; raises ValueError if it is not one."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError(f"{len(parts)} parts instead of 3")
    header = json.loads(b64decode(parts[0]))
    payload = json.loads(b64decode(parts[1]))
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise ValueError("header and payload must be JSON objects")
    return header, payload, parts


class A2Context(Context):
    def __init__(self, shortener_url, auth_url, token_style=None, auth_source=None,
                 shortener_source=None):
        super().__init__()
        self.shortener_url = shortener_url
        self.auth = Client(auth_url)
        self.public = Client(shortener_url)
        self.token_style = token_style
        self.auth_source = auth_source
        self.shortener_source = shortener_source
        self.users = []

    def new_user(self, label):
        user = User(f"{label}_{self.run}_{uuid.uuid4().hex[:4]}", "Pw-" + uuid.uuid4().hex[:12])
        self.users.append(user)
        return user

    def register(self, user):
        return self.auth.post("/users", {"username": user.name, "password": user.password})

    def login(self, user, password=None):
        response = self.auth.post("/users/login", {"username": user.name, "password": password or user.password})
        token = token_in(response) if response.status == 200 else None
        if password is None and token:
            user.token = token
        return response, token

    def change_password(self, user, old, new):
        body = {"username": user.name, "password": old, "old_password": old, "old-password": old,
                "oldPassword": old, "new_password": new, "new-password": new, "newPassword": new}
        return self.auth.put("/users", body)

    def signed_up(self, label):
        """A registered and logged-in user; skips the check if that does not work."""
        user = self.new_user(label)
        response = self.register(user)
        if response.status not in (200, 201):
            self.skip(f"cannot register a user, see AUTH-01 ({shorten(response.exchange, 200)})")
        response, token = self.login(user)
        if not token:
            self.skip(f"cannot log in, see AUTH-06 ({shorten(response.exchange, 200)})")
        self.detect_token_style(token)
        return user

    def detect_token_style(self, token):
        if self.token_style:
            return
        for name, value in TOKEN_STYLES:
            response = self.public.get("/", headers={name: value.format(token=token)})
            if response.status == 200:
                self.token_style = (name, value)
                return
        self.skip("the shortener refuses a fresh token in every usual header, see JWT-09 (if it expects "
                  "another header, pass --token-header, e.g. 'Authorization: Bearer {token}')")

    def headers(self, token):
        name, value = self.token_style or TOKEN_STYLES[0]
        return {name: value.format(token=token)}

    def client(self, user):
        return self.public.with_headers(self.headers(user.token))

    def create(self, user, url):
        response = self.client(user).post("/", {"value": url})
        short_id = returned_id(response) if response.status == 201 else None
        if short_id is None:
            self.skip(f"POST / with a valid token did not create a mapping ({shorten(response.exchange, 200)})")
        return short_id

    def listed_for(self, user):
        response = self.client(user).get("/")
        return listed(response.json()), response

    def follow(self, short_id, owner):
        """GET /:id, with the owner's token if the shortener wrongly asks for one.

        MULTI-03 reports that mistake; the other checks use this to see
        whether a mapping still exists, so that one bug does not fail them all.
        """
        path = "/" + quote(short_id, safe="")
        response = self.public.get(path)
        if response.status in (401, 403) and owner.token:
            response = self.client(owner).get(path)
        return response


@check("AUTH-01", "Authentication service", "POST /users creates a user (201)",
       why=f"{SPEC} list 201 for POST /users.", ask="Show how a user is created and stored.")
def auth_create(ctx):
    user = ctx.new_user("create")
    response = ctx.register(user)
    if response.status != 201:
        ctx.problem(f"expected 201, got {response.status}", response)


@check("AUTH-02", "Authentication service", "POST /users with an existing username answers 409",
       why=f"{SPEC} list 409 \"duplicate\".", ask="How do you detect duplicate usernames?")
def auth_duplicate(ctx):
    user = ctx.new_user("duplicate")
    ctx.register(user)
    response = ctx.register(user)
    if response.status != 409:
        ctx.problem(f"expected 409, got {response.status}", response)
    other = User(user.name, "another-" + user.password)
    response = ctx.register(other)
    if response.status != 409:
        ctx.problem(f"same name, other password: expected 409, got {response.status}", response)


@check("AUTH-03", "Authentication service", "The 409 answer says \"duplicate\"", severity="WARN",
       why=f"{SPEC} give the value \"duplicate\" with 409 (the course test checks it).",
       ask="What does a client see when the username is taken?")
def auth_duplicate_message(ctx):
    user = ctx.new_user("duplicate-message")
    ctx.register(user)
    response = ctx.register(user)
    if response.status == 409 and "duplicate" not in response.text.lower():
        ctx.problem("the 409 answer does not say \"duplicate\"", response)


@check("AUTH-04", "Authentication service", "POST /users without a username or password is refused (4xx)",
       why="Accounts without a name or password are invalid; the answer must be a client error, "
           "never 201 and never 500.", ask="What does POST /users do with incomplete input?")
def auth_create_invalid(ctx):
    name = f"invalid_{ctx.run}"
    for body in ({}, {"username": name}, {"password": "secret"}, {"username": "", "password": "secret"},
                 {"username": name + "_e", "password": ""}):
        response = ctx.auth.post("/users", body)
        if not 400 <= response.status < 500:
            ctx.problem(f"POST /users {body}: expected 4xx, got {response.status}", response)
    for data in ("{bad json", ""):
        response = ctx.auth.request("POST", "/users", data=data, headers={"Content-Type": "application/json"})
        if not 400 <= response.status < 500:
            ctx.problem(f"POST /users with body {data!r}: expected 4xx, got {response.status}", response)


@check("AUTH-05", "Authentication service", "Values that are not strings do not crash POST /users",
       why="A number, list, object or null as username or password must give a 4xx, not a 500.",
       ask="What does POST /users do when the username is a number?")
def auth_create_types(ctx):
    for body in ({"username": 12345, "password": "secret"}, {"username": ["a"], "password": "secret"},
                 {"username": f"types_{ctx.run}", "password": None}, {"username": {"a": 1}, "password": "x"}):
        response = ctx.auth.post("/users", body)
        if is_5xx(response):
            ctx.problem(f"POST /users {body}: got {response.status}", response)


@check("AUTH-06", "Authentication service", "POST /users/login with the right password answers 200 and a token",
       why=f"{SPEC} list 200 with the JWT.", ask="Show the login and how the token is made.")
def auth_login(ctx):
    user = ctx.new_user("login")
    ctx.register(user)
    response, token = ctx.login(user)
    if response.status != 200:
        ctx.problem(f"expected 200, got {response.status}", response)
    elif not token:
        ctx.problem("200, but no token found in the answer", response)


@check("AUTH-07", "Authentication service", "Login with a wrong password answers 403",
       why=f"{SPEC} list 403 \"forbidden\" for a failed login.", ask="What happens with a wrong password?")
def auth_login_wrong(ctx):
    user = ctx.new_user("wrong")
    ctx.register(user)
    for password in ("wrong-" + user.password, user.password.upper(), user.password + " "):
        response, _ = ctx.login(user, password)
        if response.status != 403:
            ctx.problem(f"password {password!r}: expected 403, got {response.status}", response)


@check("AUTH-08", "Authentication service", "Login with an unknown username answers 403",
       why=f"{SPEC}: \"Check if username and password exist in the table and generate a JWT or else return 403\".",
       ask="What does login answer for a user that does not exist?")
def auth_login_unknown(ctx):
    user = User(f"nobody_{ctx.run}", "whatever")
    response, _ = ctx.login(user, "whatever")
    if response.status != 403:
        ctx.problem(f"expected 403, got {response.status}", response)


@check("AUTH-09", "Authentication service", "403 answers say \"forbidden\"", severity="WARN",
       why=f"{SPEC} give the value \"forbidden\" with 403 (the course test checks it).",
       ask="What does a client see when the login fails?")
def auth_forbidden_message(ctx):
    user = ctx.new_user("forbidden-message")
    ctx.register(user)
    response, _ = ctx.login(user, "wrong-" + user.password)
    if response.status == 403 and "forbidden" not in response.text.lower():
        ctx.problem("the 403 answer to a failed login does not say \"forbidden\"", response)
    response = ctx.change_password(user, "wrong-" + user.password, "Pw-new")
    if response.status == 403 and "forbidden" not in response.text.lower():
        ctx.problem("the 403 answer to a failed password change does not say \"forbidden\"", response)


@check("AUTH-10", "Authentication service", "Login with missing fields or broken JSON is refused (4xx)",
       why="A login without a password must not succeed, and broken input must not crash the service.",
       ask="What does login do with incomplete input?")
def auth_login_invalid(ctx):
    user = ctx.new_user("login-invalid")
    ctx.register(user)
    for body in ({}, {"username": user.name}, {"username": user.name, "password": ""},
                 {"username": user.name, "password": None}, {"password": user.password}):
        response = ctx.auth.post("/users/login", body)
        if not 400 <= response.status < 500:
            ctx.problem(f"POST /users/login {body}: expected 4xx, got {response.status}", response)
    for data in ("{bad json", ""):
        response = ctx.auth.request("POST", "/users/login", data=data, headers={"Content-Type": "application/json"})
        if not 400 <= response.status < 500:
            ctx.problem(f"POST /users/login with body {data!r}: expected 4xx, got {response.status}", response)


@check("AUTH-11", "Authentication service", "PUT /users with the right old password changes the password",
       why=f"{SPEC} list 200 for PUT /users with the correct old password.",
       ask="Show the password change. Which fields does PUT /users expect?")
def auth_change(ctx):
    user = ctx.new_user("change")
    ctx.register(user)
    new = "Pw-new-" + uuid.uuid4().hex[:8]
    response = ctx.change_password(user, user.password, new)
    if response.status != 200:
        ctx.problem(f"expected 200, got {response.status}", response)
        return
    if ctx.login(user, new)[0].status != 200:
        ctx.problem("the new password does not log in")
    if ctx.login(user, user.password)[0].status != 403:
        ctx.problem("the old password still logs in")
    user.password = new


@check("AUTH-12", "Authentication service", "PUT /users with a wrong old password answers 403 and changes nothing",
       why=f"{SPEC}: \"Update the user's password if the user presents the correct old password, or else return 403\".",
       ask="What does PUT /users do with a wrong old password?")
def auth_change_wrong(ctx):
    user = ctx.new_user("change-wrong")
    ctx.register(user)
    response = ctx.change_password(user, "wrong-" + user.password, "Pw-hijack")
    if response.status != 403:
        ctx.problem(f"expected 403, got {response.status}", response)
    if ctx.login(user)[0].status != 200:
        ctx.problem("after the refused change, the old password no longer logs in")
    if ctx.login(user, "Pw-hijack")[0].status == 200:
        ctx.problem("the refused change took effect")


@check("AUTH-13", "Authentication service", "PUT /users for an unknown user answers 403", severity="WARN",
       why=f"{SPEC} list only 200 and 403 for PUT /users. 404 is an allowed extra code, but it "
           "tells anyone which usernames exist.", ask="Why this status for a user that does not exist?")
def auth_change_unknown(ctx):
    user = User(f"nobody_{ctx.run}", "whatever")
    response = ctx.change_password(user, "whatever", "Pw-new")
    if response.status != 403:
        ctx.problem(f"expected 403, got {response.status}", response)


@check("AUTH-14", "Authentication service", "Changing one user's password leaves other users alone",
       why="A password change must touch only that account.", ask="How does PUT /users find the account?")
def auth_change_isolated(ctx):
    alice, bob = ctx.new_user("alice"), ctx.new_user("bob")
    ctx.register(alice)
    ctx.register(bob)
    ctx.change_password(alice, alice.password, "Pw-alice-new")
    if ctx.login(bob)[0].status != 200:
        ctx.problem("after Alice changed her password, Bob cannot log in")
    if ctx.login(bob, "Pw-alice-new")[0].status == 200:
        ctx.problem("Alice's new password logs Bob in")


@check("AUTH-15", "Authentication service", "PUT /users with missing fields or broken JSON is refused (4xx)",
       why="Incomplete input must not change a password or crash the service.",
       ask="What does PUT /users do with incomplete input?")
def auth_change_invalid(ctx):
    user = ctx.new_user("change-invalid")
    ctx.register(user)
    for body in ({}, {"username": user.name}, {"username": user.name, "old_password": user.password},
                 {"username": user.name, "old_password": user.password, "new_password": ""}):
        response = ctx.auth.put("/users", body)
        if not 400 <= response.status < 500:
            ctx.problem(f"PUT /users {body}: expected 4xx, got {response.status}", response)
    response = ctx.auth.request("PUT", "/users", data="{bad json", headers={"Content-Type": "application/json"})
    if not 400 <= response.status < 500:
        ctx.problem(f"PUT /users with broken JSON: expected 4xx, got {response.status}", response)
    if ctx.login(user)[0].status != 200:
        ctx.problem("the password changed or the account broke")


@check("AUTH-16", "Authentication service", "No answer contains a password",
       why="Passwords (or their hashes) must never be sent back to a client.",
       ask="What do your answers to /users and /users/login contain?")
def auth_no_password_echo(ctx):
    passwords = [user.password for user in ctx.users if len(user.password) >= 8]
    for text in ctx.auth.texts:
        for password in passwords:
            if password in text:
                ctx.problem(f"an answer contains the password {password!r}: {shorten(text, 160)}")
                return


@check("AUTH-17", "Authentication service", "Observations on the authentication service", severity="INFO")
def auth_observations(ctx):
    for label, body_keys in (("old_password/new_password", ("old_password", "new_password")),
                             ("password/new_password", ("password", "new_password")),
                             ("old-password/new-password", ("old-password", "new-password"))):
        user = ctx.new_user("fields")
        ctx.register(user)
        body = {"username": user.name, body_keys[0]: user.password, body_keys[1]: "Pw-" + uuid.uuid4().hex[:8]}
        response = ctx.auth.put("/users", body)
        ctx.observe(f"PUT /users with {label}: {response.status}")
    user = ctx.new_user("Case")
    ctx.register(user)
    response = ctx.auth.post("/users", {"username": user.name.lower(), "password": user.password})
    ctx.observe("usernames differing only in case are " + ("different accounts" if response.status == 201 else
                                                           f"refused ({response.status})"))


@check("JWT-01", "JWT", "The login token is a JWT: three base64url parts with a JSON header and payload",
       why="Assignment 2 asks for JSON Web Tokens built by hand: "
           "base64url(JSON header).base64url(JSON payload).signature.",
       ask="Build a token on the whiteboard: what are its three parts?")
def jwt_structure(ctx):
    user = ctx.signed_up("jwt")
    try:
        jwt_parts(user.token)
    except (ValueError, TypeError) as error:
        ctx.problem(f"the token is not a JWT ({error}): {shorten(user.token, 120)}")


@check("JWT-02", "JWT", "The token is signed",
       why="An unsigned token (alg none, empty signature) can be forged by anyone.",
       ask="How is the token signed, and with which key?")
def jwt_signed(ctx):
    user = ctx.signed_up("jwt-signed")
    try:
        header, _, parts = jwt_parts(user.token)
    except (ValueError, TypeError):
        ctx.skip("the token is not a JWT, see JWT-01")
    if str(header.get("alg", "none")).lower() == "none" or not parts[2]:
        ctx.problem(f"header {header}, signature {parts[2]!r}")


@check("JWT-03", "JWT", "The token holds no password or password hash",
       why="A JWT is only encoded, not encrypted: anyone who has it can read the payload.",
       ask="What does your token contain, and why?")
def jwt_no_secret(ctx):
    user = ctx.signed_up("jwt-secret")
    try:
        header, payload, _ = jwt_parts(user.token)
    except (ValueError, TypeError):
        ctx.skip("the token is not a JWT, see JWT-01")
    text = json.dumps([header, payload])
    if user.password in text:
        ctx.problem(f"the token contains the password: {payload}")
    suspicious = [claim for claim in payload if re.search("pass|pwd|hash|secret|salt", claim, re.IGNORECASE)]
    if suspicious:
        ctx.problem(f"the token has claims {suspicious}: {payload}")


@check("JWT-04", "JWT", "The payload holds only what is needed", severity="WARN",
       why="Assignment 2: \"Make sure your JWTs do not contain unnecessary information\".",
       ask="Why does the token contain these claims?")
def jwt_minimal(ctx):
    user = ctx.signed_up("jwt-minimal")
    try:
        _, payload, parts = jwt_parts(user.token)
    except (ValueError, TypeError):
        ctx.skip("the token is not a JWT, see JWT-01")
    extra = sorted(set(payload) - EXPECTED_CLAIMS)
    if extra:
        ctx.problem(f"claims beyond the user and validity: {extra} (payload {payload})")
    if len(parts[1]) > 400:
        ctx.problem(f"the payload is {len(parts[1])} characters long")


@check("JWT-05", "JWT", "The token expires", severity="WARN",
       why="A token without exp stays valid forever, also after a password change.",
       ask="How long is a token valid? How would you revoke one?")
def jwt_expires(ctx):
    user = ctx.signed_up("jwt-exp")
    try:
        _, payload, _ = jwt_parts(user.token)
    except (ValueError, TypeError):
        ctx.skip("the token is not a JWT, see JWT-01")
    if "exp" not in payload:
        ctx.problem(f"no exp claim: {payload}")
    elif not isinstance(payload["exp"], (int, float)):
        ctx.problem(f"exp is not a number: {payload['exp']!r}")


@check("JWT-06", "JWT", "The parts are base64url without padding", severity="WARN",
       why="RFC 7519 encodes JWT parts in base64url without '='. Standard base64 ('+', '/', '=') "
           "is not a valid JWT for other software.", ask="Which base64 variant do you use, and why?")
def jwt_base64url(ctx):
    user = ctx.signed_up("jwt-base64")
    for index, part in enumerate(user.token.split(".")):
        if re.search(r"[+/=]", part):
            ctx.problem(f"part {index + 1} contains '+', '/' or '=': {shorten(part, 60)}")


@check("JWT-07", "JWT", "The token is not signed with a shared secret (HS*)", severity="WARN",
       why="Assignment 2: keep the secret in the authentication service and do not share it with the shortener. "
           "With HMAC, the shortener can only check a token itself if it has the secret.",
       ask="How does your shortener check an HS256 token without the secret?")
def jwt_hmac(ctx):
    user = ctx.signed_up("jwt-alg")
    try:
        header, _, _ = jwt_parts(user.token)
    except (ValueError, TypeError):
        ctx.skip("the token is not a JWT, see JWT-01")
    if str(header.get("alg", "")).upper().startswith("HS"):
        ctx.problem(f"the token uses {header.get('alg')}")


@check("JWT-08", "JWT", "Observations on the token", severity="INFO")
def jwt_observations(ctx):
    user = ctx.signed_up("jwt-info")
    try:
        header, payload, _ = jwt_parts(user.token)
    except (ValueError, TypeError):
        ctx.skip("the token is not a JWT, see JWT-01")
    ctx.observe(f"header {json.dumps(header)}; payload {json.dumps(payload)}")
    if isinstance(payload.get("exp"), (int, float)) and isinstance(payload.get("iat"), (int, float)):
        ctx.observe(f"valid for {(payload['exp'] - payload['iat']) / 60:.0f} minutes")
    ctx.observe(f"the shortener takes the token as \"{ctx.token_style[0]}: {ctx.token_style[1]}\"")


@check("JWT-09", "JWT", "The shortener accepts a valid token",
       why="Assignment 2: the shortener verifies the JWTs that the authentication service issues. If it refuses "
           "valid tokens, no user can manage mappings.",
       ask="How does the shortener verify a token, and with which key?")
def jwt_valid_accepted(ctx):
    user = ctx.new_user("jwt-valid")
    response = ctx.register(user)
    if response.status not in (200, 201):
        ctx.skip(f"cannot register a user, see AUTH-01 ({shorten(response.exchange, 200)})")
    response, token = ctx.login(user)
    if not token:
        ctx.skip(f"cannot log in, see AUTH-06 ({shorten(response.exchange, 200)})")
    styles = [ctx.token_style] if ctx.token_style else TOKEN_STYLES
    answers = [ctx.public.get("/", headers={name: value.format(token=token)}) for name, value in styles]
    if not any(answer.status == 200 for answer in answers):
        tried = ", ".join(f"{name}: {value.format(token='TOKEN')} -> {answer.status}"
                          for (name, value), answer in zip(styles, answers))
        ctx.problem(f"GET / with a fresh token was refused ({tried})", answers[0])


def forged_requests(ctx, user, token):
    """Status of GET / and of DELETE on the user's mapping, sent with token."""
    short_id = ctx.create(user, ctx.url("forged-" + uuid.uuid4().hex[:6]))
    client = ctx.public.with_headers(ctx.headers(token))
    listing = client.get("/")
    deletion = client.delete("/" + quote(short_id, safe=""))
    survived = ctx.follow(short_id, user).status == 301
    return listing, deletion, survived


@check("JWT-10", "JWT", "A token whose payload was changed is rejected",
       why="The shortener must check the signature; otherwise anyone can extend or alter a token.",
       ask="Where and how does the shortener check the signature?")
def jwt_tampered(ctx):
    user = ctx.signed_up("jwt-tampered")
    try:
        _, payload, parts = jwt_parts(user.token)
    except (ValueError, TypeError):
        ctx.skip("the token is not a JWT, see JWT-01")
    payload = dict(payload)
    if isinstance(payload.get("exp"), (int, float)):
        payload["exp"] = int(payload["exp"]) + 365 * 24 * 3600
    else:
        payload["admin"] = True
    forged = ".".join([parts[0], b64encode_like(json.dumps(payload).encode(), parts[1]), parts[2]])
    listing, deletion, survived = forged_requests(ctx, user, forged)
    if listing.ok:
        ctx.problem("GET / accepted the changed token", listing)
    if deletion.ok or not survived:
        ctx.problem("DELETE /:id with the changed token removed the mapping", deletion)


@check("JWT-11", "JWT", "An unsigned token (alg none) is rejected",
       why="Accepting alg none lets anyone write their own token.",
       ask="Does your verification look at the alg in the header?")
def jwt_alg_none(ctx):
    user = ctx.signed_up("jwt-none")
    try:
        _, _, parts = jwt_parts(user.token)
    except (ValueError, TypeError):
        ctx.skip("the token is not a JWT, see JWT-01")
    header = b64encode_like(b'{"alg":"none","typ":"JWT"}', parts[0])
    for forged in (f"{header}.{parts[1]}.", f"{header}.{parts[1]}"):
        listing, deletion, survived = forged_requests(ctx, user, forged)
        if listing.ok:
            ctx.problem(f"GET / accepted {shorten(forged, 50)!r}", listing)
        if deletion.ok or not survived:
            ctx.problem("DELETE /:id with an unsigned token removed the mapping", deletion)


@check("JWT-12", "JWT", "A token with a missing or damaged signature is rejected",
       why="The signature is what makes the token trustworthy.", ask="Show the signature check.")
def jwt_damaged_signature(ctx):
    user = ctx.signed_up("jwt-damaged")
    parts = user.token.split(".")
    if len(parts) != 3:
        ctx.skip("the token is not a JWT, see JWT-01")
    signature = parts[2]
    flipped = ("A" if signature[:1] != "A" else "B") + signature[1:]
    for forged in (f"{parts[0]}.{parts[1]}.", f"{parts[0]}.{parts[1]}.{flipped}",
                   f"{parts[0]}.{parts[1]}.{signature[:-4]}"):
        listing = ctx.public.get("/", headers=ctx.headers(forged))
        if listing.ok:
            ctx.problem(f"GET / accepted a token with signature {shorten(forged.split('.')[2], 30)!r}", listing)


@check("JWT-13", "JWT", "A token cannot be changed to act as another user",
       why="If the shortener reads the user from an unchecked token, Alice can manage Bob's mappings.",
       ask="How does the shortener know which user sends a request?")
def jwt_impersonation(ctx):
    alice, bob = ctx.signed_up("alice"), ctx.signed_up("bob")
    bob_id = ctx.create(bob, ctx.url("bob-private"))
    try:
        _, payload, parts = jwt_parts(alice.token)
        _, bob_payload, _ = jwt_parts(bob.token)
    except (ValueError, TypeError):
        ctx.skip("the token is not a JWT, see JWT-01")
    # Alice's token with Bob's identity claims, and Alice's signature.
    changed = dict(payload)
    changed.update({key: value for key, value in bob_payload.items() if key not in ("iat", "exp", "nbf", "jti")})
    if changed == payload:
        ctx.skip("both users' tokens carry the same claims; impersonation not constructed")
    forged = ".".join([parts[0], b64encode_like(json.dumps(changed).encode(), parts[1]), parts[2]])
    client = ctx.public.with_headers(ctx.headers(forged))
    response = client.get("/")
    if response.ok and bob_id in listed(response.json()):
        ctx.problem("a token changed to Bob's name lists Bob's mappings", response)
    response = client.delete("/" + quote(bob_id, safe=""))
    if response.ok:
        ctx.problem("a token changed to Bob's name deleted Bob's mapping", response)


@check("JWT-14", "JWT", "Garbage tokens get 403, not a crash",
       why="Any string can arrive as a token; the answer must be 403 \"forbidden\".",
       ask="What happens when the token cannot be decoded?")
def jwt_garbage(ctx):
    ctx.signed_up("jwt-garbage")
    for token in ("", "x", "a.b.c", "a.b", "....", "eyJhbGciOiJIUzI1NiJ9.e30", "%" * 10, "x" * 5000,
                  "e30.e30.e30", "bnVsbA.bnVsbA.x"):
        response = ctx.public.get("/", headers=ctx.headers(token))
        if response.status != 403:
            ctx.problem(f"token {shorten(token, 30)!r}: expected 403, got {response.status}", response)


@check("JWT-15", "JWT", "A token after a password change", severity="INFO")
def jwt_after_password_change(ctx):
    user = ctx.signed_up("jwt-revoke")
    old_token = user.token
    ctx.change_password(user, user.password, "Pw-" + uuid.uuid4().hex[:10])
    response = ctx.public.get("/", headers=ctx.headers(old_token))
    ctx.observe("a token issued before a password change is " +
                ("still accepted (stateless tokens: ask about revocation)" if response.ok else
                 f"refused ({response.status})"))


ENDPOINTS = (("PUT", "/{id}", {"url": None}), ("DELETE", "/{id}", None), ("GET", "/", None),
             ("POST", "/", {"value": None}), ("DELETE", "/", None))


def every_endpoint(ctx, user, headers):
    """Answers of the five protected endpoints with the given headers."""
    short_id = ctx.create(user, ctx.url("protected-" + uuid.uuid4().hex[:6]))
    answers = []
    for method, path, body in ENDPOINTS:
        if body is not None:
            body = {key: ctx.url("protected-new") for key in body}
        answers.append(ctx.public.request(method, path.format(id=quote(short_id, safe="")),
                                          json_body=body, headers=headers))
    return short_id, answers


@check("MULTI-01", "Multi-user", "Without a token, every management endpoint answers 403",
       why=f"{SPEC} add 403 \"forbidden\" to PUT /:id, DELETE /:id, GET /, POST / and DELETE /.",
       ask="When does your shortener ask for a token?")
def multi_no_token(ctx):
    user = ctx.signed_up("no-token")
    short_id, answers = every_endpoint(ctx, user, {})
    for (method, path, _), response in zip(ENDPOINTS, answers):
        if response.status != 403:
            ctx.problem(f"{method} {path}: expected 403, got {response.status}", response)
    if ctx.follow(short_id, user).status != 301:
        ctx.problem("requests without a token changed or removed the mapping")


@check("MULTI-02", "Multi-user", "With an invalid token, every management endpoint answers 403",
       why=f"{SPEC} add 403 \"forbidden\" for these endpoints.", ask="What happens with an invalid token?")
def multi_invalid_token(ctx):
    user = ctx.signed_up("invalid-token")
    short_id, answers = every_endpoint(ctx, user, ctx.headers("invalid"))
    for (method, path, _), response in zip(ENDPOINTS, answers):
        if response.status != 403:
            ctx.problem(f"{method} {path}: expected 403, got {response.status}", response)
    if ctx.follow(short_id, user).status != 301:
        ctx.problem("requests with an invalid token changed or removed the mapping")


@check("MULTI-03", "Multi-user", "GET /:id works without a token",
       why=f"{SPEC} have no 403 for GET /:id: short links are public.",
       ask="Who may follow a short link?")
def multi_public_get(ctx):
    user = ctx.signed_up("public")
    url = ctx.url("public")
    short_id = ctx.create(user, url)
    response = ctx.public.get("/" + quote(short_id, safe=""))
    if not gives_url(response, url):
        ctx.problem(f"GET /:id without a token: expected 301 to the URL, got {response.status}", response)


@check("MULTI-04", "Multi-user", "GET / lists only the caller's mappings",
       why="Assignment 2: associate mappings with users so that only they can manage them.",
       ask="How does GET / decide which keys to return?")
def multi_list_own(ctx):
    alice, bob = ctx.signed_up("alice"), ctx.signed_up("bob")
    alice_id, bob_id = ctx.create(alice, ctx.url("alice-list")), ctx.create(bob, ctx.url("bob-list"))
    alice_keys, response = ctx.listed_for(alice)
    if bob_id in alice_keys or ctx.url("bob-list") in alice_keys:
        ctx.problem("GET / as Alice lists Bob's mapping", response)
    if alice_id not in alice_keys and ctx.url("alice-list") not in alice_keys:
        ctx.problem("GET / as Alice does not list her own mapping", response)


@check("MULTI-05", "Multi-user", "Another user cannot change a mapping",
       why="Only the owner may manage a mapping; requiring a login is not enough.",
       ask="Where does PUT /:id check the owner?")
def multi_put_other(ctx):
    alice, bob = ctx.signed_up("alice"), ctx.signed_up("bob")
    url = ctx.url("alice-put")
    short_id = ctx.create(alice, url)
    response = ctx.client(bob).put("/" + quote(short_id, safe=""), {"url": ctx.url("bob-took-over")})
    if response.ok:
        ctx.problem("Bob changed Alice's mapping", response)
    if not gives_url(ctx.follow(short_id, alice), url):
        ctx.problem("Alice's mapping no longer leads to her URL")


@check("MULTI-06", "Multi-user", "Another user cannot delete a mapping",
       why="Only the owner may delete a mapping.", ask="Where does DELETE /:id check the owner?")
def multi_delete_other(ctx):
    alice, bob = ctx.signed_up("alice"), ctx.signed_up("bob")
    url = ctx.url("alice-delete")
    short_id = ctx.create(alice, url)
    response = ctx.client(bob).delete("/" + quote(short_id, safe=""))
    if response.ok:
        ctx.problem("Bob deleted Alice's mapping", response)
    if not gives_url(ctx.follow(short_id, alice), url):
        ctx.problem("Alice's mapping is gone")


@check("MULTI-07", "Multi-user", "Another user's attempt is answered with 403", severity="WARN",
       why=f"{SPEC} use 403 \"forbidden\" for this case. 404 hides that the mapping exists, which is "
           "defensible but not the specified code.", ask="Why this status code?")
def multi_other_status(ctx):
    alice, bob = ctx.signed_up("alice"), ctx.signed_up("bob")
    short_id = ctx.create(alice, ctx.url("alice-status"))
    for method, body in (("PUT", {"url": ctx.url("bob-status")}), ("DELETE", None)):
        response = ctx.client(bob).request(method, "/" + quote(short_id, safe=""), json_body=body)
        if response.status != 403 and not response.ok:
            ctx.problem(f"{method} on another user's mapping: expected 403, got {response.status}", response)


@check("MULTI-08", "Multi-user", "DELETE / removes only the caller's mappings",
       why="Deleting all mappings of all users is a multi-user bug.", ask="What does DELETE / delete?")
def multi_delete_all_own(ctx):
    alice, bob = ctx.signed_up("alice"), ctx.signed_up("bob")
    alice_id = ctx.create(alice, ctx.url("alice-all"))
    bob_url = ctx.url("bob-all")
    bob_id = ctx.create(bob, bob_url)
    response = ctx.client(alice).delete("/")
    if response.status != 404:
        ctx.problem(f"DELETE /: expected 404, got {response.status}", response)
    if ctx.follow(alice_id, alice).status != 404:
        ctx.problem("Alice's own mapping survived her DELETE /")
    if not gives_url(ctx.follow(bob_id, bob), bob_url):
        ctx.problem("Alice's DELETE / removed Bob's mapping")


@check("MULTI-09", "Multi-user", "Two users who shorten the same URL keep separate mappings",
       why="An identifier derived from the URL alone can hand an existing mapping (and its ownership) "
           "to a second user.", ask="What happens when Bob shortens a URL that Alice already shortened?")
def multi_same_url(ctx):
    alice, bob = ctx.signed_up("alice"), ctx.signed_up("bob")
    url = ctx.url("same-url")
    alice_id = ctx.create(alice, url)
    bob_id = ctx.create(bob, url)
    if alice_id == bob_id:
        ctx.problem(f"both got the id {alice_id!r}: one of them cannot manage it")
    alice_keys, response = ctx.listed_for(alice)
    if alice_id not in alice_keys:
        ctx.problem("after Bob shortened the same URL, Alice no longer lists her mapping", response)
    response = ctx.client(bob).delete("/" + quote(alice_id, safe=""))
    if response.ok and alice_id != bob_id:
        ctx.problem("Bob deleted Alice's mapping of the same URL", response)
    response = ctx.client(alice).put("/" + quote(alice_id, safe=""), {"url": ctx.url("same-url-new")})
    if response.status != 200:
        ctx.problem(f"Alice can no longer update her mapping ({response.status})", response)


@check("MULTI-10", "Multi-user", "Concurrent requests of two users keep identifiers and owners apart",
       why="Concurrent POSTs must not share identifiers or mix up owners.",
       ask="What happens when two users create mappings at the same moment?")
def multi_concurrent(ctx):
    alice, bob = ctx.signed_up("alice"), ctx.signed_up("bob")
    jobs = [(user, ctx.url(f"{user.name}-parallel-{number}")) for number in range(20) for user in (alice, bob)]

    def create(job):
        user, url = job
        response = ctx.client(user).post("/", {"value": url})
        return user, url, returned_id(response) if response.status == 201 else None

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(create, jobs))
    ids = [short_id for _, _, short_id in results if short_id]
    if len(ids) != len(jobs):
        ctx.problem(f"{len(jobs) - len(ids)} of {len(jobs)} concurrent POSTs failed")
    if len(set(ids)) != len(ids):
        ctx.problem(f"{len(ids) - len(set(ids))} identifiers were handed out twice")
    for user in (alice, bob):
        keys, _ = ctx.listed_for(user)
        foreign = [short_id for owner, _, short_id in results if short_id and owner is not user and short_id in keys]
        if foreign:
            ctx.problem(f"{user.name.split('_')[0]} lists {len(foreign)} mappings of the other user")


@check("SVC-01", "Microservices", "The shortener does not serve the authentication endpoints", severity="WARN",
       why="Rubric: two separate services. A shortener that answers POST /users looks like one program.",
       ask="Are your services separate programs? How do they communicate?")
def svc_shortener_has_no_auth(ctx):
    response = ctx.public.post("/users", {"username": f"svc_{ctx.run}", "password": "Pw-svc-check"})
    if response.status in (200, 201, 409):
        ctx.problem(f"POST /users on the shortener answered {response.status}", response)
    response = ctx.public.post("/users/login", {"username": f"svc_{ctx.run}", "password": "Pw-svc-check"})
    if response.status == 200:
        ctx.problem("POST /users/login on the shortener answered 200", response)


@check("SVC-02", "Microservices", "The authentication service does not serve the shortener", severity="WARN",
       why="Rubric: two separate services.", ask="Are your services separate programs?")
def svc_auth_has_no_shortener(ctx):
    user = ctx.signed_up("svc")
    response = ctx.auth.post("/", {"value": ctx.url("svc")}, headers=ctx.headers(user.token))
    if response.status == 201:
        ctx.problem("POST / on the authentication service created a mapping", response)


JWT_MODULES = r"jwt|jose|python_jose|authlib|jwcrypto|flask_jwt_extended|flask_jwt|jwt_simple|python_jwt"
JWT_PACKAGES = r"pyjwt|python-jose|jose|authlib|jwcrypto|flask-jwt-extended|flask-jwt|python-jwt|jwt"
SKIPPED_FOLDERS = {".git", ".venv", "venv", "env", "__pycache__", "node_modules", "site-packages"}


def source_files(folder, patterns):
    for pattern in patterns:
        for path in Path(folder).rglob(pattern):
            if not SKIPPED_FOLDERS.intersection(path.parts) and path.is_file():
                yield path


def read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def source_folders(ctx):
    folders = [folder for folder in (ctx.auth_source, ctx.shortener_source) if folder]
    if not folders:
        ctx.skip("no source given; pass --auth-source and --shortener-source")
    return folders


@check("SRC-01", "Source code", "No library builds or checks the JWT",
       why="Assignment 2: \"Do not use libraries that implement JWTs for you ... Using a library that does "
           "everything will cost you a few points.\"", ask="Which libraries do you use for the token, and for what?")
def src_jwt_library(ctx):
    for folder in source_folders(ctx):
        for path in source_files(folder, ("*.py",)):
            for number, line in enumerate(read(path).splitlines(), 1):
                if re.match(rf"\s*(import|from)\s+({JWT_MODULES})\b", line):
                    ctx.problem(f"{path}:{number}: {line.strip()}")


@check("SRC-02", "Source code", "No JWT library is listed as a dependency", severity="WARN",
       why="A JWT library in the requirements suggests it is used, even if no import was found.",
       ask="Why is this package a dependency?")
def src_jwt_requirement(ctx):
    for folder in source_folders(ctx):
        for path in source_files(folder, ("requirements*.txt", "pyproject.toml", "Pipfile")):
            for number, line in enumerate(read(path).splitlines(), 1):
                if re.match(rf"\s*\"?({JWT_PACKAGES})\b", line, re.IGNORECASE):
                    ctx.problem(f"{path}:{number}: {line.strip()}")


@check("SRC-03", "Source code", "The shortener holds no private key",
       why="Assignment 2: keep the secret in the authentication service; do not share it with the shortener.",
       ask="Which key material does the shortener have, and why?")
def src_shortener_private_key(ctx):
    if not ctx.shortener_source:
        ctx.skip("no shortener source given; pass --shortener-source")
    for path in source_files(ctx.shortener_source, ("*",)):
        if path.stat().st_size < 200000 and holds_private_key(read(path)):
            ctx.problem(f"{path} contains a private key")


# Names of locations (PRIVATE_KEY_FILE, KEYS_DIR) and of public keys, which both
# services may share.
NOT_SECRET = re.compile(r"public|(file|path|dir|folder|url|name)$", re.IGNORECASE)


def secret_literals(folder):
    """String constants assigned to names that look like secrets or keys."""
    found = {}
    for path in source_files(folder, ("*.py",)):
        try:
            tree = ast.parse(read(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str) and len(node.value.value) >= 6:
                for target in node.targets:
                    if isinstance(target, ast.Name) and re.search("secret|key|signing", target.id, re.IGNORECASE) \
                            and not NOT_SECRET.search(target.id):
                        found.setdefault(node.value.value, f"{path}:{node.lineno} {target.id}")
    return found


@check("SRC-04", "Source code", "The two services do not contain the same secret", severity="WARN",
       why="The same secret constant in both services means the shortener can sign tokens too.",
       ask="Where is the signing secret, and who knows it?")
def src_shared_secret(ctx):
    if not (ctx.auth_source and ctx.shortener_source):
        ctx.skip("pass both --auth-source and --shortener-source")
    auth = secret_literals(ctx.auth_source)
    shortener = secret_literals(ctx.shortener_source)
    for value in set(auth) & set(shortener):
        if auth[value].split(" ")[0] != shortener[value].split(" ")[0]:
            ctx.problem(f"{auth[value]} and {shortener[value]} hold the same value")


@check("SRC-05", "Source code", "The services are separate programs, not Blueprints of one app", severity="WARN",
       why="Rubric: points for re-implementing the services, \"and not used stuff like Blueprint\".",
       ask="How are your services started? Are they separate processes?")
def src_blueprint(ctx):
    for folder in source_folders(ctx):
        for path in source_files(folder, ("*.py",)):
            if re.search(r"\bBlueprint\s*\(", read(path)):
                ctx.problem(f"{path} defines a Flask Blueprint")


@check("SRC-06", "Source code", "Observations on the source", severity="INFO")
def src_observations(ctx):
    for folder in source_folders(ctx):
        text = "\n".join(read(path) for path in source_files(folder, ("*.py",)))
        for pattern, label in ((r"pbkdf2_hmac|bcrypt|argon2|scrypt", "a slow, salted password hash"),
                               (r"sha256\(|md5\(|sha1\(", "a fast hash (sha256/md5/sha1)"),
                               (r"debug\s*=\s*True", "Flask debug mode"),
                               (r"requests\.(get|post)\(", "HTTP calls to another service"),
                               (r"RS256|PKCS1v15|rsa\.", "RSA signatures"),
                               (r"hmac\.new|HS256", "HMAC signatures")):
            if re.search(pattern, text):
                ctx.observe(f"{folder}: uses {label}")


def main():
    parser = argparse.ArgumentParser(description="TA audit for Assignment 2 (authentication and multi-user shortener).")
    parser.add_argument("--url", default="http://127.0.0.1:5000", help="URL shortener (default: %(default)s)")
    parser.add_argument("--auth-url", default="http://127.0.0.1:5001",
                        help="authentication service (default: %(default)s)")
    parser.add_argument("--token-header", metavar="'NAME: FORMAT'",
                        help="how to send the token, e.g. 'Authorization: Bearer {token}' (default: detected)")
    parser.add_argument("--auth-source", metavar="DIR", help="the students' authentication service source")
    parser.add_argument("--shortener-source", metavar="DIR", help="the students' URL shortener source")
    parser.add_argument("--report", metavar="FILE.md", help="also write the findings to a Markdown file")
    parser.add_argument("--quick", action="store_true", help="fewer URLs, no collision search")
    parser.add_argument("--only", nargs="*", help="run only checks whose id starts with these, e.g. A2-JWT")
    parser.add_argument("-v", "--verbose", action="store_true", help="show each check while it runs")
    args = parser.parse_args()

    style = None
    if args.token_header:
        name, _, value = args.token_header.partition(":")
        style = (name.strip(), value.strip())
    context = A2Context(args.url, args.auth_url, style, args.auth_source, args.shortener_source)
    try:
        wait_for(context.public, context.auth)
    except ServiceUnreachable as error:
        print(f"Cannot reach a service: {error}", file=sys.stderr)
        sys.exit(2)
    started = time.monotonic()
    results = run_checks(CHECKS, context, "A2", args.only, args.verbose)

    # Every Assignment 1 check again, with a token.
    user = context.new_user("a1")
    if context.register(user).status in (200, 201) and context.login(user)[1]:
        try:
            context.result = None
            context.detect_token_style(user.token)
        except Exception:
            pass
        if context.token_style:
            api = context.client(user)
            public = context.public
            # If following a link needs a token (A2-MULTI-03 reports that), the
            # Assignment 1 checks follow links with the token, so that one bug
            # does not fail them all.
            probe = api.post("/", {"value": context.url("public-probe")})
            probe_id = returned_id(probe)
            if probe_id and public.get("/" + quote(probe_id, safe="")).status != 301 \
                    and api.get("/" + quote(probe_id, safe="")).status == 301:
                public = api
            shortener = audit_a1.ShortenerContext(api, public, many=200 if args.quick else 1000,
                                                  collision_search=not args.quick)
            results += run_checks(audit_a1.CHECKS, shortener, "A2", args.only, args.verbose)

    for user in context.users:  # remove the audit's mappings; accounts remain
        if user.token:
            try:
                context.client(user).delete("/")
            except ServiceUnreachable:
                break
    title = "TA audit, Assignment 2 (authentication service and multi-user shortener)"
    target = (f"Shortener: {args.url}, authentication: {args.auth_url}. "
              f"{len(results)} checks in {time.monotonic() - started:.0f} s.")
    print_report(title, target, results)
    if args.report:
        write_markdown(args.report, title, target, results)
        print(f"Report written to {args.report}")
    sys.exit(1 if any(result.status == "FAIL" for result in results) else 0)


if __name__ == "__main__":
    main()
