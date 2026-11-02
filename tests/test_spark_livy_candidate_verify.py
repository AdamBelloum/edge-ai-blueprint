"""Offline checksum and Compose-preservation tests; no live archive or Docker."""
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml
from ansible.plugins.filter.core import to_bool
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
old_path = list(sys.path)
try:
    sys.path.insert(0, str(ROOT / "scripts/workshops/big-data/spark"))
    import livy_candidate_verify as verify
finally:
    sys.path[:] = old_path


class CandidateVerificationTests(unittest.TestCase):
    def setUp(self):
        role = ROOT / "roles/big_data_spark_runtime"
        self.defaults = yaml.safe_load((role / "defaults/main.yml").read_text())
        env = Environment(loader=FileSystemLoader(str(role / "templates")),
                          undefined=StrictUndefined, trim_blocks=True,
                          lstrip_blocks=True)
        env.filters["bool"] = to_bool
        template = env.get_template("compose.yaml.j2")
        settings = dict(self.defaults)
        settings.update(
            big_data_spark_worker_count=1,
            big_data_spark_client_enabled=True,
            big_data_spark_client_bind_ip="192.0.2.10")
        self.baseline = yaml.safe_load(template.render(**settings))
        settings.update(
            big_data_livy_enabled=True,
            big_data_livy_access_enabled=True,
            big_data_livy_assets_host_path=verify.ROOT + "/livy-transition")
        self.candidate = yaml.safe_load(template.render(**settings))
        self.files = {name: ("trusted " + name).encode() for name in verify.FILES}
        self.reviewed = {name: value for name, value in self.files.items()
                         if name != verify.ARCHIVE}

    def check(self):
        return verify.verify_staging_inputs(
            self.files, reviewed_text_files=self.reviewed,
            baseline_config=self.baseline, candidate_config=self.candidate)

    def digest_matches(self):
        return patch.object(verify.hashlib, "sha512", return_value=
            SimpleNamespace(hexdigest=lambda: verify.ARCHIVE_SHA512))

    def test_embedded_release_lock_matches_repository_defaults(self):
        self.assertEqual(verify.ARCHIVE_SHA512,
                         self.defaults["big_data_livy_archive_sha512"])
        self.assertEqual(verify.LIVY_IMAGE, self.defaults["big_data_livy_image"])

    def test_valid_reviewed_inputs_pass_without_mutation(self):
        before = deepcopy((self.files, self.reviewed,
                           self.baseline, self.candidate))
        with self.digest_matches() as digest:
            self.check()
        digest.assert_called_once_with(self.files[verify.ARCHIVE])
        self.assertEqual((self.files, self.reviewed,
                          self.baseline, self.candidate), before)

    def test_real_unlocked_archive_is_refused(self):
        with self.assertRaisesRegex(ValueError, "release lock"):
            self.check()

    def test_changed_text_asset_is_refused_before_archive_verification(self):
        self.files["livy-transition/livy.conf"] = b"changed"
        with self.digest_matches() as digest:
            with self.assertRaisesRegex(ValueError, "reviewed rendering"):
                self.check()
            digest.assert_not_called()

    def test_each_shared_service_change_is_refused(self):
        for service in verify.SHARED:
            with self.subTest(service=service):
                candidate = deepcopy(self.candidate)
                candidate["services"][service]["cpus"] = 99
                with self.assertRaisesRegex(ValueError, "service definition differs"):
                    verify.verify_compose_preservation(self.baseline, candidate)

    def test_second_worker_or_missing_direct_identity_is_refused(self):
        for service in ("spark-worker-2", "spark-client"):
            with self.subTest(service=service):
                baseline = deepcopy(self.baseline)
                if service == "spark-worker-2":
                    baseline["services"][service] = {}
                else:
                    del baseline["services"][service]
                with self.assertRaises(ValueError):
                    verify.verify_compose_preservation(baseline, self.candidate)

    def test_network_change_is_refused(self):
        candidate = deepcopy(self.candidate)
        candidate["networks"]["spark-private"]["internal"] = False
        with self.assertRaisesRegex(ValueError, "network definitions"):
            verify.verify_compose_preservation(self.baseline, candidate)

    def test_unisolated_context_or_published_rest_endpoint_is_refused(self):
        for change in ("context", "ports"):
            with self.subTest(change=change):
                candidate = deepcopy(self.candidate)
                livy = candidate["services"]["spark-livy"]
                if change == "context":
                    livy["build"]["context"] = verify.ROOT + "/livy-build"
                else:
                    livy["ports"] = ["8998:8998"]
                with self.assertRaises(ValueError):
                    verify.verify_compose_preservation(self.baseline, candidate)

    def test_gateway_endpoint_or_profile_change_is_refused(self):
        for field, value in (("ports", ["3333:2222"]), ("profiles", [])):
            with self.subTest(field=field):
                candidate = deepcopy(self.candidate)
                candidate["services"]["spark-livy-access"][field] = value
                with self.assertRaises(ValueError):
                    verify.verify_compose_preservation(self.baseline, candidate)


if __name__ == "__main__":
    unittest.main()
