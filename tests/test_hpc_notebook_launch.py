"""Offline HPC image-selection and notebook-launch regression tests."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]


class HPCNotebookTests(unittest.TestCase):
    def test_image_and_command_selection(self):
        source = (ROOT / "roles/k8s_apps/templates/jhub-values.yaml.j2").read_text()
        block = "singleuser:" + source.split("singleuser:", 1)[1].split("  cpu:", 1)[0]
        defaults = yaml.safe_load(
            (ROOT / "roles/k8s_apps/defaults/main.yml").read_text()
        )
        env = Environment(undefined=StrictUndefined)
        env.filters["bool"] = bool
        for runtime, active, general in (
            (False, False, False),
            (False, False, True),
            (True, False, True),
            (True, True, True),
            (True, True, False),
        ):
            with self.subTest(runtime=runtime, active=active, general=general):
                values = yaml.safe_load(env.from_string(block).render(
                    hpc_runtime_enabled=runtime,
                    hpc_workspace_enabled=active,
                    hpc_notebook_image=defaults["hpc_notebook_image"],
                    workshop_notebook_runtime={
                        "enabled": general,
                        "image_name": "general/notebook",
                        "image_tag": "test",
                    },
                ))["singleuser"]
                if runtime and active:
                    self.assertEqual(values["image"], defaults["hpc_notebook_image"])
                    self.assertEqual(values["cmd"], [
                        "/bin/bash", "/runtime/hpc/hpc-notebook-launch.sh",
                        "jupyterhub-singleuser",
                    ])
                else:
                    expected = (
                        {"name": "general/notebook", "tag": "test"} if general
                        else {"name": "jupyter/minimal-notebook", "tag": "python-3.11"}
                    )
                    self.assertEqual(values["image"], expected)
                    self.assertNotIn("cmd", values)

    def run_launch(self, marker="valid"):
        with tempfile.TemporaryDirectory(prefix="hpc-launch-test-") as directory:
            root = Path(directory)
            home = root / "home"
            runtime = home / ".local/share/digitafrica/runtime/hpc"
            prefix = runtime / "environment"
            tools = prefix / "bin"
            tools.mkdir(parents=True)
            specification = root / "environment.yml"
            specification.write_text("test specification\n")
            if marker != "absent":
                digest = hashlib.sha256(specification.read_bytes()).hexdigest()
                (runtime / "environment.sha256").write_text(
                    digest if marker == "valid" else "wrong"
                )

            bin_dir = root / "bin"
            bin_dir.mkdir()
            conda = bin_dir / "conda"
            conda.write_text("""#!/bin/bash
set -eu
test "$1 $2" = "shell.bash hook"
cat <<'HOOK'
conda() {
    test "$1" = activate
    export CC="$2/bin/test-cc"
    export PATH="$2/bin:$PATH"
}
HOOK
""")
            conda.chmod(0o755)
            for name in ("test-cc", "mpicc", "mpirun"):
                executable = tools / name
                executable.write_text("#!/bin/sh\nexit 0\n")
                executable.chmod(0o755)

            notebook = bin_dir / "test-notebook"
            notebook.write_text("#!" + os.sys.executable + """
import json, os, sys
print(json.dumps({"argv": sys.argv[1:], "cc": os.environ.get("CC")}))
""")
            notebook.chmod(0o755)
            # A shadow notebook checks that activation cannot replace the
            # notebook executable resolved from the original image PATH.
            shadow = tools / "test-notebook"
            shadow.write_text("#!/bin/sh\nexit 99\n")
            shadow.chmod(0o755)

            source = (ROOT / "roles/hpc_runtime/files/hpc-notebook-launch.sh").read_text()
            # Redirect only the read-only ConfigMap path for this offline test.
            source = source.replace(
                "specification=/runtime/hpc/environment.yml",
                "specification=" + str(specification),
            )
            wrapper = root / "launch.sh"
            wrapper.write_text(source)
            environment = dict(os.environ)
            environment.update(HOME=str(home), PATH=str(bin_dir) + ":/usr/bin:/bin")
            result = subprocess.run(
                ["bash", str(wrapper), "test-notebook", "--label=two words", ""],
                env=environment, capture_output=True, text=True, timeout=15,
            )
            return result, str(tools / "test-cc")

    def test_activation_preserves_notebook_and_arguments(self):
        result, compiler = self.run_launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "argv": ["--label=two words", ""], "cc": compiler,
        })

    def test_missing_completion_marker_blocks_launch(self):
        result, _ = self.run_launch("absent")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("preparation is incomplete", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_changed_definition_blocks_launch(self):
        result, _ = self.run_launch("wrong")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
