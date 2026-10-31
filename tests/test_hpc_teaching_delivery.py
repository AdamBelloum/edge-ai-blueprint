"""Offline tests of the actual HPC startup teaching-delivery block."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "workshop_assets/hpc"
TEMPLATE = ROOT / "roles/k8s_apps/templates/jhub-values.yaml.j2"


def extract_delivery():
    text = TEMPLATE.read_text()
    start = text.index(
        "          # HPC: explicit teaching-file allowlist; preserve participant edits.\n"
    )
    end = text.index(
        "          # Spark: preserve participant edits on subsequent spawns.\n",
        start,
    )
    block = text[start:end]
    helper_start = text.index("          copy_seed_file() {{ '{{' }}")
    helper_end = text.index('          mkdir -p "$workspace"\n', helper_start)
    functions = text[helper_start:helper_end]
    return functions, block


def render_shell(text):
    return text.replace("{{ '{{' }}", "{").replace("{{ '}}' }}", "}")


def role_files():
    text = (ROOT / "roles/hpc_workspace/defaults/main.yml").read_text()
    section = text.split("hpc_workspace_files:\n", 1)[1]
    return [
        line.strip()[2:]
        for line in section.splitlines()
        if line.strip().startswith("- ")
    ]


class HPCTeachingDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="hpc-teaching-delivery-"
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "temporary workspace"
        self.source = self.root / "seed"
        self.workspace = self.root / "participant/HPC"
        self.source.mkdir(parents=True)

        self.files = role_files()
        for filename in self.files:
            destination = self.source / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ASSETS / filename, destination)
            destination.chmod(0o644)

        # Never change real file ownership in these offline tests.
        self.bin = self.root / "bin"
        self.bin.mkdir()
        chown = self.bin / "chown"
        chown.write_text("#!/bin/sh\nexit 0\n")
        chown.chmod(0o755)

        functions, block = extract_delivery()
        block = block.replace(
            "hpc_source=/seed/hpc",
            "hpc_source=" + shlex.quote(str(self.source)),
        ).replace(
            "hpc_workspace=/home/jovyan/HPC",
            "hpc_workspace=" + shlex.quote(str(self.workspace)),
        )
        self.script = "set -eu\n" + render_shell(functions + block)

    def seed(self, role="participant", module="openmp-01-basics"):
        environment = dict(os.environ)
        environment.update(
            PATH=str(self.bin) + os.pathsep + environment.get("PATH", ""),
            workshop_type="hpc",
            workshop_module=module,
            DIGITAFRICA_HPC_WORKSPACE_ROLE=role,
        )
        return subprocess.run(
            ["bash", "-c", self.script],
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def snapshot(self):
        return {
            str(path.relative_to(self.workspace)): path.read_bytes()
            for path in self.workspace.rglob("*")
            if path.is_file()
        }

    def test_role_and_startup_allowlists_match(self):
        _, block = extract_delivery()
        match = re.search(
            r"for filename in \\\n(.*?)"
            r'                  copy_seed_file ',
            block,
            re.S,
        )
        self.assertIsNotNone(match)
        startup_files = [
            line.strip().split()[0].rstrip(";")
            for line in match.group(1).splitlines()
            if line.strip()
        ]
        self.assertEqual(startup_files, self.files)
        self.assertEqual(len(self.files), 63)
        self.assertEqual(len(set(self.files)), len(self.files))
        self.assertTrue(all((ASSETS / name).is_file() for name in self.files))
        self.assertFalse(any(
            name.startswith(("runtime/", "openmp-01-basics/"))
            for name in self.files
        ))
        tasks = (ROOT / "roles/hpc_workspace/tasks/main.yml").read_text()
        self.assertIn('loop: "{{ hpc_workspace_directories }}"', tasks)
        self.assertIn(
            "'0755' if item in ['OpenMP/helpers/openmp_start', 'MPI/helpers/mpi_start'] else '0644'",
            tasks,
        )

    def test_fresh_delivery_copies_all_files_and_sets_helper_permissions(self):
        result = self.seed()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in self.files:
            self.assertEqual(
                (self.workspace / name).read_bytes(),
                (self.source / name).read_bytes(),
            )
        for relative in (
            "OpenMP/helpers/openmp_start",
            "MPI/helpers/mpi_start",
        ):
            with self.subTest(helper=relative):
                helper = self.workspace / relative
                self.assertEqual(helper.stat().st_mode & 0o777, 0o755)
        self.assertTrue((self.workspace / "MPI").is_dir())
        self.assertTrue((self.workspace / "HPC_SEED_RECEIPT.txt").is_file())
        self.assertFalse((self.workspace / "runtime").exists())

    def test_repeat_startup_preserves_edits_notes_and_receipt(self):
        result = self.seed()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in (
            "README.md",
            "OpenMP/01-openmp-debugging.ipynb",
            "OpenMP/exercises/code1/code.c",
            "OpenMP/helpers/openmp_start",
            "MPI/01-mpi-debugging.ipynb",
            "MPI/exercises/code1/code.c",
            "MPI/helpers/mpi_start",
        ):
            path = self.workspace / name
            path.write_bytes(path.read_bytes() + b"\nparticipant edit\n")
        (self.workspace / "OpenMP/my-notes.md").write_text("Keep my notes\n")
        (self.workspace / "MPI/my-notes.md").write_text("Keep MPI notes\n")
        legacy = self.workspace / "openmp-01-basics/01-beginner"
        legacy.mkdir(parents=True)
        (legacy / "hello.c").write_text("Keep legacy work\n")
        before = self.snapshot()

        result = self.seed()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.snapshot())
        self.assertIn("preserving existing file", result.stdout)

    def test_partial_workspace_preserves_existing_code_and_adds_missing_files(self):
        code = self.workspace / "OpenMP/exercises/code2/code.c"
        code.parent.mkdir(parents=True)
        code.write_text("My existing correction\n")
        result = self.seed()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(code.read_text(), "My existing correction\n")
        self.assertTrue(
            (self.workspace / "OpenMP/01-openmp-debugging.ipynb").is_file()
        )

    def test_administrator_skips_participant_delivery(self):
        result = self.seed(role="administrator")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("participant HPC workspace skipped", result.stdout)
        self.assertFalse(self.workspace.exists())

    def test_disabled_delivery_fails_without_creating_workspace(self):
        result = self.seed(role="disabled")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HPC source delivery is not enabled", result.stderr)
        self.assertFalse(self.workspace.exists())

    def test_missing_source_fails_without_a_completion_receipt(self):
        # Even an existing participant copy must not conceal missing seed input.
        relative = "OpenMP/exercises/code4/solution.md"
        existing = self.workspace / relative
        existing.parent.mkdir(parents=True)
        existing.write_text("Existing participant reference\n")
        (self.source / relative).unlink()
        result = self.seed()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing required seed file", result.stderr)
        self.assertEqual(
            existing.read_text(), "Existing participant reference\n"
        )
        self.assertFalse(
            (self.workspace / "HPC_SEED_RECEIPT.txt").exists()
        )

    def test_notebook_structure_and_python_cells(self):
        notebook = json.loads(
            (ASSETS / "OpenMP/01-openmp-debugging.ipynb").read_text()
        )
        self.assertEqual(notebook["nbformat"], 4)
        self.assertEqual(notebook["nbformat_minor"], 5)
        self.assertEqual(notebook["metadata"]["license"], "Apache-2.0")
        cells = notebook["cells"]
        self.assertEqual(len(cells), 50)
        self.assertEqual(len({cell["id"] for cell in cells}), len(cells))
        solution_commands = []
        for index, cell in enumerate(cells):
            self.assertIn(cell["cell_type"], ("markdown", "code"))
            self.assertIsInstance(cell["source"], list)
            if cell["cell_type"] != "code":
                continue
            self.assertIsNone(cell["execution_count"])
            self.assertEqual(cell["outputs"], [])
            source = "".join(cell["source"])
            if source.startswith("!"):
                self.assertEqual(len(source.strip().splitlines()), 1)
                self.assertTrue(source.startswith("!openmp_start "))
                if "--solution" in source:
                    solution_commands.append(source.strip())
                    previous = "".join(cells[index - 1]["source"])
                    self.assertIn("after your attempt", previous)
            else:
                ast.parse(source)
        self.assertEqual(solution_commands, [
            f"!openmp_start code{number} --solution"
            for number in range(1, 5)
        ])

    def test_delivered_notebook_setup_and_problem_command(self):
        result = self.seed()
        self.assertEqual(result.returncode, 0, result.stderr)
        module = self.workspace / "OpenMP"
        notebook = json.loads(
            (module / "01-openmp-debugging.ipynb").read_text()
        )
        setup = "".join(next(
            cell["source"] for cell in notebook["cells"]
            if cell["cell_type"] == "code"
            and not "".join(cell["source"]).startswith("!")
        ))
        # CC is checked for availability only; it is never invoked here.
        environment = dict(os.environ)
        environment["CC"] = shlex.quote(sys.executable)
        program = setup + (
            "\nimport subprocess\n"
            "subprocess.run("
            "['openmp_start', 'code1', '--problem'], check=True)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", program],
            cwd=module,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Exercise helper:", result.stdout)
        self.assertIn("Why is there only one thread?", result.stdout)


    def test_mpi_selection_delivers_shared_workspace_and_preserves_edits(self):
        result = self.seed(module="mpi-01-basics")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in self.files:
            with self.subTest(file=name):
                self.assertEqual(
                    (self.workspace / name).read_bytes(),
                    (self.source / name).read_bytes(),
                )
        for name in ("OpenMP/helpers/openmp_start", "MPI/helpers/mpi_start"):
            self.assertEqual(
                (self.workspace / name).stat().st_mode & 0o777, 0o755
            )
        code = self.workspace / "MPI/exercises/code7/code.c"
        code.write_text("Participant correction\n")
        (self.workspace / "MPI/my-notes.md").write_text("Keep MPI notes\n")
        before = self.snapshot()
        result = self.seed(module="mpi-01-basics")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.snapshot())
        self.assertIn("preserving existing file", result.stdout)

    def test_mpi_missing_source_fails_without_completion_receipt(self):
        relative = "MPI/exercises/code7/solution.md"
        existing = self.workspace / relative
        existing.parent.mkdir(parents=True)
        existing.write_text("Keep participant reference\n")
        (self.source / relative).unlink()
        result = self.seed(module="mpi-01-basics")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing required seed file", result.stderr)
        self.assertEqual(existing.read_text(), "Keep participant reference\n")
        self.assertFalse((self.workspace / "HPC_SEED_RECEIPT.txt").exists())

    def test_mpi_manifest_covers_distributed_assets_and_matches_hashes(self):
        module = ASSETS / "MPI"
        manifest = json.loads((module / "source-manifest.json").read_text())
        self.assertEqual(
            manifest["source_revision"],
            "297aaf15cda80e5ced209a7f0edeeb940f5713d5",
        )
        expected = {
            name.removeprefix("MPI/")
            for name in self.files if name.startswith("MPI/")
        } - {"source-manifest.json"}
        records = manifest["generated_sha256"]
        self.assertEqual(set(records), expected)
        self.assertEqual(len(records), 40)
        for name, digest in records.items():
            with self.subTest(file=name):
                self.assertEqual(
                    hashlib.sha256((module / name).read_bytes()).hexdigest(),
                    digest,
                )

    def test_current_seed_provenance_checksums_match(self):
        provenance = (ASSETS / "PROVENANCE.md").read_text()
        section = provenance.split(
            "## Current participant seed SHA-256 checksums\n", 1
        )[1]
        records = re.findall(
            r"^([0-9a-f]{64})  (.+)$", section, re.M
        )
        expected = set(self.files) - {"PROVENANCE.md"}
        self.assertEqual({name for _, name in records}, expected)
        self.assertEqual(len(records), len(expected))
        for digest, name in records:
            with self.subTest(file=name):
                self.assertEqual(
                    hashlib.sha256((ASSETS / name).read_bytes()).hexdigest(),
                    digest,
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
