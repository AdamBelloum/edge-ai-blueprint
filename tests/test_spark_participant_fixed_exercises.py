import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/workshops/big-data/spark/participant/fixed_exercises.py'
spec = importlib.util.spec_from_file_location('spark_participant_fixed_exercises', SOURCE)
contract = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = contract
spec.loader.exec_module(contract)

PROTOCOL_SOURCE = SOURCE.parent.parent / 'submission/protocol.py'
protocol_spec = importlib.util.spec_from_file_location(
    'spark_submission_protocol_approval_integration', PROTOCOL_SOURCE)
protocol = importlib.util.module_from_spec(protocol_spec)
sys.modules[protocol_spec.name] = protocol
protocol_spec.loader.exec_module(protocol)




class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'source'
        self.approval = self.base / 'approval'
        self.source.mkdir(mode=0o755)
        self.approval.mkdir(mode=0o755)
        self.contents = {'direct': b'print("approved direct")\n', 'livy': b'print("approved livy")\n'}
        self.install()
        # Filesystem tests run as the ordinary test user. Production constants
        # remain root:root; only these private test fixtures substitute ownership.
        for name, value in (('_ROOT_UID', os.getuid()), ('_ROOT_GID', os.getgid())):
            mocked = patch.object(contract, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        mocked = patch.object(contract, '_open_protected_directory', side_effect=self.open_fixture)
        mocked.start()
        self.addCleanup(mocked.stop)

    def open_fixture(self, path):
        if path == contract._SOURCE_ROOT:
            directory = self.source
        elif path == contract._APPROVAL_ROOT:
            directory = self.approval
        else:
            raise AssertionError('Unexpected protected root')
        return os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def install(self):
        hashes = {}
        for action, content in self.contents.items():
            name = contract._FILES[action][0]
            target = self.source / name
            target.write_bytes(content)
            target.chmod(0o644)
            hashes[action] = hashlib.sha256(content).hexdigest()
        self.manifest = self.approval / 'approved-exercises.json'
        self.manifest.write_text(json.dumps({'version': 1, 'exercises': hashes}))
        self.manifest.chmod(0o644)

    def test_both_approved_snapshots_and_fixed_preview_names(self):
        for action, preview in (('direct', 'filtered_preview.csv'), ('livy', '02_filtered_preview.csv')):
            result = contract.load_approved_exercise(action)
            self.assertEqual(result.source, self.contents[action])
            self.assertEqual(result.preview_name, preview)
            self.assertEqual(result.source_sha256, hashlib.sha256(result.source).hexdigest())

    def test_source_is_compiled_never_executed(self):
        marker = self.base / 'must-not-exist'
        self.contents['direct'] = ('from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n').encode()
        self.install()
        contract.load_approved_exercise('direct')
        self.assertFalse(marker.exists())

    def test_changed_source_rejected_without_reapproval(self):
        (self.source / '01_spark_basics.py').write_bytes(b'print("changed")\n')
        with self.assertRaises(contract.ApprovalError):
            contract.load_approved_exercise('direct')

    def test_symlink_and_hardlink_source_rejected(self):
        target = self.source / '01_spark_basics.py'
        target.unlink()
        other = self.base / 'other.py'
        other.write_bytes(self.contents['direct'])
        target.symlink_to(other)
        with self.assertRaises(contract.ApprovalError):
            contract.load_approved_exercise('direct')
        target.unlink()
        os.link(other, target)
        with self.assertRaises(contract.ApprovalError):
            contract.load_approved_exercise('direct')

    def test_writable_source_manifest_and_directory_rejected(self):
        for target in (self.source / '01_spark_basics.py', self.manifest, self.source):
            with self.subTest(target=target.name):
                old_mode = stat.S_IMODE(target.stat().st_mode)
                target.chmod(old_mode | stat.S_IWGRP)
                try:
                    with self.assertRaises(contract.ApprovalError):
                        contract.load_approved_exercise('direct')
                finally:
                    target.chmod(old_mode)

    def test_missing_manifest_fails_closed(self):
        self.manifest.unlink()
        with self.assertRaises(contract.ApprovalError):
            contract.load_approved_exercise('direct')

    def test_oversized_and_invalid_python_source_rejected(self):
        for source in (b'x' * (contract.MAX_SOURCE_BYTES + 1), b'def :\n', b'\xff'):
            with self.subTest(length=len(source)):
                self.contents['direct'] = source
                self.install()
                with self.assertRaises(contract.ApprovalError):
                    contract.load_approved_exercise('direct')

    def test_manifest_schema_and_hashes_fail_closed(self):
        valid = {'version': 1, 'exercises': {'direct': 'a' * 64, 'livy': 'b' * 64}}
        invalid = [
            {}, {'version': True, 'exercises': valid['exercises']},
            {'version': 1, 'exercises': {'direct': 'a' * 64}},
            {'version': 1, 'exercises': {'direct': 'A' * 64, 'livy': 'b' * 64}},
            dict(valid, path='/tmp/evil.py'),
        ]
        for value in invalid:
            with self.assertRaises(contract.ApprovalError):
                contract.parse_approval_manifest(json.dumps(value).encode())
        with self.assertRaises(contract.ApprovalError):
            contract.parse_approval_manifest(b'{"version":1,"version":1,"exercises":{}}')

    def test_unknown_action_rejected_before_filesystem_access(self):
        with self.assertRaises(contract.ApprovalError):
            contract.load_approved_exercise('../direct')

    def test_wrong_owner_rejected(self):
        with patch.object(contract, '_ROOT_UID', os.getuid() + 1):
            with self.assertRaises(contract.ApprovalError):
                contract.load_approved_exercise('direct')

    def test_wire_and_approval_filename_mappings_agree(self):
        expected = {action: names[0] for action, names in contract._FILES.items()}
        self.assertEqual(dict(protocol.EXERCISE_FILES), expected)

    def test_validated_run_frames_load_only_approved_sources(self):
        for exercise in ('direct', 'livy'):
            with self.subTest(exercise=exercise):
                frame = protocol.encode_run_request(exercise)
                request = protocol.decode_request(frame)
                self.assertEqual(request.operation, 'run')
                approved = contract.load_approved_exercise(request.exercise)
                self.assertEqual(approved.action, exercise)
                self.assertEqual(approved.source_name, protocol.EXERCISE_FILES[exercise])
                self.assertEqual(approved.source, self.contents[exercise])

    def test_status_frame_does_not_select_an_exercise(self):
        request = protocol.decode_request(protocol.encode_status_request('a' * 32))
        self.assertEqual(request.operation, 'status')
        self.assertIsNone(request.exercise)
        with self.assertRaises(contract.ApprovalError):
            contract.load_approved_exercise(request.exercise)


if __name__ == '__main__':
    unittest.main()
