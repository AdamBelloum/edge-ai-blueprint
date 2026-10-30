"""Host-local teardown wiring; no executable entry point."""
from teardown_assets import validated_runtime_assets
from teardown_seed import validated_seed_assets
from teardown_images import ImageCleanup
from teardown_directory import locked_evidence_directory, locked_submission_runtime
from teardown_docker import Docker
from teardown_evidence import clear_evidence, load_evidence, save_evidence
from teardown_sequence import teardown


def run_teardown():
    """Preflight files; remove Docker resources; delete files under both locks."""
    with locked_evidence_directory() as directory_fd:
        with locked_submission_runtime():
            with validated_runtime_assets() as assets, validated_seed_assets() as seed:
                docker = Docker()
                daemon_id = docker.daemon_id()
                images = ImageCleanup(docker)
                result = teardown(
                    snapshot=docker.snapshot,
                    load_evidence=lambda: load_evidence(directory_fd, daemon_id),
                    save_evidence=lambda ids: save_evidence(directory_fd, daemon_id, ids),
                    remove_container=docker.remove_container,
                    remove_network=docker.remove_network,
                )
                result["removed_image_references"] = images.remove()
                result["removed_asset_paths"] = assets.remove() + seed.remove()
                result["retry_evidence_removed"] = clear_evidence(directory_fd, daemon_id)
                return result
