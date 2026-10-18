"""Bounded sequential exercise traffic; no automatic retries or background jobs."""

from collections import Counter
import time

from invoke import invoke
from lab_config import load_config


def run_traffic(config_path, function_key, payload):
    """Send the configured number of requests and return aggregate observations.

    Configuration is validated before traffic begins. Requests are sequential,
    with a configured pause between completed requests. Transport failures stop
    the exercise immediately; HTTP error statuses are counted as responses.

    Latencies measure client-observed request duration, not function execution
    time. Status counts are not a substitute for platform monitoring.
    """
    config = load_config(config_path)
    if function_key not in config["functions"]:
        raise ValueError("Choose an assigned function key.")

    settings = config["load"]
    statuses = Counter()
    latencies = []

    for index in range(settings["requests"]):
        started = time.perf_counter()
        result = invoke(config_path, function_key, payload)
        latencies.append(time.perf_counter() - started)
        statuses[result.status] += 1

        if index + 1 < settings["requests"]:
            time.sleep(settings["interval_seconds"])

    return {
        "completed_requests": len(latencies),
        "status_counts": dict(sorted(statuses.items())),
        "client_latency_seconds": {
            "minimum": min(latencies),
            "mean": sum(latencies) / len(latencies),
            "maximum": max(latencies),
        },
    }
