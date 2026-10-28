"""Offline image and complete participant-direct reset integration tests."""
from pathlib import Path
import unittest
from test_spark_teardown_images import module as images, FakeDocker
import test_spark_teardown_participant_assets as asset_tests
import test_spark_teardown_participant_runtime as runtime_tests

class ParticipantImageTests(unittest.TestCase):
    def test_existing_image_metadata_verified_before_any_removal(self):
        mutations = [
            lambda i: i.update(RepoTags=[]),
            lambda i: i.update(Architecture="arm64"),
            lambda i: i["Config"].update(User="185:0"),
            lambda i: i["Config"].update(Cmd=["sh"]),
            lambda i: i["Config"].update(WorkingDir="/tmp"),
            lambda i: i["Config"].update(Env=[]),
            lambda i: i["Config"]["Labels"].update({"org.digitafrica.managed-by": "other"}),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                docker = FakeDocker()
                mutate(docker.records[images.SSH_CLIENT])
                with self.assertRaises(ValueError):
                    images.ImageCleanup(docker)
                self.assertEqual(docker.removals(), [])

    def test_client_retagging_and_remaining_users_block_all_images(self):
        docker = FakeDocker()
        plan = images.ImageCleanup(docker)
        docker.records[images.SSH_CLIENT]["Id"] = "sha256:" + "e" * 64
        with self.assertRaises(ValueError):
            plan.remove()
        self.assertEqual(docker.removals(), [])
        docker = FakeDocker()
        plan = images.ImageCleanup(docker)
        docker.busy.add(docker.records[images.SSH_CLIENT]["Id"])
        with self.assertRaises(RuntimeError):
            plan.remove()
        self.assertEqual(docker.removals(), [])

    def test_unrelated_image_reference_preserved(self):
        docker = FakeDocker()
        reference = "unrelated/research:keep"
        docker.records[reference] = {"Id": "sha256:" + "c" * 64}
        self.assertEqual(images.ImageCleanup(docker).remove(), list(images.ORDER))
        self.assertEqual(set(docker.records), {reference})
        self.assertFalse(any("--force" in c or "prune" in c for c in docker.commands))

    def test_service_and_image_cleanup_agree_with_assessed_reference(self):
        self.assertEqual(runtime_tests.v.PARTICIPANT_IMAGE, images.SSH_CLIENT)
        self.assertEqual(runtime_tests.v.PARTICIPANT_CMD, images.SSH_CMD)
        self.assertEqual(runtime_tests.v.OWNERSHIP, images.SSH_LABELS)
        self.assertIn(images.SSH_CLIENT, (Path(__file__).resolve().parents[1]
            / "roles/big_data_spark_runtime/defaults/main.yml").read_text())

    def fixture(self):
        fixture = asset_tests.ParticipantAssetTests(
            "test_reviewed_assets_removed_and_shared_lock_preserved")
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        return fixture

    def test_full_mocked_profile_cleanup_resources_images_then_files(self):
        fixture, resources, docker = self.fixture(), runtime_tests.Resources(True), FakeDocker()
        with fixture.assets() as assets:
            plan = images.ImageCleanup(docker)
            resources.reset()
            self.assertEqual(plan.remove(), list(images.ORDER))
            assets.remove()
        self.assertEqual(resources.snapshot(), ([], [], []))
        self.assertEqual(docker.records, {})
        self.assertEqual(list(fixture.root.iterdir()), [fixture.lock])
        fixture.assert_preserved()

    def test_image_failure_preserves_client_files_and_retry_completes(self):
        fixture, resources, docker = self.fixture(), runtime_tests.Resources(), FakeDocker()
        with fixture.assets() as assets:
            plan = images.ImageCleanup(docker)
            resources.reset()
            docker.fail_remove = True
            with self.assertRaises(RuntimeError):
                plan.remove()
            self.assertTrue((fixture.root / "client-access/login_key").exists())
            self.assertTrue((fixture.root / "client-build/Dockerfile").exists())
            fixture.assert_preserved()
            docker.fail_remove = False
            self.assertEqual(images.ImageCleanup(docker).remove(), list(images.ORDER))
            assets.remove()
        self.assertEqual(list(fixture.root.iterdir()), [fixture.lock])
        fixture.assert_preserved()

if __name__ == "__main__":
    unittest.main(verbosity=2)
