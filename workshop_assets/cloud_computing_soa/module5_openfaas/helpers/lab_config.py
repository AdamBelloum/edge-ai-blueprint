"""Validate secret-free workshop configuration without contacting the platform."""

import json
from pathlib import Path
import re
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """Configuration is incomplete, unsafe, or unsuitable for live execution."""


def require(condition, message):
    """Raise a configuration error without revealing configuration contents."""
    if not condition:
        raise ConfigurationError(message)


def bounded_number(value, minimum, maximum, label, integer=False):
    """Reject booleans, wrong numeric types, and out-of-range values."""
    allowed_types = (int,) if integer else (int, float)
    require(type(value) in allowed_types, f"{label}: invalid numeric type.")
    require(minimum <= value <= maximum, f"{label}: outside allowed bounds.")


def validate_route(value, label, require_live):
    """Require HTTPS routes without embedded credentials, queries, or fragments."""
    require(isinstance(value, str), f"{label}: expected a URL string.")
    require(not any(char.isspace() for char in value),
            f"{label}: whitespace is not allowed.")
    try:
        route = urlsplit(value)
        port = route.port
    except ValueError:
        raise ConfigurationError(f"{label}: malformed URL.") from None
    require(route.scheme == "https" and bool(route.hostname),
            f"{label}: an HTTPS hostname is required.")
    require(route.username is None and route.password is None,
            f"{label}: embedded credentials are forbidden.")
    require(not route.query and not route.fragment,
            f"{label}: query strings and fragments are forbidden.")
    require(port is None or 1 <= port <= 65535, f"{label}: invalid port.")
    if require_live:
        hostname = route.hostname.lower().rstrip(".")
        require(hostname != "invalid" and not hostname.endswith(".invalid"),
                f"{label}: replace the placeholder route before live execution.")


def load_config(path, require_live=True):
    """Load and validate configuration; live execution is disabled by default.

    Passing require_live=False permits authoring placeholders for offline checks.
    Validation does not establish route reachability, approval, or isolation.
    """
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ConfigurationError(
            "Cannot read valid UTF-8 JSON configuration."
        ) from None

    require(isinstance(config, dict), "Configuration must be a JSON object.")
    expected = {
        "schema_version", "live_test_enabled", "lab_id", "gateway_url",
        "monitoring_url", "registry_repository", "functions", "image_tag",
        "request_timeout_seconds", "readiness_timeout_seconds", "load",
    }
    require(set(config) == expected,
            "Configuration fields do not match schema version 1; keep secrets outside it.")
    require(type(config["schema_version"]) is int and config["schema_version"] == 1,
            "Unsupported schema version.")
    require(type(config["live_test_enabled"]) is bool,
            "live_test_enabled must be a boolean.")
    if require_live:
        require(config["live_test_enabled"],
                "Live execution is disabled; organiser approval and configuration are required.")

    lab_id = config["lab_id"]
    require(isinstance(lab_id, str) and
            re.fullmatch(r"[a-z][a-z0-9-]{0,29}", lab_id) is not None,
            "Invalid lab_id.")

    for label in ("gateway_url", "monitoring_url"):
        validate_route(config[label], label, require_live)

    repository = config["registry_repository"]
    require(isinstance(repository, str), "Invalid registry_repository.")
    validate_route("https://" + repository, "registry_repository", require_live)
    require(re.fullmatch(
        r"[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9]+(?:[._-][a-z0-9]+)*"
        r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*", repository
    ) is not None, "Registry repository must contain a host and scoped repository path.")

    functions = config["functions"]
    require(isinstance(functions, dict) and
            set(functions) == {"prepared_greeting", "greeting", "weather"},
            "Expected prepared_greeting, greeting, and weather function assignments.")
    names = list(functions.values())
    for name in names:
        require(isinstance(name, str) and len(name) <= 63 and
                re.fullmatch(r"[a-z][a-z0-9-]*[a-z0-9]", name) is not None,
                "Invalid assigned function name.")
        require(name.startswith(lab_id + "-"),
                "Assigned function names must use the lab prefix.")
    require(len(set(names)) == 3, "Assigned function names must be distinct.")

    tag = config["image_tag"]
    require(isinstance(tag, str) and
            re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag) is not None and
            tag.lower() != "latest", "Use an explicit image tag, not latest.")

    bounded_number(config["request_timeout_seconds"], 1, 30,
                   "request_timeout_seconds")
    bounded_number(config["readiness_timeout_seconds"], 1, 300,
                   "readiness_timeout_seconds")
    load = config["load"]
    require(isinstance(load, dict) and
            set(load) == {"requests", "interval_seconds", "concurrency"},
            "Invalid bounded-load configuration.")
    bounded_number(load["requests"], 1, 100, "load.requests", integer=True)
    bounded_number(load["interval_seconds"], 0.1, 10, "load.interval_seconds")
    bounded_number(load["concurrency"], 1, 1, "load.concurrency", integer=True)
    return config
