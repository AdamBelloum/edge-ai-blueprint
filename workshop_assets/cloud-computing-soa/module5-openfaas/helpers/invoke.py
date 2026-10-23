"""Bounded synchronous function invocation using Python's standard library.

No credentials are read or printed. Protected invocation authentication remains
an execution-contract decision; this helper does not bypass gateway access rules.
"""

from dataclasses import dataclass
import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from lab_config import load_config


MAX_RESPONSE_BYTES = 65536


class InvocationError(RuntimeError):
    """Invocation failed without exposing URLs, credentials, or response bodies."""


class NoRedirects(HTTPRedirectHandler):
    """Prevent automatic forwarding to another route."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class InvocationResult:
    """Bounded response with only allowlisted headers."""

    status: int
    headers: dict
    body: str

    def json(self):
        """Parse a JSON response without echoing its contents on failure."""
        try:
            return json.loads(self.body)
        except ValueError:
            raise InvocationError("Response is not valid JSON.") from None


def invoke(config_path, function_key, payload=None, method="POST"):
    """Invoke one assigned function after validating live configuration.

    Dictionary/list payloads are encoded as JSON. Bytes permit explicit malformed
    JSON exercises. GET is supported for method-not-allowed tests. There are no
    retries: callers control the number and pacing of requests.
    """
    config = load_config(config_path)
    if function_key not in config["functions"]:
        raise InvocationError("Choose an assigned function key.")
    if method not in ("POST", "GET"):
        raise InvocationError("Only POST and GET are supported.")

    if isinstance(payload, bytes):
        data = payload
    elif payload is None:
        data = None
    else:
        try:
            data = json.dumps(payload, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError):
            raise InvocationError("Payload cannot be encoded as JSON.") from None

    if data is not None and len(data) > MAX_RESPONSE_BYTES:
        raise InvocationError("Request body exceeds the 64 KiB exercise limit.")

    name = config["functions"][function_key]
    url = config["gateway_url"].rstrip("/") + "/function/" + name
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    opener = build_opener(NoRedirects())

    try:
        try:
            response = opener.open(
                request, timeout=config["request_timeout_seconds"]
            )
        except HTTPError as error:
            # HTTP failure statuses are exercise results, not transport failures.
            response = error

        with response:
            status = response.code
            if 300 <= status < 400:
                raise InvocationError("Redirect refused; check the assigned route.")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise InvocationError("Response exceeds the 64 KiB exercise limit.")
            headers = {
                name.lower(): response.headers[name]
                for name in ("Content-Type", "Allow")
                if name in response.headers
            }

        try:
            body = raw.decode("utf-8")
        except UnicodeError:
            raise InvocationError("Response is not valid UTF-8.") from None
        return InvocationResult(status=status, headers=headers, body=body)

    except InvocationError:
        raise
    except (URLError, OSError, ValueError):
        raise InvocationError(
            "Transport failed; check lab readiness, route, TLS and access with the organiser."
        ) from None
