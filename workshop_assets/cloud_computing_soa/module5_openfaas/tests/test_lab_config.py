"""Offline configuration tests; no network or platform validation."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / "helpers"))
from lab_config import ConfigurationError, load_config


class ConfigurationTests(unittest.TestCase):
    """Check valid configuration and fail-closed input handling."""

    def setUp(self):
        """Prepare synthetic routes; no test contacts these hosts."""
        self.template = json.loads(
            (MODULE / "config/lab.example.json").read_text(encoding="utf-8")
        )
        self.config = copy.deepcopy(self.template)
        self.config.update(
            live_test_enabled=True,
            gateway_url="https://gateway.example.test/openfaas",
            monitoring_url="https://monitoring.example.test",
            registry_repository="registry.example.test:5000/group-01",
        )
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "lab.local.json"

    def load(self, config, require_live=True):
        """Write temporary JSON and invoke the loader without networking."""
        self.path.write_text(json.dumps(config), encoding="utf-8")
        return load_config(self.path, require_live=require_live)

    def test_valid_configuration(self):
        self.assertEqual(self.load(self.config), self.config)

    def test_template_is_offline_only(self):
        self.assertEqual(self.load(self.template, False), self.template)
        with self.assertRaisesRegex(ConfigurationError, "Live execution is disabled"):
            self.load(self.template)

    def test_placeholder_routes_are_rejected(self):
        for field, value in (
            ("gateway_url", "https://gateway.example.invalid"),
            ("monitoring_url", "https://monitoring.example.invalid"),
            ("registry_repository", "registry.example.invalid/group-01"),
        ):
            with self.subTest(field=field):
                config = copy.deepcopy(self.config)
                config[field] = value
                with self.assertRaises(ConfigurationError):
                    self.load(config)

    def test_unsafe_routes_are_rejected(self):
        for value in (
            "http://gateway.example.test",
            "https://user:password@gateway.example.test",
            "https://gateway.example.test?token=secret",
            "https://gateway.example.test#fragment",
            "https://gateway.example.test:99999",
            "https://gateway.example.test/with space",
        ):
            with self.subTest(value=value):
                config = copy.deepcopy(self.config)
                config["gateway_url"] = value
                with self.assertRaises(ConfigurationError):
                    self.load(config)

    def test_unknown_fields_are_rejected_without_echoing_secrets(self):
        config = copy.deepcopy(self.config)
        config["password"] = "secret-that-must-not-be-printed"
        with self.assertRaises(ConfigurationError) as caught:
            self.load(config)
        self.assertNotIn(config["password"], str(caught.exception))

    def test_schema_and_flag_types_are_strict(self):
        for field, value in (
            ("schema_version", True),
            ("schema_version", 2),
            ("live_test_enabled", "true"),
        ):
            with self.subTest(field=field, value=value):
                config = copy.deepcopy(self.config)
                config[field] = value
                with self.assertRaises(ConfigurationError):
                    self.load(config)

    def test_function_names_are_scoped_distinct_and_bounded(self):
        for value in (
            "other-group-greeting",
            "group-01-UPPERCASE",
            "group-01-" + "a" * 64,
            self.config["functions"]["weather"],
        ):
            with self.subTest(value=value):
                config = copy.deepcopy(self.config)
                config["functions"]["greeting"] = value
                with self.assertRaises(ConfigurationError):
                    self.load(config)

    def test_mutable_or_invalid_image_tags_are_rejected(self):
        for value in ("latest", "LATEST", "", "v1;echo unsafe"):
            with self.subTest(value=value):
                config = copy.deepcopy(self.config)
                config["image_tag"] = value
                with self.assertRaises(ConfigurationError):
                    self.load(config)

    def test_traffic_limits_are_enforced(self):
        for field, value in (
            ("requests", 101),
            ("requests", True),
            ("requests", 1.5),
            ("interval_seconds", 0),
            ("interval_seconds", float("nan")),
            ("concurrency", 2),
        ):
            with self.subTest(field=field, value=value):
                config = copy.deepcopy(self.config)
                config["load"][field] = value
                with self.assertRaises(ConfigurationError):
                    self.load(config)

    def test_timeouts_are_bounded(self):
        for field, value in (
            ("request_timeout_seconds", 0),
            ("request_timeout_seconds", 31),
            ("readiness_timeout_seconds", 301),
            ("readiness_timeout_seconds", True),
        ):
            with self.subTest(field=field, value=value):
                config = copy.deepcopy(self.config)
                config[field] = value
                with self.assertRaises(ConfigurationError):
                    self.load(config)

    def test_invalid_json_has_a_clear_error(self):
        self.path.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(ConfigurationError, "Cannot read valid"):
            load_config(self.path)

    def test_missing_file_has_a_clear_error(self):
        with self.assertRaisesRegex(ConfigurationError, "Cannot read valid"):
            load_config(self.path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
