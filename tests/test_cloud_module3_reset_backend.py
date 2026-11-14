"""Offline orchestration tests for the Cloud Module 3 reset backend.

The runtime helper is a stub. These tests cover ordering and failure
handling in reset-workshop.sh, not the real confirmation prompt or the
Docker/Kubernetes cleanup.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT / "scripts/workshops/cloud-computing-soa"

STUBS = {
    "context": ("scripts/workshops/lib/workshop-context.sh",
                "load_workshop_context() { return 0; }\n"),
    "common": ("scripts/lib/common.sh", ": # common.sh stub\n"),
    "runtime": (
        "scripts/workshops/cloud-computing-soa/module3-runtime.sh",
        'cloud_module3_runtime_reset_confirmed() {\n'
        '  if [ -e "$CLOUD_MODULE3_ENDPOINTS_PATH" ]; then\n'
        '    printf "runtime-reset endpoint_present=1\\n" >> "$MOCK_LOG"\n'
        '  else\n'
        '    printf "runtime-reset endpoint_present=0\\n" >> "$MOCK_LOG"\n'
        '  fi\n'
        '  return "$MOCK_RUNTIME_STATUS"\n'
        '}\n',
    ),
}


def run_backend(arguments, runtime_status=0, omit=()):
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        backend_dir = base / "scripts/workshops/cloud-computing-soa"
        backend_dir.mkdir(parents=True)
        shutil.copy2(BACKEND_SRC / "reset-workshop.sh",
                     backend_dir / "reset-workshop.sh")
        shutil.copy2(BACKEND_SRC / "module3_endpoints.py",
                     backend_dir / "module3_endpoints.py")
        for name, (relative, content) in STUBS.items():
            if name in omit:
                continue
            target = base / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        endpoints = base / "state" / "endpoints.tsv"
        endpoints.parent.mkdir(parents=True)
        endpoints.write_text("seeded\n")
        log = base / "calls.log"
        environment = os.environ.copy()
        for name in ("BASH_ENV", "ENV"):
            environment.pop(name, None)
        environment.update(
            MOCK_LOG=str(log),
            MOCK_RUNTIME_STATUS=str(runtime_status),
            CLOUD_MODULE3_ENDPOINTS_PATH=str(endpoints),
            XDG_STATE_HOME=str(base / "state"),
        )
        result = subprocess.run(
            ["bash", str(backend_dir / "reset-workshop.sh"), *arguments],
            env=environment, capture_output=True, text=True, timeout=10,
        )
        result.calls = log.read_text().splitlines() if log.exists() else []
        result.endpoint_exists = endpoints.exists()
        return result


ARGS = ["--runtime-only", "--module", "module3"]


class Module3BackendOrchestrationTests(unittest.TestCase):
    def test_success_removes_runtime_before_endpoint_file(self):
        result = run_backend(ARGS)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.calls, ["runtime-reset endpoint_present=1"])
        self.assertFalse(result.endpoint_exists)

    def test_runtime_failure_preserves_endpoint_and_exits_3(self):
        result = run_backend(ARGS, runtime_status=1)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("declined or failed", result.stderr)
        self.assertTrue(result.endpoint_exists)

    def test_missing_dependency_preserves_endpoint_and_exits_3(self):
        for omitted in ("context", "runtime"):
            with self.subTest(omitted=omitted):
                result = run_backend(ARGS, omit=(omitted,))
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertTrue(result.endpoint_exists)

    def test_old_attestation_flag_is_rejected(self):
        result = run_backend(
            ARGS + ["--confirm-no-external-module3-runtime"])
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.calls, [])
        self.assertTrue(result.endpoint_exists)


if __name__ == "__main__":
    unittest.main()
