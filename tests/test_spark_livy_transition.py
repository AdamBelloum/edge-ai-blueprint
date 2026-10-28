"""Offline transition-plan tests. No Docker or production filesystem access."""
from copy import deepcopy
import sys
from pathlib import Path
import unittest

from test_spark_teardown_participant_runtime import participant, CID
from test_spark_teardown_validation import validator as v
from test_spark_teardown_livy_access import livy_access

old_path = list(sys.path)
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/workshops/big-data/spark"))
    import livy_transition as transition
finally:
    sys.path[:] = old_path


def fixture(gateway=False):
    containers, networks, volumes = livy_access() if gateway else participant()
    containers = [c for c in containers if c["Config"]["Labels"]["com.docker.compose.service"]
                  in {"spark-master", "spark-worker-1", "spark-client", "spark-livy-access"}]
    ids = {c["Id"] for c in containers}
    for network in networks:
        network["Containers"] = {key: value for key, value in network["Containers"].items() if key in ids}
    images = {
        v.CLIENT_IMAGE: "sha256:" + "1" * 64,
        v.PARTICIPANT_IMAGE: "sha256:" + "f" * 64,
        transition.LIVY_IMAGE: "sha256:" + "2" * 64,
    }
    hashes = {}
    for index, container in enumerate(containers, 1):
        service = container["Config"]["Labels"]["com.docker.compose.service"]
        container["State"] = dict(Running=True, Paused=False, Restarting=False)
        container["Config"]["Image"] = transition.REFERENCES[service]
        container["Image"] = images[transition.REFERENCES[service]]
        hashes[service] = format(index, "064x")
        container["Config"]["Labels"]["com.docker.compose.config-hash"] = hashes[service]
    status = {"activeapps": [], "workers": [{"state": "ALIVE", "host": "spark-worker-1"}]}
    return (containers, networks, volumes), status, images, hashes


class TransitionPlanTests(unittest.TestCase):
    def plan(self, state, status, images, hashes, inventory=None):
        return transition.plan_transition(*state, status, image_ids=images,
                                          expected_hashes=hashes, livy_inventory=inventory)

    def test_direct_plan_stops_only_client_preserves_shared_ids_and_does_not_mutate(self):
        state, status, images, hashes = fixture()
        before = deepcopy((state, status, images, hashes))
        plan = self.plan(state, status, images, hashes)
        self.assertEqual(plan["stop_client_id"], CID)
        self.assertEqual(plan["start_services"], ["spark-livy", "spark-livy-access"])
        shared = {c["Config"]["Labels"]["com.docker.compose.service"]: c["Id"] for c in state[0]
                  if c["Config"]["Labels"]["com.docker.compose.service"] in {"spark-master", "spark-worker-1"}}
        self.assertEqual(plan["preserve_service_ids"], shared)
        self.assertEqual((state, status, images, hashes), before)

    def test_stopped_client_can_resume_without_another_stop(self):
        state, status, images, hashes = fixture()
        state[0][-1]["State"]["Running"] = False
        self.assertIsNone(self.plan(state, status, images, hashes)["stop_client_id"])

    def test_existing_gateway_is_not_restarted(self):
        state, status, images, hashes = fixture(gateway=True)
        plan = self.plan(state, status, images, hashes)
        self.assertIsNone(plan["stop_client_id"])
        self.assertEqual(plan["start_services"], ["spark-livy"])

    def test_active_queued_and_unverified_master_status_are_refused(self):
        for status in ({}, {"activeapps": ["app"]}, {"activeapps": [], "waitingapps": ["app"]}):
            with self.subTest(status=status):
                state, _, images, hashes = fixture()
                with self.assertRaises(ValueError):
                    self.plan(state, status, images, hashes)

    def test_wrong_worker_missing_worker_and_extra_worker_are_refused(self):
        for workers in ([], [{"state": "DEAD", "host": "spark-worker-1"}],
                        [{"state": "ALIVE", "host": "foreign"}],
                        [{"state": "ALIVE", "host": "spark-worker-1"}] * 2):
            with self.subTest(workers=workers):
                state, status, images, hashes = fixture()
                status["workers"] = workers
                with self.assertRaises(ValueError):
                    self.plan(state, status, images, hashes)

    def test_stopped_paused_or_restarting_shared_service_is_refused(self):
        for field, value in (("Running", False), ("Paused", True), ("Restarting", True)):
            with self.subTest(field=field):
                state, status, images, hashes = fixture()
                state[0][0]["State"][field] = value
                with self.assertRaises(ValueError):
                    self.plan(state, status, images, hashes)

    def test_image_and_staged_hash_mismatches_are_refused(self):
        for kind in ("image", "hash", "missing-image", "missing-hash"):
            with self.subTest(kind=kind):
                state, status, images, hashes = fixture()
                master = state[0][0]
                if kind == "image":
                    master["Image"] = "sha256:" + "e" * 64
                elif kind == "hash":
                    master["Config"]["Labels"]["com.docker.compose.config-hash"] = "e" * 64
                elif kind == "missing-image":
                    images.pop(transition.LIVY_IMAGE)
                else:
                    hashes.pop("spark-master")
                with self.assertRaises(ValueError):
                    self.plan(state, status, images, hashes)

    def test_invalid_gateway_cannot_be_treated_as_a_resumable_transition(self):
        state, status, images, hashes = fixture(gateway=True)
        command = state[0][-1]["Config"]["Cmd"]
        command[command.index("MaxSessions=0")] = "MaxSessions=1"
        with self.assertRaises(ValueError):
            self.plan(state, status, images, hashes)

    def test_paused_direct_client_is_refused(self):
        state, status, images, hashes = fixture()
        state[0][-1]["State"]["Paused"] = True
        with self.assertRaises(ValueError):
            self.plan(state, status, images, hashes)

    def test_cold_cluster_without_prepared_access_identity_is_refused(self):
        state, status, images, hashes = fixture()
        removed = state[0].pop()
        for network in state[1]:
            network["Containers"].pop(removed["Id"], None)
        with self.assertRaises(ValueError):
            self.plan(state, status, images, hashes)

    def test_running_livy_requires_empty_fresh_session_and_batch_inventory(self):
        state, status, images, hashes = fixture(gateway=True)
        livy = deepcopy(state[0][0])
        livy.update(Id="6" * 64, Name="/" + v.PROJECT + "-spark-livy-1", Image=images[transition.LIVY_IMAGE])
        livy["Config"]["Image"] = transition.LIVY_IMAGE
        livy["Config"]["Labels"].update({"com.docker.compose.service": "spark-livy",
                                          "com.docker.compose.config-hash": "6" * 64})
        livy["Mounts"] = [dict(Type="bind", RW=False, Source=s, Destination=d)
                          for s, d in sorted({v.DATA_MOUNT} | v.LIVY_MOUNTS)]
        state[0].append(livy)
        state[1][0]["Containers"][livy["Id"]] = {}
        hashes["spark-livy"] = "6" * 64
        for inventory in (None, {"sessions": {"total": 0, "sessions": []}},
                          {"sessions": {"total": 1, "sessions": [{}]}, "batches": {"total": 0, "sessions": []}}):
            with self.subTest(inventory=inventory):
                with self.assertRaises(ValueError):
                    self.plan(state, status, images, hashes, inventory)
        empty = {kind: {"total": 0, "sessions": []} for kind in ("sessions", "batches")}
        plan = self.plan(state, status, images, hashes, empty)
        self.assertIsNone(plan["stop_client_id"])
        self.assertEqual(plan["start_services"], [])


if __name__ == "__main__":
    unittest.main()
