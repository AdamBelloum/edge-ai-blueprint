"""Verified candidate staging under one shared lock; no CLI or Ansible entry point.

Only trusted organiser-rendered inputs are accepted. The caller must exclude
non-cooperating Docker/filesystem writers administratively. This stages files
only: no builds, service changes, account changes or readiness claims.
"""
from livy_candidate_assets import CandidateAssets
from livy_candidate_compose import compose_config, read_baseline
from livy_candidate_observe import (
    locked_submission_runtime, observe_mounts, open_runtime,
)
from livy_candidate_verify import verify_asset_inputs, verify_compose_preservation

COMPOSE = "compose.livy-transition.yaml"


def stage_verified_candidate(
    files, *, reviewed_text_files,
    submission_lock=locked_submission_runtime,
    runtime_context=open_runtime,
    baseline_reader=read_baseline,
    normalize=compose_config,
    mount_observer=observe_mounts,
    assets_factory=CandidateAssets,
):
    """Adapters are injectable for offline tests; defaults target the fixed runtime."""
    with submission_lock() as lock_fd:
        if lock_fd is None:
            raise ValueError("Existing submission runtime is required.")
        with runtime_context() as runtime_fd:
            # Freeze the caller's mappings before observation callbacks.
            if not isinstance(files, dict) or not isinstance(reviewed_text_files, dict):
                raise ValueError("Trusted asset mappings are required.")
            files = dict(files)
            reviewed_text_files = dict(reviewed_text_files)
            verify_asset_inputs(files, reviewed_text_files=reviewed_text_files)
            baseline_text = baseline_reader(runtime_fd)
            baseline = normalize(baseline_text)
            candidate = normalize(files[COMPOSE])
            verify_compose_preservation(baseline, candidate)
            if baseline_reader(runtime_fd) != baseline_text:
                raise ValueError("Existing Compose content changed before staging.")
            return assets_factory(runtime_fd).stage(files, mount_observer)
