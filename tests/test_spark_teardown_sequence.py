"""Offline sequencing tests; no Docker commands or evidence files."""
import importlib.util
from pathlib import Path
import sys
import unittest

from test_spark_teardown_validation import snapshot, validator

sys.modules["teardown_validation"] = validator
path = Path(__file__).resolve().parents[1] / (
    "scripts/workshops/big-data/spark/teardown_sequence.py"
)
spec = importlib.util.spec_from_file_location("teardown_sequence", path)
sequence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sequence)


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.events = []

    def run_sequence(self, snapshots, failure=None, evidence=()):
        snapshots = iter(snapshots)

        def save_evidence(ids):
            if failure == "evidence":
                raise RuntimeError("simulated evidence failure")
            self.events.append(("evidence", set(ids)))

        def remove_container(identifier):
            self.events.append(("container", identifier))
            if failure == "container":
                raise RuntimeError("simulated removal failure")

        def remove_network(identifier):
            self.events.append(("network", identifier))
            if failure == "network":
                raise RuntimeError("simulated network removal failure")

        return sequence.teardown(
            snapshot=lambda: next(snapshots),
            load_evidence=lambda: set(evidence),
            save_evidence=save_evidence,
            remove_container=remove_container,
            remove_network=remove_network,
        )

    def test_legacy_evidence_precedes_removal_and_clears_last(self):
        initial = snapshot(legacy=True)
        network_id = initial[1][0]["Id"]
        empty_network = snapshot(legacy=True)
        empty_network[1][0]["Containers"] = {}
        result = self.run_sequence([
            initial, ([], empty_network[1], []), ([], [], []),
        ])
        self.assertEqual(self.events[0], ("evidence", {network_id}))
        self.assertEqual(self.events[1:-2], [
            ("container", identifier)
            for identifier in sorted(c["Id"] for c in initial[0])
        ])
        self.assertEqual(self.events[-2], ("network", network_id))
        self.assertEqual(self.events[-1], ("evidence", set()))
        self.assertEqual(result["network_ids"], [network_id])

    def test_foreign_endpoint_after_container_removal_is_refused(self):
        current = snapshot()
        current[1][0]["Containers"] = {"f" * 64: {}}
        with self.assertRaisesRegex(ValueError, "Foreign"):
            self.run_sequence([snapshot(), ([], current[1], [])])
        self.assertFalse(any(kind == "network" for kind, _ in self.events))
        self.assertEqual(
            sum(kind == "evidence" for kind, _ in self.events), 1
        )

    def test_container_removal_failure_retains_evidence_and_stops(self):
        initial = snapshot(legacy=True)
        with self.assertRaisesRegex(RuntimeError, "simulated removal"):
            self.run_sequence([initial], failure="container")
        self.assertEqual(self.events, [
            ("evidence", {initial[1][0]["Id"]}),
            ("container", sorted(c["Id"] for c in initial[0])[0]),
        ])

    def test_evidence_failure_prevents_all_removal(self):
        with self.assertRaisesRegex(RuntimeError, "simulated evidence"):
            self.run_sequence([snapshot(legacy=True)], failure="evidence")
        self.assertEqual(self.events, [])

    def test_retry_removes_empty_legacy_network_with_saved_evidence(self):
        current = snapshot(legacy=True)
        current[1][0]["Containers"] = {}
        network_id = current[1][0]["Id"]
        result = self.run_sequence(
            [([], current[1], []), ([], current[1], []), ([], [], [])],
            evidence={network_id},
        )
        self.assertEqual(result["container_ids"], [])
        self.assertEqual(self.events, [
            ("evidence", {network_id}),
            ("network", network_id),
            ("evidence", set()),
        ])

    def test_network_failure_does_not_clear_retry_evidence(self):
        initial = snapshot(legacy=True)
        current = snapshot(legacy=True)
        current[1][0]["Containers"] = {}
        network_id = initial[1][0]["Id"]
        with self.assertRaisesRegex(RuntimeError, "network removal"):
            self.run_sequence(
                [initial, ([], current[1], [])], failure="network"
            )
        self.assertEqual(
            [event for event in self.events if event[0] == "evidence"],
            [("evidence", {network_id})],
        )
        self.assertEqual(self.events[-1], ("network", network_id))

    def test_replacement_network_is_not_removed(self):
        current = snapshot()
        current[1][0]["Containers"] = {}
        current[1][0]["Id"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "identity changed"):
            self.run_sequence([snapshot(), ([], current[1], [])])
        self.assertFalse(any(kind == "network" for kind, _ in self.events))

    def test_remaining_network_fails_final_verification(self):
        initial = snapshot(legacy=True)
        current = snapshot(legacy=True)
        current[1][0]["Containers"] = {}
        with self.assertRaisesRegex(ValueError, "could not be verified"):
            self.run_sequence([
                initial, ([], current[1], []), ([], current[1], []),
            ])
        self.assertEqual(
            [event for event in self.events if event[0] == "evidence"],
            [("evidence", {initial[1][0]["Id"]})],
        )

    def test_already_clean_is_successful(self):
        result = self.run_sequence([([], [], [])] * 3)
        self.assertEqual(result, {"container_ids": [], "network_ids": []})
        self.assertEqual(self.events, [
            ("evidence", set()), ("evidence", set()),
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
