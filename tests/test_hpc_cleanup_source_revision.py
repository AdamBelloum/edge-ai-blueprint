"""Pinned-revision tests in disposable Git repositories and mocked wrappers."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_hpc_cleanup_orchestration import ROOT, builder, inventory, invoke
from test_hpc_reset_entrypoint import invoke as invoke_reset

DEPLOYED_REVISION = "75740411e0333568532a253bf9b87aed09bd0f73"


class SourceRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for relative in ("roles/hpc_workspace", "roles/hpc_runtime", "workshop_assets/hpc"):
            shutil.copytree(ROOT / relative, self.root / relative)
        self.git("init", "-q")
        self.git("add", ".")
        self.commit("initial installed baseline")
        self.revision = self.git("rev-parse", "HEAD").strip()
        self.helper = self.root / "workshop_assets/hpc/MPI/helpers/mpi_start"
        self.old_hash = hashlib.sha256(self.helper.read_bytes()).hexdigest()
        self.helper.write_bytes(self.helper.read_bytes() + b"\n# changed fixture revision\n")
        self.git("add", ".")
        self.commit("new helper baseline")
        self.current = self.git("rev-parse", "HEAD").strip()

    def git(self, *arguments):
        result = subprocess.run(
            ["git", "-C", str(self.root), "-c", "core.hooksPath=/dev/null", *arguments],
            check=True, capture_output=True, text=True,
        )
        return result.stdout

    def commit(self, message):
        self.git("-c", "user.name=Offline Test", "-c", "user.email=test@example.invalid",
                 "commit", "-q", "--allow-empty", "-m", message)

    def build(self, revision=None):
        return builder.build(self.root, inventory(), "workers", "central", revision)

    def helper_hash(self, plan):
        entries = plan["hpc_cleanup_jobs"][0]["manifest"]["files"]
        return next(entry["sha256"] for entry in entries if entry["path"] == "MPI/helpers/mpi_start")

    def test_historical_git_blob_is_used_without_checkout_or_overwrite(self):
        before = self.helper.read_bytes()
        plan = self.build(self.revision)
        self.assertEqual(plan["hpc_cleanup_source_revision"], self.revision)
        self.assertEqual(self.helper_hash(plan), self.old_hash)
        self.assertEqual(self.helper.read_bytes(), before)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.current)

    def test_default_still_uses_current_working_tree(self):
        plan = self.build()
        self.assertEqual(plan["hpc_cleanup_source_revision"], "working-tree")
        self.assertEqual(self.helper_hash(plan), hashlib.sha256(self.helper.read_bytes()).hexdigest())
        self.assertNotEqual(self.helper_hash(plan), self.old_hash)

    def test_abbreviated_named_and_unknown_revisions_are_refused(self):
        for revision in ("HEAD", self.revision[:7], "-bad", "f" * 40):
            with self.subTest(revision=revision):
                with self.assertRaises(ValueError):
                    self.build(revision)

    def test_installation_role_changes_are_refused(self):
        role = self.root / "roles/hpc_workspace/tasks/main.yml"
        role.write_text(role.read_text() + "\n# changed installation contract\n")
        with self.assertRaises(ValueError):
            self.build(self.revision)

    def test_nonancestor_commit_is_refused(self):
        self.git("checkout", "--orphan", "unrelated")
        self.commit("unrelated root commit")
        unrelated = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", self.current)
        with self.assertRaises(ValueError):
            self.build(unrelated)


class RevisionArgumentTests(unittest.TestCase):
    def test_reset_wrapper_forwards_revision_to_both_stages(self):
        for module in ("openmp-01-basics", "mpi-01-basics"):
            with self.subTest(module=module):
                result, calls = invoke_reset([
                    "--runtime-only", "--module", module,
                    "--source-revision", DEPLOYED_REVISION,
                ])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, [
                    "--check --source-revision " + DEPLOYED_REVISION,
                    "--execute --source-revision " + DEPLOYED_REVISION,
                ])

    def test_invalid_revision_arguments_never_invoke_cleanup(self):
        for revision in ("HEAD", "7574041", "not-a-commit"):
            result, calls = invoke_reset([
                "--runtime-only", "--module", "mpi-01-basics",
                "--source-revision", revision,
            ])
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(calls, [])
            result, calls, remaining = invoke(["--execute", "--source-revision", revision])
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(calls, [])
            self.assertEqual(remaining, [])

    def test_orchestrator_carries_pinned_revision_in_manifest(self):
        exists = subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "-e", DEPLOYED_REVISION + "^{commit}"],
            capture_output=True,
        )
        if exists.returncode != 0:
            self.skipTest("Historical deployment commit unavailable in this clone")
        result, calls, remaining = invoke(["--check", "--source-revision", DEPLOYED_REVISION])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[-1]["manifest"]["hpc_cleanup_source_revision"], DEPLOYED_REVISION)
        self.assertIn("hpc_cleanup_execute=false", calls[-1]["args"])
        self.assertEqual(remaining, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
