"""Offline execution tests using the real transition planner and fake adapters."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import sys
import unittest

from test_spark_livy_transition import fixture
from test_spark_teardown_validation import validator as v

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                       'scripts/workshops/big-data/spark'))
from livy_transition_execute import execute_transition
import livy_transition


class FakeRuntime:
    def __init__(self):
        state, status, images, hashes = fixture()
        hashes.update({'spark-livy': '6' * 64, 'spark-livy-access': '5' * 64})
        self.data = dict(containers=state[0], networks=state[1], volumes=state[2],
                         master_status=status, image_ids=images, expected_hashes=hashes,
                         daemon_id='offline-daemon', livy_inventory={
                             kind: {'total': 0, 'sessions': []}
                             for kind in ('sessions', 'batches')})
        self.operations = []
        self.events = []
        self.fenced = self.locked = False
        self.observations = 0
        self.hook = None
        self.stop_noop = self.start_error = self.readiness_error = False
        self.partial_start = False

    @contextmanager
    def fence(self):
        self.fenced = True
        try:
            yield
        finally:
            self.fenced = False

    @contextmanager
    def lock(self):
        if not self.fenced:
            raise AssertionError('Fence must precede lock')
        self.locked = True
        try:
            yield
        finally:
            self.locked = False

    def observe(self):
        if not (self.fenced and self.locked):
            raise AssertionError('Observation outside fence/lock')
        self.observations += 1
        if self.hook:
            self.hook(self)
        return deepcopy(self.data)

    def stop(self, identifier):
        self.operations.append(('stop', identifier))
        if not self.stop_noop:
            next(c for c in self.data['containers'] if c['Id'] == identifier)['State']['Running'] = False

    def add_service(self, service):
        if service == 'spark-livy-access':
            container = deepcopy(fixture(gateway=True)[0][0][-1])
            container['Id'] = '5' * 64
        else:
            container = deepcopy(self.data['containers'][0])
            container['Id'] = '6' * 64
            container['Config']['Image'] = livy_transition.LIVY_IMAGE
            container['Image'] = self.data['image_ids'][livy_transition.LIVY_IMAGE]
            container['Mounts'] = [dict(Type='bind', RW=False, Source=s, Destination=d)
                                   for s, d in sorted({v.DATA_MOUNT} | v.LIVY_MOUNTS)]
        container['Name'] = '/' + v.PROJECT + '-' + service + '-1'
        container['Config']['Labels'].update({
            'com.docker.compose.service': service,
            'com.docker.compose.config-hash': self.data['expected_hashes'][service]})
        container['State'] = dict(Running=True, Paused=False, Restarting=False)
        self.data['containers'].append(container)
        for network in self.data['networks']:
            attachment = container['NetworkSettings']['Networks'].get(network['Name'])
            if attachment is not None:
                attachment['NetworkID'] = network['Id']
                network['Containers'][container['Id']] = {}

    def start(self, services, existing_ids):
        self.operations.append(('start', services, existing_ids))
        if self.start_error:
            raise RuntimeError('Synthetic startup failure')
        for service in services:
            self.add_service(service)
            if self.partial_start:
                break

    def ready(self):
        self.operations.append(('ready',))
        if self.readiness_error:
            raise RuntimeError('Synthetic readiness failure')

    def run(self):
        return execute_transition(participant_fence=self.fence,
                                  submission_lock=self.lock, observe=self.observe,
                                  stop_client=self.stop, start_services=self.start,
                                  verify_ready=self.ready,
                                  record_event=lambda name, data: self.events.append((name, data)))


class ExecutionTests(unittest.TestCase):
    def test_success_preserves_existing_containers_and_stops_only_direct_client(self):
        runtime = FakeRuntime()
        before = {c['Id'] for c in runtime.data['containers']}
        result = runtime.run()
        self.assertEqual([op[0] for op in runtime.operations], ['stop', 'start', 'ready'])
        self.assertEqual(runtime.operations[1][1], ('spark-livy', 'spark-livy-access'))
        self.assertTrue(before <= {c['Id'] for c in runtime.data['containers']})
        self.assertEqual(result['status'], 'runtime-transition-verified')
        self.assertFalse(runtime.fenced or runtime.locked)

    def test_active_application_refuses_before_operations(self):
        runtime = FakeRuntime()
        runtime.data['master_status']['activeapps'] = ['busy']
        with self.assertRaises(ValueError):
            runtime.run()
        self.assertEqual(runtime.operations, [])
        self.assertFalse(runtime.fenced or runtime.locked)

    def test_fresh_activity_before_stop_refuses(self):
        runtime = FakeRuntime()
        def hook(current):
            if current.observations == 2:
                current.data['master_status']['waitingapps'] = ['queued']
        runtime.hook = hook
        with self.assertRaises(ValueError):
            runtime.run()
        self.assertEqual(runtime.operations, [])

    def test_changed_daemon_refuses_before_stop(self):
        runtime = FakeRuntime()
        def hook(current):
            if current.observations == 2:
                current.data['daemon_id'] = 'other-daemon'
        runtime.hook = hook
        with self.assertRaises(ValueError):
            runtime.run()
        self.assertEqual(runtime.operations, [])

    def test_unconfirmed_stop_prevents_start(self):
        runtime = FakeRuntime()
        runtime.stop_noop = True
        with self.assertRaises(ValueError):
            runtime.run()
        self.assertEqual([op[0] for op in runtime.operations], ['stop'])

    def test_start_failure_does_not_restart_direct_client_or_continue(self):
        runtime = FakeRuntime()
        runtime.start_error = True
        with self.assertRaises(RuntimeError):
            runtime.run()
        self.assertEqual([op[0] for op in runtime.operations], ['stop', 'start'])
        self.assertEqual(runtime.events[-1][0], 'failed')

    def test_partial_start_does_not_claim_success_or_retry_automatically(self):
        runtime = FakeRuntime()
        runtime.partial_start = True
        with self.assertRaises(ValueError):
            runtime.run()
        self.assertEqual([op[0] for op in runtime.operations], ['stop', 'start'])

    def test_readiness_failure_does_not_claim_success(self):
        runtime = FakeRuntime()
        runtime.readiness_error = True
        with self.assertRaises(RuntimeError):
            runtime.run()
        self.assertNotIn('runtime-transition-verified', [name for name, _ in runtime.events])

    def test_service_stopping_during_readiness_prevents_success(self):
        for service in ('spark-livy', 'spark-livy-access'):
            with self.subTest(service=service):
                runtime = FakeRuntime()
                original_ready = runtime.ready

                def changed_ready():
                    original_ready()
                    container = next(
                        c for c in runtime.data['containers']
                        if c['Config']['Labels']['com.docker.compose.service'] == service
                    )
                    container['State']['Running'] = False

                runtime.ready = changed_ready
                with self.assertRaises(ValueError):
                    runtime.run()
                self.assertNotIn(
                    'runtime-transition-verified',
                    [name for name, _ in runtime.events]
                )

    def test_already_transitioned_runtime_needs_no_stop_or_start(self):
        runtime = FakeRuntime()
        runtime.data['containers'][-1]['State']['Running'] = False
        runtime.add_service('spark-livy')
        runtime.add_service('spark-livy-access')
        runtime.run()
        self.assertEqual(runtime.operations, [('ready',)])


if __name__ == '__main__':
    unittest.main()
