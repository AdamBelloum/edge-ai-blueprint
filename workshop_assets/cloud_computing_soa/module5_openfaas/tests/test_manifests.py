"""Offline manifest tests; no CLI, template download or platform access."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / "helpers"))
import manifests
from lab_config import ConfigurationError


class ManifestTests(unittest.TestCase):
    """Verify candidate contents and safe local file handling."""

    def setUp(self):
        self.config = MODULE / "config/lab.example.json"
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_owned_function_manifests_match_configuration(self):
        config = json.loads(self.config.read_text(encoding="utf-8"))
        for key in ("greeting", "weather"):
            with self.subTest(function=key):
                result = json.loads(manifests.render_manifest(self.config, key))
                name = config["functions"][key]
                self.assertEqual(result["version"], "1.0")
                self.assertEqual(result["provider"], {
                    "name": "openfaas",
                    "gateway": config["gateway_url"],
                })
                self.assertEqual(result["functions"], {
                    name: {
                        "lang": "node22",
                        "handler": str(MODULE / "examples" / key),
                        "image": (
                            config["registry_repository"] + "/"
                            + name + ":" + config["image_tag"]
                        ),
                    }
                })

    def test_prepared_and_unknown_functions_are_excluded(self):
        for key in ("prepared_greeting", "unknown"):
            with self.subTest(function=key):
                with self.assertRaisesRegex(ValueError, "Only owned"):
                    manifests.render_manifest(self.config, key)

    def test_new_manifest_is_written_as_rendered(self):
        output = self.root / "greeting.local.json"
        result = manifests.write_manifest(self.config, "greeting", output)
        self.assertEqual(result, output)
        self.assertEqual(
            output.read_text(encoding="utf-8"),
            manifests.render_manifest(self.config, "greeting"),
        )

    def test_existing_file_is_preserved(self):
        output = self.root / "greeting.local.json"
        output.write_text("original contents\n", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            manifests.write_manifest(self.config, "greeting", output)
        self.assertEqual(
            output.read_text(encoding="utf-8"), "original contents\n"
        )

    def test_missing_sources_prevent_output_creation(self):
        source = self.root / "examples" / "greeting"
        source.mkdir(parents=True)
        for missing in ("handler.js", "package.json"):
            with self.subTest(missing=missing):
                for filename in ("handler.js", "package.json"):
                    path = source / filename
                    if path.exists():
                        path.unlink()
                    if filename != missing:
                        path.write_text("", encoding="utf-8")
                output = self.root / (missing + ".local.json")
                with patch.object(manifests, "MODULE", self.root):
                    with self.assertRaisesRegex(ValueError, "source files"):
                        manifests.write_manifest(self.config, "greeting", output)
                self.assertFalse(output.exists())

    def test_invalid_configuration_prevents_output_creation(self):
        config = self.root / "invalid.local.json"
        config.write_text("{}", encoding="utf-8")
        output = self.root / "greeting.local.json"
        with self.assertRaises(ConfigurationError):
            manifests.write_manifest(config, "greeting", output)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
