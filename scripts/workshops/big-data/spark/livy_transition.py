"""Fail-closed plan for a one-worker direct-to-Livy transition.

This module executes no commands and mutates no filesystem or Docker resources.
The future live caller must hold the shared organiser lock, establish cohort
quiescence, validate image provenance and staged configuration, and collect
fresh master/Livy observations before calling this function. The organiser
lock alone does not fence participant submissions or other administrators.
"""
import re

from teardown_validation import (
    CLIENT_IMAGE, PARTICIPANT_IMAGE, require, validate_snapshot,
)

LIVY_IMAGE = "digitafrica/livy:0.9.0-incubating-spark3.5.3"
ALLOWED = {"spark-master", "spark-worker-1", "spark-client", "spark-livy", "spark-livy-access"}
REFERENCES = {
    "spark-master": CLIENT_IMAGE,
    "spark-worker-1": CLIENT_IMAGE,
    "spark-client": PARTICIPANT_IMAGE,
    "spark-livy": LIVY_IMAGE,
    "spark-livy-access": PARTICIPANT_IMAGE,
}


def running(container):
    state = container.get("State") or {}
    require(type(state.get("Running")) is bool,
            "Missing or invalid service running state.")
    require(state.get("Paused") is False and state.get("Restarting") is False,
            "Paused or restarting service; transition refused.")
    return state["Running"]


def empty_livy_inventory(inventory):
    """Require both bounded GET /sessions and GET /batches observations."""
    require(isinstance(inventory, dict) and set(inventory) == {"sessions", "batches"},
            "Fresh Livy session and batch observations are required.")
    for response in inventory.values():
        require(isinstance(response, dict)
                and type(response.get("total")) is int
                and response["total"] == 0
                and response.get("sessions") == [],
                "Existing Livy sessions or batches; transition refused.")


def plan_transition(containers, networks, volumes, master_status, *,
                    image_ids, expected_hashes, livy_inventory=None):
    """Return minimal proposed actions after validating all supplied observations.

    image_ids maps the three reviewed image references to inspected local IDs.
    expected_hashes comes from the proposed staged Compose service configuration,
    not from existing container labels. Neither input is participant-supplied.
    No stop/start operation is performed by this planner.
    """
    validate_snapshot(containers, networks, volumes)
    services = {}
    for container in containers:
        service = (container["Config"].get("Labels") or {}).get("com.docker.compose.service")
        require(service in ALLOWED, "Unexpected service or organiser test client; transition refused.")
        services[service] = container
    require({"spark-master", "spark-worker-1"} <= set(services),
            "Existing master and exactly one worker are required.")
    require("spark-client" in services or "spark-livy-access" in services,
            "Prepared direct/access identity is required; this is not cold startup.")
    for reference in set(REFERENCES.values()):
        identifier = image_ids.get(reference)
        require(isinstance(identifier, str)
                and re.fullmatch(r"sha256:[0-9a-f]{64}", identifier),
                "All three reviewed local image identities are required.")
    states = {}
    for service, container in services.items():
        config = container["Config"]
        require(config.get("Image") == REFERENCES[service]
                and container.get("Image") == image_ids[REFERENCES[service]],
                "Existing service image identity differs from the reviewed image.")
        expected = expected_hashes.get(service)
        require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected)
                and (config.get("Labels") or {}).get("com.docker.compose.config-hash") == expected,
                "Existing service differs from the proposed staged configuration.")
        states[service] = running(container)
    require(states["spark-master"] and states["spark-worker-1"],
            "Master and worker must already be running; replacement is prohibited.")
    require(not (states.get("spark-client", False) and states.get("spark-livy-access", False)),
            "Both SSH access services are running; inspect explicitly.")
    require(isinstance(master_status, dict)
            and master_status.get("activeapps") == []
            and master_status.get("waitingapps", []) == [],
            "Spark applications are active, queued, or unverified; transition refused.")
    workers = master_status.get("workers")
    require(isinstance(workers, list) and len(workers) == 1
            and isinstance(workers[0], dict)
            and workers[0].get("state") == "ALIVE"
            and workers[0].get("host") == "spark-worker-1",
            "The assigned single Spark worker is not verified ALIVE.")
    if states.get("spark-livy", False):
        empty_livy_inventory(livy_inventory)
    start = [service for service in ("spark-livy", "spark-livy-access")
             if not states.get(service, False)]
    return {
        "stop_client_id": services["spark-client"]["Id"] if states.get("spark-client", False) else None,
        "start_services": start,
        "preserve_service_ids": {
            name: services[name]["Id"] for name in ("spark-master", "spark-worker-1")
        },
        "existing_start_service_ids": {
            name: services[name]["Id"] for name in start if name in services
        },
    }
