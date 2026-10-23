"""Offline failure-boundary tests; no recovery, Ansible, or network calls."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PREPARE = Path(__file__).resolve().parents[1] / (
    "scripts/workshops/federated-learning/prepare-workshop.sh"
)

STUB = """#!/usr/bin/env bash
name="$(basename "$0")"
printf '%s %s\\n' "$name" "$*"
case "$name" in
  cohort) exit "$COHORT_STATUS" ;;
  readiness)
    if [[ "$*" == *--skip-participant-mapping* ]]; then
      exit "$PRECHECK_STATUS"
    fi
    exit "$POSTCHECK_STATUS"
    ;;
esac
exit 0
"""

RUNNER = """
set -euo pipefail
source "$PREPARE_SCRIPT"
die() { printf '%s\\n' "$*" >&2; exit 2; }
print_heading() { :; }
ensure_workshop_activation_allowed() { :; }
recover_and_stage_fl_partitions() { echo recovery; return "$RECOVERY_STATUS"; }
publish_prepared_fl_cohort() { echo publish; }
# Stub destructive workspace cleanup; retain publication in lifecycle assertions.
start_new_cohort() { publish_prepared_fl_cohort "$1"; }
if prepare_federated_learning_workshop beginner; then
  exit 0
else
  exit "$?"
fi
"""


class PreparationFailureBoundaryTests(unittest.TestCase):
    def test_failures_stop_conditional_callers(self):
        cases = (
            ("COHORT_STATUS", 13, "recovery"),
            ("RECOVERY_STATUS", 23, "readiness"),
            ("PRECHECK_STATUS", 7, "publish"),
            ("POSTCHECK_STATUS", 9, "flower restart"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("cohort", "flower", "readiness"):
                path = root / name
                path.write_text(STUB)
                path.chmod(0o755)
            for key, status, forbidden in cases:
                with self.subTest(boundary=key):
                    env = os.environ.copy()
                    env.update({case[0]: "0" for case in cases})
                    env.update(
                        PREPARE_SCRIPT=str(PREPARE),
                        COHORT_WORKFLOW=str(root / "cohort"),
                        FLOWER_MANAGER=str(root / "flower"),
                        WORKSHOP_READINESS_CHECKER=str(root / "readiness"),
                    )
                    env[key] = str(status)
                    result = subprocess.run(
                        ["bash", "-c", RUNNER], env=env,
                        capture_output=True, text=True, timeout=15,
                    )
                    self.assertEqual(
                        result.returncode, status, result.stdout + result.stderr
                    )
                    self.assertNotIn(forbidden, result.stdout)


class PublicationFailureBoundaryTests(unittest.TestCase):
    def test_real_publication_propagates_failures(self):
        runner = """
set -euo pipefail
source "$PUBLICATION_SCRIPT"
die() { printf '%s\\n' "$*" >&2; exit 2; }
print_heading() { :; }
remote_calls=0
run_deployment_remote() {
  remote_calls=$((remote_calls + 1))
  printf 'remote %s\\n' "$remote_calls"
  if ((remote_calls == 1)); then return "$PATCH_STATUS"; fi
  return "$STATE_STATUS"
}
if publish_prepared_fl_cohort beginner; then
  echo published
  exit 0
else
  exit "$?"
fi
"""
        cases = (
            ("PATCH_STATUS", 31),
            ("MAPPING_STATUS", 32),
            ("STATE_STATUS", 33),
            ("PATCH_STATUS", 0),
        )
        with tempfile.TemporaryDirectory() as temporary:
            mapping = Path(temporary) / "mapping"
            mapping.write_text(
                '#!/usr/bin/env bash\necho mapping\nexit "$MAPPING_STATUS"\n'
            )
            mapping.chmod(0o755)
            for key, status in cases:
                with self.subTest(boundary=key, status=status):
                    env = os.environ.copy()
                    env.update({case[0]: "0" for case in cases})
                    env.update(
                        PUBLICATION_SCRIPT=str(PREPARE.with_name("publish-workshop.sh")),
                        COHORT_MAPPING_HELPER=str(mapping),
                        DIGITAFRICA_NAMESPACE="offline-fixture",
                    )
                    env[key] = str(status)
                    result = subprocess.run(
                        ["bash", "-c", runner], env=env,
                        capture_output=True, text=True, timeout=15,
                    )
                    self.assertEqual(
                        result.returncode, status, result.stdout + result.stderr
                    )
                    if status:
                        self.assertNotIn("published\n", result.stdout)
                    else:
                        self.assertIn("published\n", result.stdout)
                    if key == "PATCH_STATUS" and status:
                        self.assertNotIn("mapping\n", result.stdout)
                    if key == "MAPPING_STATUS" and status:
                        self.assertNotIn("remote 2\n", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
