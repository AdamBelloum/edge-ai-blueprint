"""Staging verification tests: fixture credentials and mocked Kubernetes only."""
import base64
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/workshops/big-data/spark/stage_credential_secrets.py'
spec = importlib.util.spec_from_file_location('spark_staging_verify_fixture', SOURCE)
staging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(staging)


class StagedCredentialsVerifyTests(unittest.TestCase):
    def setUp(self):
        credentials = {}
        for name in ('login_key', 'known_hosts'):
            payload = ('fixture-' + name).encode()
            credentials[name] = {
                'content_b64': base64.b64encode(payload).decode(),
                'sha256': hashlib.sha256(payload).hexdigest(),
            }
        request = {
            'group_id': 'group_01', 'worker': 'worker-1',
            'worker_node': 'actual-worker-node', 'operation': 'apply',
            'credentials': credentials,
        }
        self.request = {
            'namespace': 'digitafrica', 'operation': 'verify',
            'requests': [request], 'helper_code': '# fixture reconciler\n',
        }
        secret = staging.desired_secret('digitafrica', request)
        self.secret_key = ('secret', secret['metadata']['name'])
        self.helper_key = ('configmap', staging.HELPER)
        self.resources = {
            self.secret_key: secret,
            self.helper_key: {
                'metadata': {'labels': deepcopy(staging.MANAGED)},
                'data': {'reconcile_credentials.py': self.request['helper_code']},
            },
        }

    def run_stage(self):
        def existing(namespace, kind, name):
            self.assertEqual(namespace, 'digitafrica')
            return deepcopy(self.resources.get((kind, name)))
        with patch.object(staging, 'existing', side_effect=existing), \
             patch.object(staging, 'kubectl', return_value='') as writes:
            result = staging.stage(deepcopy(self.request))
            return result, writes.call_args_list

    def assert_blocked_without_write(self, reason):
        with patch.object(staging, 'existing', side_effect=lambda ns, kind, name: deepcopy(self.resources.get((kind, name)))), \
             patch.object(staging, 'kubectl') as writes:
            with self.assertRaisesRegex(staging.Blocked, reason):
                staging.stage(deepcopy(self.request))
            writes.assert_not_called()

    def test_matching_staged_credentials_are_verified_without_writes(self):
        before = deepcopy(self.resources)
        result, writes = self.run_stage()
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['helper_action'], 'preserve')
        self.assertEqual(result['groups'][0]['action'], 'preserve')
        self.assertEqual(writes, [])
        self.assertEqual(self.resources, before)

    def test_missing_secret_blocks_instead_of_creating(self):
        del self.resources[self.secret_key]
        self.assert_blocked_without_write('group_credentials_not_staged')

    def test_missing_helper_blocks_instead_of_creating(self):
        del self.resources[self.helper_key]
        self.assert_blocked_without_write('credential_helper_not_staged_current')

    def test_outdated_helper_blocks_instead_of_updating(self):
        self.resources[self.helper_key]['data']['reconcile_credentials.py'] = '# old code'
        self.assert_blocked_without_write('credential_helper_not_staged_current')

    def test_conflicting_secret_blocks_without_writes(self):
        self.resources[self.secret_key]['data']['request.json'] = 'Y29uZmxpY3Q='
        self.assert_blocked_without_write('existing_secret_credential_conflict')

    def test_foreign_secret_blocks_without_writes(self):
        self.resources[self.secret_key]['metadata']['labels']['digitafrica.eu/managed-by'] = 'other'
        self.assert_blocked_without_write('existing_secret_ownership_conflict')

    def test_one_missing_group_blocks_all_verification(self):
        second = deepcopy(self.request['requests'][0])
        second.update(group_id='group_02', worker='worker-2', worker_node='other-node')
        self.request['requests'].append(second)
        self.assert_blocked_without_write('group_credentials_not_staged')

    def test_existing_plan_behavior_is_preserved(self):
        self.request['operation'] = 'plan'
        self.resources.clear()
        result, writes = self.run_stage()
        self.assertEqual(result['status'], 'planned')
        self.assertEqual(result['helper_action'], 'create')
        self.assertEqual(result['groups'][0]['action'], 'create')
        self.assertEqual(writes, [])

    def test_existing_apply_behavior_is_preserved(self):
        self.request['operation'] = 'apply'
        self.resources.clear()
        result, writes = self.run_stage()
        self.assertEqual(result['status'], 'staged')
        self.assertEqual(len(writes), 2)
        self.assertTrue(all(call.args[0] == ['create', '-f', '-'] for call in writes))


if __name__ == '__main__':
    unittest.main()
