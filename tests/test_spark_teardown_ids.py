"""Offline validation of IDs used by the future teardown runner."""
import unittest
from test_spark_teardown_validation import snapshot, validator


class RemovalIdTests(unittest.TestCase):
    def test_invalid_container_ids_are_refused(self):
        for identifier in (None, 123, "", "abc123", "--force",
                           "g" * 64, "A" * 64):
            with self.subTest(identifier=identifier):
                containers, networks, volumes = snapshot()
                containers[0]["Id"] = identifier
                with self.assertRaisesRegex(ValueError, "full container ID"):
                    validator.validate_snapshot(containers, networks, volumes)

    def test_invalid_network_ids_are_refused(self):
        for identifier in (None, 123, "", "abc123", "--force",
                           "g" * 64, "A" * 64):
            with self.subTest(identifier=identifier):
                containers, networks, volumes = snapshot()
                networks[0]["Id"] = identifier
                with self.assertRaisesRegex(ValueError, "full network ID"):
                    validator.validate_snapshot(containers, networks, volumes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
