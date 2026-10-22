"""Teardown sequencing only; all external operations are injected."""
from teardown_validation import validate_snapshot


def teardown(*, snapshot, load_evidence, save_evidence,
             remove_container, remove_network):
    """Fail closed; retain ownership evidence if cleanup fails.

    Caller must serialize cooperating teardown runs and securely manage
    host-local evidence. Snapshot must discover all project resources.
    Docker access must remain administrator-controlled during cleanup.
    """
    evidence = set(load_evidence())
    initial = validate_snapshot(
        *snapshot(), verified_legacy_network_ids=evidence
    )
    evidence.update(initial["legacy_network_ids"])

    # Durable evidence must exist before the first container removal.
    save_evidence(evidence)
    for identifier in initial["container_ids"]:
        remove_container(identifier)

    # Revalidate current ownership and endpoints before removing networks.
    current = validate_snapshot(
        *snapshot(), verified_legacy_network_ids=evidence
    )
    if current["container_ids"]:
        raise ValueError("Project containers remain or appeared; cleanup refused.")
    if not set(current["network_ids"]) <= set(initial["network_ids"]):
        raise ValueError("Project network identity changed; cleanup refused.")

    for identifier in current["network_ids"]:
        remove_network(identifier)

    final = validate_snapshot(
        *snapshot(), verified_legacy_network_ids=evidence
    )
    if final["container_ids"] or final["network_ids"]:
        raise ValueError("Spark runtime cleanup could not be verified.")

    # Clear retry evidence only after verified absence of project resources.
    save_evidence(set())
    return {
        "container_ids": initial["container_ids"],
        "network_ids": current["network_ids"],
    }
