"""Mocked image cleanup tests: never invokes Docker."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from test_spark_teardown_docker import adapter

path = Path(__file__).resolve().parents[1] / "scripts/workshops/big-data/spark/teardown_images.py"
spec = importlib.util.spec_from_file_location("teardown_images", path)
module = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"teardown_docker": adapter}):
    spec.loader.exec_module(module)


def metadata(reference, identifier):
    value = {"Id": identifier, "Os": "linux", "Architecture": "amd64"}
    if reference == module.SPARK:
        value["RepoDigests"] = [module.SPARK]
    else:
        value.update(RepoTags=[module.LIVY], Config={
            "User": "185:0", "Cmd": ["/opt/livy/bin/livy-server"],
            "Env": ["LIVY_SERVER_START_MODE=foreground"],
            "Labels": {
                "org.digitafrica.livy.archive-sha512": module.ARCHIVE_SHA512,
                "org.digitafrica.livy.dockerfile-sha512": module.DOCKERFILE_SHA512,
                "org.digitafrica.livy.spark-base": module.SPARK,
            },
        })
    return value


class FakeDocker:
    def __init__(self):
        self.records = {module.SPARK: metadata(module.SPARK, "sha256:" + "a" * 64),
                        module.LIVY: metadata(module.LIVY, "sha256:" + "b" * 64)}
        self.commands, self.busy = [], set()
        self.fail_remove = False
        self.keep_removed = False
        self.bad_listing = None

    def command(self, *args):
        self.commands.append(args)
        if args[:2] == ("image", "ls"):
            if self.bad_listing is not None:
                return self.bad_listing
            rows = [{"Repository": "unrelated/platform", "Tag": "latest", "Digest": "<none>",
                     "ID": "sha256:" + "c" * 64}]
            for reference, info in self.records.items():
                if reference == module.SPARK:
                    rows.append({"Repository": "apache/spark", "Tag": "<none>",
                                 "Digest": reference.split("@", 1)[1], "ID": info["Id"]})
                else:
                    rows.append({"Repository": "digitafrica/livy", "Tag": reference.split(":", 1)[1],
                                 "Digest": "<none>", "ID": info["Id"]})
            return "\n".join(json.dumps(row) for row in rows)
        if args[:2] == ("image", "inspect"):
            return json.dumps([self.records[args[2]]])
        if args[:2] == ("container", "ls"):
            return "d" * 64 if args[-1].split("=", 1)[1] in self.busy else ""
        if args[:2] == ("image", "rm"):
            if self.fail_remove:
                raise RuntimeError("Docker removal failed")
            if not self.keep_removed:
                del self.records[args[2]]
            return ""
        raise AssertionError("Unexpected Docker command: " + repr(args))

    def removals(self):
        return [args for args in self.commands if args[:2] == ("image", "rm")]


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.docker = FakeDocker()

    def test_verified_images_removed_livy_before_spark_without_force_or_prune(self):
        self.assertEqual(module.ImageCleanup(self.docker).remove(), [module.LIVY, module.SPARK])
        self.assertEqual(self.docker.removals(), [("image", "rm", module.LIVY), ("image", "rm", module.SPARK)])
        self.assertFalse(any("--force" in cmd or "prune" in cmd for cmd in self.docker.commands))
        self.assertFalse(any("unrelated/platform" in cmd for cmd in self.docker.commands))

    def test_missing_images_are_idempotently_clean(self):
        self.docker.records.clear()
        self.assertEqual(module.ImageCleanup(self.docker).remove(), [])
        self.assertEqual(self.docker.removals(), [])

    def test_spark_only_or_livy_only(self):
        for reference in module.ORDER:
            docker = FakeDocker()
            docker.records = {reference: docker.records[reference]}
            with self.subTest(reference=reference):
                self.assertEqual(module.ImageCleanup(docker).remove(), [reference])

    def test_platform_or_invalid_id_mismatch_blocks_removal(self):
        for field, value in (("Os", "windows"), ("Architecture", "arm64"), ("Id", "short")):
            docker = FakeDocker()
            docker.records[module.SPARK][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                module.ImageCleanup(docker)
            self.assertEqual(docker.removals(), [])

    def test_livy_provenance_or_runtime_mismatch_blocks_removal(self):
        mutations = [
            lambda c: c.update(User="root"),
            lambda c: c.update(Cmd=["sh"]),
            lambda c: c.update(Env=[]),
            lambda c: c["Labels"].update({"org.digitafrica.livy.archive-sha512": "wrong"}),
            lambda c: c["Labels"].update({"org.digitafrica.livy.dockerfile-sha512": "wrong"}),
            lambda c: c["Labels"].update({"org.digitafrica.livy.spark-base": "wrong"}),
        ]
        for mutate in mutations:
            docker = FakeDocker()
            mutate(docker.records[module.LIVY]["Config"])
            with self.assertRaises(ValueError):
                module.ImageCleanup(docker)
            self.assertEqual(docker.removals(), [])

    def test_repo_digest_and_tag_metadata_must_match(self):
        for reference, field in ((module.SPARK, "RepoDigests"), (module.LIVY, "RepoTags")):
            docker = FakeDocker()
            docker.records[reference][field] = []
            with self.assertRaises(ValueError):
                module.ImageCleanup(docker)
            self.assertEqual(docker.removals(), [])

    def test_retagged_or_new_image_is_refused(self):
        plan = module.ImageCleanup(self.docker)
        self.docker.records[module.LIVY]["Id"] = "sha256:" + "e" * 64
        with self.assertRaisesRegex(ValueError, "identities changed"):
            plan.remove()
        self.assertEqual(self.docker.removals(), [])

    def test_remaining_running_stopped_or_descendant_container_blocks_all_images(self):
        plan = module.ImageCleanup(self.docker)
        self.docker.busy.add(self.docker.records[module.SPARK]["Id"])
        with self.assertRaisesRegex(RuntimeError, "still used"):
            plan.remove()
        self.assertEqual(self.docker.removals(), [])
        self.assertTrue(any("--all" in cmd for cmd in self.docker.commands if cmd[:2] == ("container", "ls")))

    def test_command_failure_is_not_treated_as_absence(self):
        with patch.object(self.docker, "command", side_effect=RuntimeError("daemon unavailable")):
            with self.assertRaisesRegex(RuntimeError, "daemon unavailable"):
                module.ImageCleanup(self.docker)

    def test_malformed_listing_is_refused(self):
        for value in ("not-json", "[]"):
            docker = FakeDocker()
            docker.bad_listing = value
            with self.assertRaises(ValueError):
                module.ImageCleanup(docker)
            self.assertEqual(docker.removals(), [])

    def test_removal_failure_propagates_and_retry_can_complete(self):
        plan = module.ImageCleanup(self.docker)
        self.docker.fail_remove = True
        with self.assertRaisesRegex(RuntimeError, "removal failed"):
            plan.remove()
        self.docker.fail_remove = False
        self.assertEqual(module.ImageCleanup(self.docker).remove(), [module.LIVY, module.SPARK])

    def test_remaining_reference_fails_final_verification(self):
        plan = module.ImageCleanup(self.docker)
        self.docker.keep_removed = True
        with self.assertRaisesRegex(ValueError, "remain"):
            plan.remove()

    def test_pinned_dockerfile_hash_matches_current_reviewed_template(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "roles/big_data_spark_runtime/templates/livy.Dockerfile.j2").read_text()
        for variable, value in {"big_data_spark_image": module.SPARK,
                                "big_data_livy_archive_sha512": module.ARCHIVE_SHA512,
                                "big_data_livy_version": "0.9.0-incubating"}.items():
            text = text.replace("{{ " + variable + " }}", value)
        self.assertEqual(hashlib.sha512(text.encode()).hexdigest(), module.DOCKERFILE_SHA512)


if __name__ == "__main__":
    unittest.main(verbosity=2)
