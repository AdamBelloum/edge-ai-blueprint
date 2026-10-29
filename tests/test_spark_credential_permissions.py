"""Local startup-permission regressions; no Kubernetes, SSH or real secrets."""
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
HOOK_NAME = "workshop-hooks/spark-credential-permissions.sh.j2"
ENV = Environment(
    loader=FileSystemLoader(str(ROOT / "roles/k8s_apps/templates")),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)
SCRIPT = ENV.get_template(HOOK_NAME).render()


class SparkCredentialPermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.ssh = self.home / ".ssh"
        self.credentials = self.ssh / "spark-direct"
        self.credentials.mkdir(parents=True)
        self.ssh.chmod(0o2770)
        self.credentials.chmod(0o2770)
        self.contents = {"login_key": b"fake-private-key\n", "known_hosts": b"fake-pinned-host\n"}
        for name, content in self.contents.items():
            path = self.credentials / name
            path.write_bytes(content)
            path.chmod(0o660)
        self.other = self.ssh / "unrelated-key"
        self.other.write_bytes(b"preserve unrelated file\n")
        self.other.chmod(0o640)

    def run_hook(self, uid=None):
        if uid is None:
            uid = os.getuid()
        script = SCRIPT.replace("/home/jovyan", str(self.home))
        script = script.replace("spark_credential_uid=1000", "spark_credential_uid=" + str(uid))
        return subprocess.run(["sh", "-eu", "-c", script], text=True, capture_output=True)

    def assert_unmodified_permissions(self):
        self.assertEqual(stat.S_IMODE(self.ssh.stat().st_mode), 0o2770)
        self.assertEqual(stat.S_IMODE(self.credentials.stat().st_mode), 0o2770)
        self.assertEqual(stat.S_IMODE((self.credentials / "login_key").stat().st_mode), 0o660)

    def test_repairs_modes_preserves_contents_and_repeats_after_mount_widening(self):
        owners = {name: (self.credentials / name).stat().st_uid for name in self.contents}
        for attempt in range(3):
            with self.subTest(attempt=attempt):
                result = self.run_hook()
                self.assertEqual(result.returncode, 0, result.stderr)
                for directory in (self.ssh, self.credentials):
                    self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
                for name, content in self.contents.items():
                    path = self.credentials / name
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                    self.assertEqual(path.read_bytes(), content)
                    self.assertEqual(path.stat().st_uid, owners[name])
                self.assertEqual(self.other.read_bytes(), b"preserve unrelated file\n")
                self.assertEqual(stat.S_IMODE(self.other.stat().st_mode), 0o640)
                if attempt == 1:
                    for directory in (self.ssh, self.credentials):
                        directory.chmod(0o2770)
                    for name in self.contents:
                        (self.credentials / name).chmod(0o660)

    def test_missing_credentials_are_not_created(self):
        self.ssh.rename(self.home / "saved-ssh")
        result = self.run_hook()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.ssh.exists())
        self.assertIn("not provisioned", result.stdout)

    def test_missing_host_record_blocks_all_permission_changes(self):
        (self.credentials / "known_hosts").unlink()
        self.assertNotEqual(self.run_hook().returncode, 0)
        self.assert_unmodified_permissions()

    def test_file_symlinks_cannot_change_external_targets(self):
        for name in self.contents:
            with self.subTest(name=name):
                external = Path(self.temp.name) / ("external-" + name)
                external.write_bytes(b"external evidence\n")
                external.chmod(0o666)
                path = self.credentials / name
                path.unlink()
                path.symlink_to(external)
                self.assertNotEqual(self.run_hook().returncode, 0)
                self.assertEqual(external.read_bytes(), b"external evidence\n")
                self.assertEqual(stat.S_IMODE(external.stat().st_mode), 0o666)
                self.assertEqual(stat.S_IMODE(self.credentials.stat().st_mode), 0o2770)
                path.unlink()
                path.write_bytes(self.contents[name])
                path.chmod(0o660)

    def test_ssh_directory_symlink_is_refused(self):
        saved = self.home / "saved-ssh"
        self.ssh.rename(saved)
        self.ssh.symlink_to(saved, target_is_directory=True)
        self.assertNotEqual(self.run_hook().returncode, 0)
        self.assertEqual(stat.S_IMODE(saved.stat().st_mode), 0o2770)

    def test_credential_directory_symlink_is_refused(self):
        saved = self.home / "saved-credentials"
        self.credentials.rename(saved)
        self.credentials.symlink_to(saved, target_is_directory=True)
        self.assertNotEqual(self.run_hook().returncode, 0)
        self.assertEqual(stat.S_IMODE(saved.stat().st_mode), 0o2770)
        self.assertEqual(stat.S_IMODE(self.ssh.stat().st_mode), 0o2770)

    def test_hardlinked_key_and_wrong_owner_are_refused(self):
        os.link(self.credentials / "login_key", Path(self.temp.name) / "linked-key")
        self.assertNotEqual(self.run_hook().returncode, 0)
        self.assert_unmodified_permissions()
        (Path(self.temp.name) / "linked-key").unlink()
        self.assertNotEqual(self.run_hook(uid=os.getuid() + 1).returncode, 0)
        self.assert_unmodified_permissions()

    def test_rendered_include_boundary_is_valid_with_whitespace_trimming(self):
        template = (ROOT / "roles/k8s_apps/templates/jhub-values.yaml.j2").read_text()
        lines = template.splitlines()
        matches = [
            i for i, line in enumerate(lines)
            if "include '" + HOOK_NAME + "'" in line
        ]
        self.assertEqual(len(matches), 1)
        i = matches[0]
        fragment = "\n".join(lines[i:i + 2]) + "\n"
        self.assertIn("big_data_source=/seed/big-data/spark", fragment)

        for lstrip_blocks in (False, True):
            with self.subTest(lstrip_blocks=lstrip_blocks):
                env = Environment(
                    loader=FileSystemLoader(str(ROOT / "roles/k8s_apps/templates")),
                    undefined=StrictUndefined,
                    trim_blocks=True,
                    lstrip_blocks=lstrip_blocks,
                    keep_trailing_newline=False,
                )
                rendered = env.from_string(fragment).render()
                self.assertRegex(
                    rendered,
                    r"\bfi[ \t]*\n[ \t]*big_data_source=/seed/big-data/spark",
                )
                result = subprocess.run(
                    ["sh", "-n"], input=rendered, text=True, capture_output=True
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_hook_is_scoped_to_spark_participant_seed_branch(self):
        template = (ROOT / "roles/k8s_apps/templates/jhub-values.yaml.j2").read_text()
        spark = template.split("          # Spark: preserve participant edits on subsequent spawns.\n", 1)[1]
        participant = spark.split("              participant)\n", 1)[1].split("\n                ;;", 1)[0]
        self.assertEqual(template.count("include '" + HOOK_NAME + "'"), 1)
        self.assertIn("include '" + HOOK_NAME + "'", participant)
        self.assertLess(participant.index(HOOK_NAME), participant.index("big_data_source=/seed/big-data/spark"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
