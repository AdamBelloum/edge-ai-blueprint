"""Behavioural tests for the worker-runtime check embedded in health-check.sh.

Deployment owns the client app and the locked requirements. The workshop
organiser owns the prepared partition and its manifest.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "admin" / "health-check.sh"
GROUP = "group_01"


def embedded_checker() -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    found = re.findall(r"python3 - <<'PYTHON'\n(.*?)\nPYTHON\n", text, re.DOTALL)
    if len(found) != 1:
        raise AssertionError(f"expected one embedded checker, found {len(found)}")
    return found[0]


CODE = embedded_checker()


def run_checker(root: Path):
    env = dict(os.environ, EXPECTED_GROUP_ID=GROUP, WORKSHOP_RUNTIME_ROOT=str(root))
    return subprocess.run(
        [sys.executable, "-c", CODE], env=env, capture_output=True, text=True
    )


def deployed(root: Path, lock: str = "flwr==1.0\n") -> None:
    (root / "app" / "client").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "app" / "client" / "client.py").write_text("print('x')\n")
    (root / "app" / "requirements.lock").write_text(lock)


def prepared(root: Path, sha: str | None = None) -> None:
    payload = b"a,b\n1,2\n3,4\n"
    (root / "data" / "train.csv").write_bytes(payload)
    manifest = {
        "group_id_format": "group_{NN}",
        "source_sha256": "0" * 64,
        "partitions": {
            GROUP: {"sha256": sha or hashlib.sha256(payload).hexdigest(), "rows": 2}
        },
    }
    (root / "data" / "partition-manifest.json").write_text(json.dumps(manifest))


class TestWorkerRuntimeCheck(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_deployment_only_state_passes(self):
        deployed(self.root)
        result = run_checker(self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("worker_runtime_integrity=PASSED", result.stdout)
        self.assertIn("partition_state=not-prepared", result.stdout)

    def test_missing_client_app_fails(self):
        deployed(self.root)
        (self.root / "app" / "client" / "client.py").unlink()
        result = run_checker(self.root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing worker runtime asset", result.stderr)

    def test_unlocked_requirement_fails_even_without_partition(self):
        deployed(self.root, lock="flwr\n")
        result = run_checker(self.root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unlocked requirement", result.stderr)

    def test_partial_partition_state_fails(self):
        deployed(self.root)
        prepared(self.root)
        (self.root / "data" / "train.csv").unlink()
        result = run_checker(self.root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("partial partition state", result.stderr)

    def test_prepared_partition_is_fully_validated(self):
        deployed(self.root)
        prepared(self.root)
        result = run_checker(self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("partition_rows=2", result.stdout)
        self.assertIn("worker_runtime_integrity=PASSED", result.stdout)

    def test_prepared_partition_with_wrong_checksum_fails(self):
        deployed(self.root)
        prepared(self.root, sha="f" * 64)
        result = run_checker(self.root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum differs", result.stderr)


if __name__ == "__main__":
    unittest.main()
