"""Strict wire requests for the fixed-exercise Spark participant pilot.

This module parses requests; it does not grant access or execute work.
The service must establish group/node assignment through platform-controlled
socket exposure and service configuration, never through request fields or
participant environment variables. Request IDs are correlation labels, not
credentials. Source, commands, connection settings and paths are never supplied
by the client. Each connection carries one newline-terminated JSON request.
"""
import json
import re
from types import MappingProxyType
from typing import NamedTuple, Optional
import uuid

PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 1024
EXERCISE_FILES = MappingProxyType({
    "direct": "01_spark_basics.py",
    "livy": "02_spark_via_livy.py",
})
_ID = re.compile(r"[0-9a-f]{32}\Z")


class RequestError(ValueError):
    """Malformed or unsupported submission request."""


class SubmissionRequest(NamedTuple):
    operation: str
    request_id: str
    exercise: Optional[str]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RequestError("Duplicate request field: " + key)
        result[key] = value
    return result


def decode_request(frame: bytes) -> SubmissionRequest:
    """Validate one complete bounded frame; fail closed on extra fields."""
    if type(frame) is not bytes:
        raise RequestError("Request frame must be bytes")
    if not frame or len(frame) > MAX_REQUEST_BYTES:
        raise RequestError("Request frame is empty or exceeds the byte limit")
    if not frame.endswith(b"\n") or b"\n" in frame[:-1]:
        raise RequestError("Expected exactly one newline-terminated JSON frame")
    try:
        value = json.loads(frame[:-1].decode("utf-8"),
                           object_pairs_hook=_unique_object)
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise RequestError("Invalid JSON request") from error
    if type(value) is not dict:
        raise RequestError("Request must be a JSON object")
    if type(value.get("version")) is not int or value["version"] != PROTOCOL_VERSION:
        raise RequestError("Unsupported protocol version")
    operation = value.get("operation")
    if type(operation) is not str or operation not in ("run", "status"):
        raise RequestError("Unsupported operation")
    expected = {"version", "operation", "request_id"}
    if operation == "run":
        expected.add("exercise")
    if set(value) != expected:
        raise RequestError("Missing or unsupported request fields")
    request_id = value["request_id"]
    if type(request_id) is not str or _ID.fullmatch(request_id) is None:
        raise RequestError("Request ID must be 32 lowercase hexadecimal characters")
    exercise = value.get("exercise")
    if operation == "run":
        if type(exercise) is not str or exercise not in EXERCISE_FILES:
            raise RequestError("Only the approved direct and livy exercises are supported")
    return SubmissionRequest(operation, request_id, exercise)


def _encode(value):
    frame = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    decode_request(frame)
    return frame


def encode_run_request(exercise: str, request_id: Optional[str] = None) -> bytes:
    """Create a validated run frame; generate a new correlation ID if omitted."""
    if request_id is None:
        request_id = uuid.uuid4().hex
    return _encode({"version": PROTOCOL_VERSION, "operation": "run",
                    "request_id": request_id, "exercise": exercise})


def encode_status_request(request_id: str) -> bytes:
    """Create a validated lookup frame; the service must scope the lookup."""
    return _encode({"version": PROTOCOL_VERSION, "operation": "status",
                    "request_id": request_id})
