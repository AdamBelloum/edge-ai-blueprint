"""Local asset/regression checks only; never establish live readiness."""

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

MODULE = Path(__file__).resolve().parents[1]
TEST_MODULES = (
    "test_invocation", "test_lab_config", "test_manifests",
    "test_notebook2_offline", "test_notebook3_offline",
    "test_notebook_live_mocked", "test_notebook_offline", "test_traffic",
)
REQUIRED = (
    ".gitignore", "README.md", "SOURCE.md", "UPSTREAM-LICENSE.txt",
    "beginner/01-explore-and-invoke.ipynb",
    "beginner/02-develop-and-deploy.ipynb",
    "beginner/03-data-and-observability.ipynb",
    "config/.gitignore", "config/lab.example.json",
    "fixtures/weather-sample.json",
    "helpers/invoke.py", "helpers/lab_config.py",
    "helpers/manifests.py", "helpers/traffic.py",
) + tuple(
    f"examples/{function}/{name}"
    for function in ("greeting", "weather")
    for name in ("handler.js", "handler.test.js", "package.json")
) + tuple(f"tests/{name}.py" for name in TEST_MODULES)


def main():
    missing = [name for name in REQUIRED if not (MODULE / name).is_file()]
    if missing:
        print("FAIL: Required pre-live assets are missing:", file=sys.stderr)
        for name in missing:
            print("  " + name, file=sys.stderr)
        return 1
    print("Checking local authoring assets; no deployment or live invocation.", flush=True)
    # Copy only required teaching/test files, not local configs or workspaces.
    with tempfile.TemporaryDirectory(prefix="openfaas-prelive-") as directory:
        copy = Path(directory) / "module5_openfaas"
        for name in REQUIRED:
            destination = copy / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(MODULE / name, destination)
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "-v", *TEST_MODULES],
                cwd=copy / "tests", env=environment, timeout=60,
            )
        except subprocess.TimeoutExpired:
            print("FAIL: Local regressions exceeded 60 seconds.", file=sys.stderr)
            return 1
    if result.returncode != 0:
        print("FAIL: Local Python regressions did not pass.", file=sys.stderr)
        return 1
    print("PASS: Required assets and local Python regressions.")
    print("NOT VALIDATED: Node.js exercises, participant delivery, live runtime,")
    print("authentication, isolation, monitoring, or deployment lifecycle.")
    print("Licensing clarification remains pending; publication remains blocked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
