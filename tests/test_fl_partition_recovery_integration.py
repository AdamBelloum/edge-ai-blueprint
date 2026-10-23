"""Offline FL preparation tests: synthetic data, fake Ansible, no network."""
import csv
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts/workshops/federated-learning"

FAKE_COMMAND = r'''#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import sys

name = Path(sys.argv[0]).name
if name == "readiness-python":
    name = "readiness"
args = sys.argv[1:]
event = {"type": name, "args": args}
status = 0
if name == "ansible-playbook":
    def argument(flag):
        return args[args.index(flag) + 1]
    values = json.loads(argument("--extra-vars"))
    assert argument("--tags") == "fl_partition_data"
    assert argument("-i") == os.environ["WORKSHOP_INVENTORY"]
    assert values["workshop_worker_group"] == os.environ["WORKSHOP_WORKER_GROUP"]
    assert values["fl_workshop_client_hosts"] == json.loads(os.environ["EXPECTED_WORKERS"])
    assert values["fl_silo_runtime_root"] == os.environ["WORKSHOP_RUNTIME_ROOT"]
    output = Path(values["fl_data_root"]) / "partitions"
    manifest_path = output / "partition-manifest.json"
    raw = manifest_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == os.environ["PARTITION_MANIFEST_SHA256"]
    manifest = json.loads(raw)
    assert manifest["groups"] == len(values["fl_workshop_client_hosts"])
    for group, entry in manifest["partitions"].items():
        data = (output / group / "train.csv").read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    event.update(type="stage", variables=values)
    status = int(os.environ.get("STAGE_STATUS", "0"))
elif name == "cohort":
    status = int(os.environ.get("COHORT_STATUS", "0"))
elif name == "readiness":
    phase = "prerequisite" if "--skip-participant-mapping" in args else "participant"
    event["phase"] = phase
    key = "PREREQUISITE_STATUS" if phase == "prerequisite" else "PARTICIPANT_STATUS"
    status = int(os.environ.get(key, "0"))
elif name != "flower":
    raise SystemExit("Unexpected fake command: " + name)

with Path(os.environ["EVENT_LOG"]).open("a") as handle:
    handle.write(json.dumps(event) + "\n")
sys.exit(status)
'''


class PreparationRecoveryWiringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / "repository"
        self.script_dir = self.root / "scripts/workshops/federated-learning"
        self.script_dir.mkdir(parents=True)
        for name in (
            "prepare-workshop.sh", "verify_fl_partition_recovery.py",
            "prepare_fl_partitions.py",
        ):
            shutil.copyfile(SCRIPTS / name, self.script_dir / name)
        playbook = self.root / "playbooks/fl-workshop-stage-partitions.yml"
        playbook.parent.mkdir()
        shutil.copyfile(ROOT / "playbooks/fl-workshop-stage-partitions.yml", playbook)
        self.inventory = self.root / "inventory.ini"
        self.inventory.write_text("# Offline fixture: never used by real Ansible.\n")
        self.release = self.root / "release.env"
        self.release.write_text("# Immutable release fixture.\n")
        self.tmp = self.root / "tmp"
        self.tmp.mkdir()
        self.bin = self.root / "fake-bin"
        self.bin.mkdir()
        for name in ("ansible-playbook", "cohort", "flower", "readiness"):
            command = self.bin / name
            command.write_text(FAKE_COMMAND)
            command.chmod(0o755)
        readiness_impl = self.bin / "readiness-python"
        readiness_impl.write_text(FAKE_COMMAND)
        (self.bin / "readiness").write_text("\n".join((
            "#!/usr/bin/env bash",
            "exec python3 " + shlex.quote(str(readiness_impl)) + ' "$@"',
            "",
        )))
        self.events_path = self.root / "events.jsonl"
        self.source = self.root / "data/source/train.csv"
        self.source.parent.mkdir(parents=True)
        with self.source.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("image", "label"))
            for label in ("class_a", "class_b"):
                for index in range(12):
                    writer.writerow((f"{label}_{index}.png", label))
        result = subprocess.run(
            [sys.executable, str(self.script_dir / "prepare_fl_partitions.py"),
             "--data-root", str(self.root / "data"),
             "--groups", "2", "--seed", "42"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = self.root / "data/partitions/partition-manifest.json"
        self.manifest_bytes = manifest.read_bytes()
        self.checksum = hashlib.sha256(self.manifest_bytes).hexdigest()
        self.evidence = self.root / "data/fl-recovery-manifests" / (self.checksum + ".json")
        self.evidence.parent.mkdir()
        self.evidence.write_bytes(self.manifest_bytes)
        shutil.rmtree(self.root / "data/partitions")

    def data_snapshot(self):
        return {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in (self.root / "data").rglob("*") if path.is_file()
        }

    def run_preparation(self, workers=None, group="tier2_workers", **statuses):
        workers = workers if workers is not None else ["worker_z", "worker_a"]
        self.events_path.write_text("")
        before = self.data_snapshot()
        release_before = self.release.read_bytes()
        environment = os.environ.copy()
        for key in ("STAGE_STATUS", "COHORT_STATUS", "PREREQUISITE_STATUS", "PARTICIPANT_STATUS"):
            environment.pop(key, None)
        environment.update({
            "PATH": str(self.bin) + os.pathsep + environment.get("PATH", ""),
            "SCRIPT_DIR": str(self.script_dir),
            "COHORT_WORKFLOW": str(self.bin / "cohort"),
            "FLOWER_MANAGER": str(self.bin / "flower"),
            "WORKSHOP_READINESS_CHECKER": str(self.bin / "readiness"),
            "WORKSHOP_INVENTORY": str(self.inventory),
            "WORKSHOP_WORKER_GROUP": group,
            "WORKSHOP_RUNTIME_ROOT": "/srv/offline-fixture/fl-runtime",
            "PARTITION_MANIFEST_SHA256": self.checksum,
            "EXPECTED_WORKERS": json.dumps(workers),
            "EVENT_LOG": str(self.events_path),
            "TMPDIR": str(self.tmp),
        })
        environment.update({key: str(value) for key, value in statuses.items()})
        ordered = " ".join(shlex.quote(worker) for worker in workers)
        runner = r'''
set -euo pipefail
source "$SCRIPT_DIR/prepare-workshop.sh"
die() { printf '%s\n' "$*" >&2; exit 2; }
print_heading() { :; }
record_event() {
  python3 -c 'import json,sys; from pathlib import Path; p=Path(sys.argv[1]); f=p.open("a"); f.write(json.dumps({"type":sys.argv[2],"args":sys.argv[3:]})+"\n"); f.close()' "$EVENT_LOG" "$@"
}
ensure_workshop_activation_allowed() { record_event activation "$@"; }
publish_prepared_fl_cohort() { record_event publish "$@"; }
# Stub destructive workspace cleanup; retain publication in lifecycle assertions.
start_new_cohort() { publish_prepared_fl_cohort "$1"; }
resolve_participant_workers() {
  WORKSHOP_WORKERS=(__ORDERED_WORKERS__)
  WORKSHOP_GROUP_IDS=(group_01 group_02)
}
# Conditional callers disable automatic errexit inside called functions.
if prepare_federated_learning_workshop beginner; then
  exit 0
else
  status=$?
  exit "$status"
fi
'''.replace("__ORDERED_WORKERS__", ordered)
        result = subprocess.run(
            ["bash", "-c", runner], env=environment,
            capture_output=True, text=True, timeout=60,
        )
        events = [json.loads(line) for line in self.events_path.read_text().splitlines()]
        self.assertEqual(self.data_snapshot(), before, "Preparation changed local source/evidence")
        self.assertEqual(self.release.read_bytes(), release_before)
        self.assertEqual(list(self.tmp.iterdir()), [], "Temporary candidate directories leaked")
        return result, events

    def assert_no_stage_or_publication(self, events):
        self.assertFalse(any(event["type"] in ("stage", "readiness", "publish") for event in events))
        self.assertFalse(any(event["type"] == "flower" and event["args"][0] == "restart" for event in events))

    def test_success_preserves_inventory_order_and_lifecycle_order(self):
        for group in ("tier1_agents", "tier2_workers"):
            with self.subTest(group=group):
                result, events = self.run_preparation(group=group)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual([event["type"] for event in events], [
                    "cohort", "activation", "flower", "stage",
                    "readiness", "publish", "readiness", "flower",
                ])
                self.assertEqual(events[0]["args"], ["require-complete"])
                self.assertEqual(events[2]["args"], ["stop"])
                self.assertEqual(events[3]["variables"]["fl_workshop_client_hosts"], ["worker_z", "worker_a"])
                self.assertEqual(events[4]["phase"], "prerequisite")
                self.assertEqual(events[5]["args"], ["beginner"])
                self.assertEqual(events[6]["phase"], "participant")
                self.assertEqual(events[7]["args"], ["restart", "--defaults"])
                self.assertFalse((self.root / "data/partitions").exists())

    def test_existing_manifest_fallback_works_without_local_csv_partitions(self):
        self.evidence.unlink()
        manifest = self.root / "data/partitions/partition-manifest.json"
        manifest.parent.mkdir()
        manifest.write_bytes(self.manifest_bytes)
        result, events = self.run_preparation()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(event["type"] == "stage" for event in events))

    def test_missing_evidence_blocks_staging_and_publication(self):
        self.evidence.unlink()
        result, events = self.run_preparation()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("manifest evidence is missing", result.stderr)
        self.assert_no_stage_or_publication(events)

    def test_altered_evidence_blocks_staging_and_publication(self):
        self.evidence.write_bytes(self.manifest_bytes + b"\n")
        result, events = self.run_preparation()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("evidence checksum mismatch", result.stderr)
        self.assert_no_stage_or_publication(events)

    def test_changed_worker_count_blocks_staging_and_publication(self):
        result, events = self.run_preparation(workers=["worker_z", "worker_a", "worker_b"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("worker count differs", result.stderr)
        self.assert_no_stage_or_publication(events)

    def test_changed_source_blocks_staging_and_publication(self):
        with self.source.open("ab") as handle:
            handle.write(b"changed.png,class_a\n")
        result, events = self.run_preparation()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("canonical source checksum differs", result.stderr)
        self.assert_no_stage_or_publication(events)

    def test_staging_failure_preserves_status_and_blocks_publication(self):
        result, events = self.run_preparation(STAGE_STATUS=23)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertTrue(any(event["type"] == "stage" for event in events))
        self.assertFalse(any(event["type"] in ("readiness", "publish") for event in events))
        self.assertFalse(any(event["type"] == "flower" and event["args"][0] == "restart" for event in events))

    def test_incomplete_cohort_blocks_preparation_in_conditional_caller(self):
        result, events = self.run_preparation(COHORT_STATUS=13)
        self.assertEqual(result.returncode, 13, result.stderr)
        self.assertEqual([event["type"] for event in events], ["cohort"])

    def test_prerequisite_failure_blocks_publication_in_conditional_caller(self):
        result, events = self.run_preparation(PREREQUISITE_STATUS=7)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertFalse(any(event["type"] == "publish" for event in events))
        self.assertFalse(any(event["type"] == "flower" and event["args"][0] == "restart" for event in events))

    def test_participant_readiness_failure_blocks_restart_in_conditional_caller(self):
        result, events = self.run_preparation(PARTICIPANT_STATUS=9)
        self.assertEqual(result.returncode, 9, result.stderr)
        self.assertTrue(any(event["type"] == "publish" for event in events))
        self.assertFalse(any(event["type"] == "flower" and event["args"][0] == "restart" for event in events))


if __name__ == "__main__":
    unittest.main(verbosity=2)
