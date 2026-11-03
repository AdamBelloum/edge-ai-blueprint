"""Fake commands only: never contacts a Docker daemon."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HELPERS = Path(__file__).resolve().parents[1] / 'scripts/workshops/big-data/spark'
sys.path.insert(0, str(HELPERS))
import livy_transition_docker as adapter


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.stdout = ''
        self.docker = adapter.TransitionDocker(read_inputs=lambda: {}, run=self.fake_run,
                                                sleep=lambda _: None)

    def fake_run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return SimpleNamespace(stdout=self.stdout)

    def fresh(self, *, stop=None, services=None, existing=None):
        return {'stop_client_id': stop,
                'start_services': ['spark-livy', 'spark-livy-access'] if services is None else services,
                'existing_start_service_ids': {} if existing is None else existing}

    def test_fixed_local_daemon_and_environment_isolation(self):
        with patch.dict('os.environ', {'DOCKER_HOST': 'tcp://wrong:2375',
                                      'COMPOSE_FILE': '/wrong', 'DOCKER_CONTEXT': 'wrong'}):
            self.docker.command('info')
        argv, options = self.calls[0]
        self.assertEqual(argv[:3], ['docker', '--host', 'unix:///var/run/docker.sock'])
        self.assertNotIn('DOCKER_HOST', options['env'])
        self.assertNotIn('DOCKER_CONTEXT', options['env'])
        self.assertNotIn('COMPOSE_FILE', options['env'])
        self.assertTrue(options['check'])
        self.assertLessEqual(options['timeout'], 120)

    def test_compose_normalization_is_stdin_and_has_explicit_profiles(self):
        self.docker.compose(b'services: {}', 'config', '--format', 'json')
        argv, options = self.calls[0]
        self.assertIn('--project-directory', argv)
        self.assertIn('--env-file', argv)
        self.assertEqual(argv.count('--profile'), 2)
        self.assertEqual(options['input'], 'services: {}')
        self.assertEqual(argv[-5:], ['--file', '-', 'config', '--format', 'json'])

    def test_configuration_hashes_are_exact_and_complete(self):
        def hash_run(argv, **kwargs):
            self.calls.append((argv, kwargs))
            output = (self.stdout if '--hash' in argv else
                      json.dumps({'services': {'spark-livy': {}}}))
            return SimpleNamespace(stdout=output)
        self.docker.run = hash_run
        self.stdout = 'spark-livy ' + 'a' * 64 + '\n'
        self.assertEqual(self.docker.hashes(b'x', {'spark-livy'}), {'spark-livy': 'a' * 64})
        for invalid in ('', 'spark-livy invalid',
                        'spark-master ' + 'a' * 64,
                        self.stdout + self.stdout):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.stdout = invalid
                self.docker.hashes(b'x', {'spark-livy'})

    def test_no_deps_hash_matches_started_livy_without_changing_shared_services(self):
        # A deterministic fake hash models dependency-sensitive Compose.
        # This is not an implementation of Docker Compose's hash algorithm.
        services = {
            'spark-master': {'image': adapter.CLIENT_IMAGE, 'cpus': 0.5},
            'spark-worker-1': {
                'image': adapter.CLIENT_IMAGE,
                'depends_on': {'spark-master': {'condition': 'service_started'}},
            },
            'spark-client': {
                'image': adapter.PARTICIPANT_IMAGE,
                'depends_on': {'spark-master': {'condition': 'service_started'}},
            },
            'spark-livy': {
                'image': adapter.LIVY_IMAGE,
                'depends_on': {'spark-master': {'condition': 'service_started'}},
                'build': {'context': '/reviewed/livy-build'},
                'environment': {'LIVY_SERVER_JAVA_OPTS': '-Xms128m -Xmx512m'},
                'mem_limit': '2g',
            },
            'spark-livy-access': {
                'image': adapter.PARTICIPANT_IMAGE,
                'depends_on': {'spark-livy': {'condition': 'service_started'}},
                'ports': ['145.100.135.172:2222:2222'],
            },
        }
        original = json.dumps({'services': services}, sort_keys=True)
        effective_documents = []

        def fake_hash(value):
            return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

        def dependency_sensitive_compose(argv, **kwargs):
            self.calls.append((argv, kwargs))
            self.assertEqual(argv[:3], adapter.PREFIX)
            self.assertEqual(argv[3], 'compose')
            self.assertIn('config', argv)
            if '--hash' in argv:
                effective = json.loads(kwargs['input'])
                effective_documents.append(effective)
                output = '\n'.join(
                    name + ' ' + fake_hash(value)
                    for name, value in effective['services'].items()
                )
            else:
                output = original
            return SimpleNamespace(stdout=output)

        self.docker.run = dependency_sensitive_compose
        result = self.docker.hashes(original.encode(), set(services))
        self.assertEqual(len(self.calls), 2)
        effective = effective_documents[0]['services']
        for name in adapter.STARTABLE:
            expected = dict(services[name])
            retained = {dependency: options
                        for dependency, options in expected['depends_on'].items()
                        if dependency in adapter.STARTABLE}
            if retained:
                expected['depends_on'] = retained
            else:
                expected.pop('depends_on')
            self.assertEqual(effective[name], expected)
            self.assertEqual(result[name], fake_hash(expected))
        self.assertNotEqual(result['spark-livy'], fake_hash(services['spark-livy']))
        self.assertEqual(result['spark-livy-access'],
                         fake_hash(services['spark-livy-access']))
        for name in set(services) - adapter.STARTABLE:
            self.assertEqual(effective[name], services[name])
            self.assertEqual(result[name], fake_hash(services[name]))
        self.assertEqual(original, json.dumps({'services': services}, sort_keys=True))

    def test_livy_hash_retains_internal_dependency_options_and_filters_external_dependencies(self):
        internal = {'condition': 'service_started', 'required': True, 'restart': False}
        source = {'services': {
            'spark-master': {'image': adapter.CLIENT_IMAGE},
            'spark-livy': {
                'image': adapter.LIVY_IMAGE,
                'depends_on': {'spark-master': {'condition': 'service_started'}},
            },
            'spark-livy-access': {
                'image': adapter.PARTICIPANT_IMAGE,
                'depends_on': {
                    'spark-livy': internal,
                    'spark-master': {'condition': 'service_started'},
                },
            },
        }}
        captured = []
        def compose(argv, **kwargs):
            self.calls.append((argv, kwargs))
            self.assertEqual(argv[:3], adapter.PREFIX)
            self.assertIn('config', argv)
            if '--hash' in argv:
                captured.append(json.loads(kwargs['input']))
                return SimpleNamespace(stdout='\n'.join(
                    name + ' ' + str(index) * 64
                    for index, name in enumerate(source['services'], 1)
                ))
            return SimpleNamespace(stdout=json.dumps(source))
        self.docker.run = compose
        self.docker.hashes(json.dumps(source).encode(), set(source['services']))
        effective = captured[0]['services']
        self.assertNotIn('depends_on', effective['spark-livy'])
        self.assertEqual(effective['spark-livy-access']['depends_on'],
                         {'spark-livy': internal})
        self.assertEqual(effective['spark-master'], source['services']['spark-master'])
        self.assertIn('spark-master', source['services']['spark-livy-access']['depends_on'])
        self.assertEqual(len(self.calls), 2)

    def test_invalid_livy_dependency_mapping_refuses_before_hash_command(self):
        for dependencies in ('spark-master', ['spark-master'], None):
            with self.subTest(dependencies=dependencies):
                self.calls.clear()
                self.stdout = json.dumps({'services': {
                    'spark-livy': {'depends_on': dependencies},
                }})
                with self.assertRaises(ValueError):
                    self.docker.hashes(b'x', {'spark-livy'})
                self.assertEqual(len(self.calls), 1)
                self.assertNotIn('--hash', self.calls[0][0])

    def test_no_deps_hash_accepts_services_with_no_dependencies(self):
        source = {'services': {'spark-livy': {'image': adapter.LIVY_IMAGE}}}
        captured = []
        def compose(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if '--hash' in argv:
                captured.append(json.loads(kwargs['input']))
                return SimpleNamespace(stdout='spark-livy ' + 'a' * 64)
            return SimpleNamespace(stdout=json.dumps(source))
        self.docker.run = compose
        self.assertEqual(self.docker.hashes(json.dumps(source).encode(), {'spark-livy'}),
                         {'spark-livy': 'a' * 64})
        self.assertEqual(captured, [source])

    def test_invalid_resolved_service_contract_refuses_before_hash_command(self):
        for resolved in ([], {}, {'services': []},
                         {'services': {'spark-master': {}}},
                         {'services': {'spark-livy': 'invalid'}}):
            with self.subTest(resolved=resolved):
                self.calls.clear()
                self.stdout = json.dumps(resolved)
                with self.assertRaises(ValueError):
                    self.docker.hashes(b'x', {'spark-livy'})
                self.assertEqual(len(self.calls), 1)
                self.assertNotIn('--hash', self.calls[0][0])

    def test_startup_is_only_explicit_services_without_recreation_dependencies_build_or_pull(self):
        self.docker.observe = lambda: {}
        with patch.object(adapter, 'plan', return_value=self.fresh()):
            self.docker.start_services(('spark-livy', 'spark-livy-access'), {})
        argv = self.calls[0][0]
        self.assertIn(adapter.TRANSITION_CONFIG, argv)
        for flag in ('--no-recreate', '--no-deps', '--no-build'):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index('--pull') + 1], 'never')
        self.assertEqual(argv[-2:], ['spark-livy', 'spark-livy-access'])
        self.assertTrue(self.docker.wait_for_new_livy)

    def test_shared_service_and_duplicate_start_are_refused_before_commands(self):
        for services in (('spark-master',), ('spark-worker-1',),
                         ('spark-livy', 'spark-livy'), (), ('spark-client',)):
            with self.subTest(services=services), self.assertRaises(ValueError):
                self.docker.start_services(services, {})
        self.assertEqual(self.calls, [])

    def test_active_direct_access_and_changed_existing_id_refuse_start(self):
        self.docker.observe = lambda: {}
        cases = [self.fresh(stop='a' * 64),
                 self.fresh(existing={'spark-livy': 'b' * 64})]
        for fresh in cases:
            with patch.object(adapter, 'plan', return_value=fresh), self.assertRaises(ValueError):
                self.docker.start_services(('spark-livy', 'spark-livy-access'), {})
        self.assertEqual(self.calls, [])

    def test_stop_is_by_exact_fresh_direct_client_id(self):
        self.docker.observe = lambda: {}
        with patch.object(adapter, 'plan', return_value=self.fresh(stop='a' * 64)):
            self.docker.stop_client('a' * 64)
        self.assertEqual(self.calls[0][0][-5:], ['container', 'stop', '--time', '15', 'a' * 64])
        self.calls.clear()
        with patch.object(adapter, 'plan', return_value=self.fresh(stop='b' * 64)), self.assertRaises(ValueError):
            self.docker.stop_client('a' * 64)
        self.assertEqual(self.calls, [])

    def test_invalid_container_id_never_reaches_commands(self):
        with self.assertRaises(ValueError):
            self.docker.stop_client('short')
        self.assertEqual(self.calls, [])

    def test_rest_retry_is_bounded_and_only_after_startup(self):
        failures = []
        def failing(*args):
            failures.append(args)
            raise subprocess.CalledProcessError(1, ['fake'])
        self.docker.command = failing
        with self.assertRaises(subprocess.CalledProcessError):
            self.docker.inventory('a' * 64)
        self.assertEqual(len(failures), 1)
        failures.clear()
        self.docker.wait_for_new_livy = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.docker.inventory('a' * 64)
        self.assertEqual(len(failures), 15)
        self.assertTrue(all(args[0] == 'exec' for args in failures))

    def test_malformed_rest_json_is_not_retried(self):
        self.docker.wait_for_new_livy = True
        self.stdout = 'not-json'
        with self.assertRaises(json.JSONDecodeError):
            self.docker.inventory('a' * 64)
        self.assertEqual(len(self.calls), 1)

    def test_all_images_require_local_reviewed_platform_and_livy_provenance(self):
        dockerfile = b'reviewed Dockerfile\n'
        records = {}
        for index, reference in enumerate(sorted(set(adapter.REFERENCES.values())), 1):
            records[reference] = {
                'Id': 'sha256:' + str(index) * 64, 'Os': 'linux', 'Architecture': 'amd64',
                'RepoDigests': [reference], 'RepoTags': [reference], 'Config': {},
            }
        records[adapter.LIVY_IMAGE]['Config'] = {
            'User': '185:0', 'Cmd': ['/opt/livy/bin/livy-server'],
            'Env': ['LIVY_SERVER_START_MODE=foreground'],
            'Labels': {
                'org.digitafrica.livy.archive-sha512': adapter.ARCHIVE_SHA512,
                'org.digitafrica.livy.dockerfile-sha512': hashlib.sha512(dockerfile).hexdigest(),
                'org.digitafrica.livy.spark-base': adapter.CLIENT_IMAGE,
            },
        }
        self.docker.command = lambda *args: json.dumps([records[args[-1]]])
        self.assertEqual(set(self.docker.image_ids(dockerfile)), set(adapter.REFERENCES.values()))
        records[adapter.LIVY_IMAGE]['Config']['Labels']['org.digitafrica.livy.archive-sha512'] = 'wrong'
        with self.assertRaises(ValueError):
            self.docker.image_ids(dockerfile)
        records[adapter.PARTICIPANT_IMAGE]['Architecture'] = 'arm64'
        with self.assertRaises(ValueError):
            self.docker.image_ids(dockerfile)

    def test_invalid_reader_contract_refuses_before_docker(self):
        with self.assertRaises(ValueError):
            self.docker.observe()
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
