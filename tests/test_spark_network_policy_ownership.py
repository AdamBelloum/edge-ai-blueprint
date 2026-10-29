"""Offline ownership and playbook-order tests; no Kubernetes access."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'scripts/workshops/big-data/spark/plan_network_policy_changes.py'
SPEC = importlib.util.spec_from_file_location('spark_policy_ownership', HELPER)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def policy(name='digitafrica-spark-direct-group-01', owned=True):
    return {'kind': 'NetworkPolicy', 'metadata': {
        'namespace': 'digitafrica', 'name': name,
        'labels': dict(module.MANAGED) if owned else {'owner': 'someone-else'},
    }, 'spec': {}}


def request(current=(), desired=None, action='apply'):
    return {'namespace': 'digitafrica', 'action': action,
            'current': {'kind': 'NetworkPolicyList', 'items': list(current)},
            'desired': [policy()] if desired is None else desired}


class PolicyOwnershipTests(unittest.TestCase):
    def test_missing_desired_policy_can_be_created(self):
        result = module.plan(request())
        self.assertEqual(result['create_or_update'], ['digitafrica-spark-direct-group-01'])
        self.assertEqual(result['delete'], [])

    def test_owned_desired_policy_can_be_updated(self):
        self.assertEqual(module.plan(request([policy()]))['delete'], [])

    def test_foreign_desired_name_collision_blocks(self):
        with self.assertRaisesRegex(ValueError, 'foreign_desired_policy_collision'):
            module.plan(request([policy(owned=False)]))

    def test_partial_ownership_labels_do_not_authorise_update(self):
        item = policy()
        item['metadata']['labels'].pop('digitafrica.eu/module')
        with self.assertRaises(ValueError):
            module.plan(request([item]))

    def test_unlabelled_and_foreign_legacy_policies_are_preserved(self):
        items = [policy('spark-direct-group-01-pilot', False),
                 policy('spark-direct-group-02-pilot', False)]
        items[0]['metadata'].pop('labels')
        result = module.plan(request(items))
        self.assertEqual(result['delete'], [])
        self.assertEqual(result['preserve_unverified_legacy'],
                         ['spark-direct-group-01-pilot', 'spark-direct-group-02-pilot'])

    def test_owned_stale_and_legacy_policies_can_be_deleted(self):
        result = module.plan(request([policy('old-spark-policy'), policy('spark-direct-group-01-pilot')]))
        self.assertEqual(result['delete'], ['old-spark-policy', 'spark-direct-group-01-pilot'])

    def test_remove_only_selects_owned_objects(self):
        result = module.plan(request([policy(), policy('spark-direct-group-01-pilot', False),
                                     policy('unrelated', False)], desired=[], action='remove'))
        self.assertEqual(result['delete'], ['digitafrica-spark-direct-group-01'])
        self.assertEqual(result['create_or_update'], [])

    def test_controller_owned_update_or_deletion_blocks(self):
        item = policy()
        item['metadata']['ownerReferences'] = [{'uid': 'fixture-controller'}]
        for value in (request([item]), request([item], desired=[], action='remove')):
            with self.assertRaisesRegex(ValueError, 'policy_has_controller_owner'):
                module.plan(value)

    def test_invalid_namespace_action_snapshot_and_duplicates_block(self):
        cases = [request(), request(), request(), request(), request()]
        cases[0]['namespace'] = 'Wrong_NS'
        cases[1]['action'] = 'overwrite'
        cases[2]['current'] = {'items': []}
        cases[3]['current']['items'] = [policy(), policy()]
        cases[4]['desired'].append(policy())
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.plan(value)

    def test_cross_namespace_snapshot_blocks(self):
        item = policy()
        item['metadata']['namespace'] = 'another-workshop'
        with self.assertRaises(ValueError):
            module.plan(request([item]))

    def test_remove_rejects_nonempty_desired_list(self):
        with self.assertRaises(ValueError):
            module.plan(request(action='remove'))

    def test_desired_labels_must_be_owned(self):
        with self.assertRaises(ValueError):
            module.plan(request(desired=[policy(owned=False)]))

    def test_plan_is_readonly_and_does_not_mutate_inputs(self):
        value = request([policy('old-spark-policy')], action='plan')
        before = deepcopy(value)
        result = module.plan(value)
        self.assertEqual(value, before)
        self.assertEqual(result['delete'], ['old-spark-policy'])

    def test_cli_blocks_foreign_collision_without_output_plan(self):
        result = subprocess.run([sys.executable, str(HELPER)],
            input=json.dumps(request([policy(owned=False)])), text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')

    def test_playbook_checks_ownership_before_apply_and_delete(self):
        text = (ROOT / 'playbooks/reconcile-big-data-spark-network-policy.yml').read_text()
        guard = text.index('- name: Validate ownership before planning any policy mutation')
        self.assertLess(guard, text.index('- name: Apply discovered policies'))
        self.assertLess(guard, text.index('- name: Delete stale'))
        self.assertNotIn('select(\'match\', spark_policy_legacy_pattern)', text)
        self.assertIn('preserve_unverified_legacy', text)


if __name__ == '__main__':
    unittest.main()
