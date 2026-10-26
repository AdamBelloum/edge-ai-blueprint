"""Host-local teardown wiring; no executable entry point."""
from teardown_directory import locked_evidence_directory, locked_submission_runtime
from teardown_docker import Docker
from teardown_evidence import load_evidence, save_evidence
from teardown_sequence import teardown


def run_teardown():
    """Require secure evidence storage and lock before accessing Docker."""
    with locked_evidence_directory() as directory_fd:
        with locked_submission_runtime():
            docker = Docker()
            daemon_id = docker.daemon_id()
            return teardown(
                snapshot=docker.snapshot,
                load_evidence=lambda: load_evidence(directory_fd, daemon_id),
                save_evidence=lambda ids: save_evidence(
                    directory_fd, daemon_id, ids
                ),
                remove_container=docker.remove_container,
                remove_network=docker.remove_network,
            )
