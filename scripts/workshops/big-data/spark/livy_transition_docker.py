"""Host-local Docker operations for the guarded warm transition.

No executable entry point. The live caller must provide protected, freshly read
baseline/candidate Compose and independently reviewed Dockerfile bytes, explicit
maintenance acknowledgement, shared locking and protected evidence persistence.
Snapshots are not atomic: other administrator writers must be excluded.
Gateway probes here do NOT verify a participant SSH tunnel or REST computation.
"""
import hashlib
import json
import os
import re
import subprocess
import time

from livy_candidate_compose import MAX_COMPOSE_BYTES
from livy_candidate_verify import ARCHIVE_SHA512, verify_compose_preservation
from livy_transition import ALLOWED, LIVY_IMAGE, REFERENCES, plan_transition, running
from livy_transition_execute import execute_transition
from teardown_docker import Docker, PREFIX, full_id
from teardown_validation import (
    ACCESS_NETWORK, CLIENT_IMAGE, NETWORK, PARTICIPANT_IMAGE, PROJECT,
    ROOT, TRANSITION_CONFIG, require, validate_snapshot,
)

COMPOSE = [
    "compose", "--project-name", PROJECT, "--project-directory", ROOT,
    "--env-file", "/dev/null", "--profile", "participant-direct",
    "--profile", "participant-livy",
]
STARTABLE = {"spark-livy", "spark-livy-access"}
SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
HASH = re.compile(r"[0-9a-f]{64}")

MASTER_PROBE = r"""
import json, urllib.request
with urllib.request.urlopen('http://spark-master:8080/json/', timeout=3) as response:
    raw = response.read(1048577)
assert len(raw) <= 1048576
print(json.dumps(json.loads(raw)))
"""
INVENTORY_PROBE = r"""
import json, urllib.request
result = {}
for kind in ('sessions', 'batches'):
    with urllib.request.urlopen('http://127.0.0.1:8998/' + kind + '?from=0&size=1', timeout=3) as response:
        raw = response.read(1048577)
    assert len(raw) <= 1048576
    result[kind] = json.loads(raw)
print(json.dumps(result))
"""
HEAP_PROBE = r"""
import pathlib
commands = []
for process in pathlib.Path('/proc').iterdir():
    if not process.name.isdigit():
        continue
    try:
        args = (process / 'cmdline').read_bytes().split(b'\0')
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    if args and (args[0] == b'java' or args[0].endswith(b'/java')):
        commands.append(args)
assert any([a for a in args if a.startswith(b'-Xmx')] == [b'-Xmx512m']
           and [a for a in args if a.startswith(b'-Xms')] == [b'-Xms128m']
           for args in commands)
print('Livy server heap verified.')
"""
GATEWAY_PROBE = r"""
import json, socket, urllib.request
with socket.create_connection(('127.0.0.1', 2222), timeout=3) as sock:
    sock.settimeout(3)
    assert sock.recv(255).startswith(b'SSH-2.0-')
for kind in ('sessions', 'batches'):
    with urllib.request.urlopen('http://spark-livy:8998/' + kind + '?from=0&size=1', timeout=3) as response:
        raw = response.read(1048577)
    assert len(raw) <= 1048576
    data = json.loads(raw)
    assert data.get('total') == 0 and data.get('sessions') == []
print('Gateway SSH listener and internal Livy route verified; participant tunnel not tested.')
"""


def plan(observation):
    return plan_transition(
        observation['containers'], observation['networks'], observation['volumes'],
        observation['master_status'], image_ids=observation['image_ids'],
        expected_hashes=observation['expected_hashes'],
        livy_inventory=observation.get('livy_inventory'),
    )


class TransitionDocker(Docker):
    def __init__(self, *, read_inputs, run=subprocess.run, sleep=time.sleep):
        super().__init__(run=run)
        require(callable(read_inputs), 'A protected fresh-input reader is required.')
        self.read_inputs = read_inputs
        self.sleep = sleep
        self.wait_for_new_livy = False

    def command(self, *arguments, input=None):
        # Prevent inherited contexts or Compose variables from selecting another
        # daemon, project, profile or environment file. Never use shell=True.
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('DOCKER_', 'COMPOSE_'))}
        env['COMPOSE_DISABLE_ENV_FILE'] = '1'
        result = self.run(
            PREFIX + list(arguments), input=input, check=True,
            text=True, capture_output=True, timeout=120, env=env,
        )
        require(isinstance(result.stdout, str), 'Invalid Docker command output.')
        return result.stdout

    def compose(self, document, *arguments):
        require(isinstance(document, bytes) and 0 < len(document) <= MAX_COMPOSE_BYTES,
                'A bounded protected Compose document is required.')
        return self.command(*COMPOSE, '--file', '-', *arguments,
                            input=document.decode('utf-8'))

    def hashes(self, document, services):
        # For the two-service Livy startup with --no-deps, Compose retains
        # dependencies within the explicit startup set and excludes external
        # Spark dependencies. Derive hashes from this reviewed effective config;
        # never learn an expected hash from an existing container's labels.
        resolved = json.loads(self.compose(document, 'config', '--format', 'json'))
        require(isinstance(resolved, dict)
                and isinstance(resolved.get('services'), dict)
                and set(resolved['services']) == set(services)
                and all(isinstance(value, dict)
                        for value in resolved['services'].values()),
                'Exact resolved service configurations are required for hashing.')
        for service in STARTABLE & set(resolved['services']):
            configuration = resolved['services'][service]
            dependencies = configuration.get('depends_on', {})
            require(isinstance(dependencies, dict),
                    'Resolved Livy startup dependencies must be a mapping.')
            retained = {name: options for name, options in dependencies.items()
                        if name in STARTABLE}
            if retained:
                configuration['depends_on'] = retained
            else:
                configuration.pop('depends_on', None)
        effective = json.dumps(resolved, sort_keys=True).encode('utf-8')
        result = {}
        for line in self.compose(effective, 'config', '--hash', '*').splitlines():
            fields = line.split()
            require(len(fields) == 2 and fields[0] in services
                    and HASH.fullmatch(fields[1]) and fields[0] not in result,
                    'Invalid or ambiguous proposed Compose configuration hashes.')
            result[fields[0]] = fields[1]
        require(set(result) == set(services), 'Missing proposed service configuration hashes.')
        return result

    def image_ids(self, dockerfile):
        require(isinstance(dockerfile, bytes) and 0 < len(dockerfile) <= 65536,
                'An independently reviewed bounded Livy Dockerfile is required.')
        result = {}
        for reference in sorted(set(REFERENCES.values())):
            records = json.loads(self.command('image', 'inspect', reference))
            require(isinstance(records, list) and len(records) == 1
                    and isinstance(records[0], dict), 'Ambiguous reviewed image inspection.')
            image = records[0]
            identifier = image.get('Id')
            require(isinstance(identifier, str) and SHA256.fullmatch(identifier)
                    and image.get('Os') == 'linux' and image.get('Architecture') == 'amd64',
                    'Reviewed image platform or identity mismatch.')
            if reference == CLIENT_IMAGE:
                require(reference in (image.get('RepoDigests') or []),
                        'Pinned Spark digest is not present on the inspected image.')
            else:
                require(reference in (image.get('RepoTags') or []),
                        'Reviewed local image tag differs.')
            if reference == LIVY_IMAGE:
                config = image.get('Config') or {}
                labels = config.get('Labels') or {}
                require(config.get('User') == '185:0'
                        and config.get('Cmd') == ['/opt/livy/bin/livy-server']
                        and 'LIVY_SERVER_START_MODE=foreground' in (config.get('Env') or [])
                        and labels.get('org.digitafrica.livy.archive-sha512') == ARCHIVE_SHA512
                        and labels.get('org.digitafrica.livy.dockerfile-sha512')
                            == hashlib.sha512(dockerfile).hexdigest()
                        and labels.get('org.digitafrica.livy.spark-base') == CLIENT_IMAGE,
                        'Built Livy image failed reviewed provenance verification.')
            result[reference] = identifier
        return result

    def inventory(self, identifier):
        # Retry only the read-only REST probe immediately after an explicit
        # startup. No stop/start/build/pull operations are retried.
        attempts = 15 if self.wait_for_new_livy else 1
        for attempt in range(attempts):
            try:
                value = json.loads(self.command('exec', full_id(identifier),
                                                'python3', '-c', INVENTORY_PROBE))
                self.wait_for_new_livy = False
                return value
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                if attempt + 1 == attempts:
                    raise
                self.sleep(2)

    def observe(self):
        inputs = self.read_inputs()
        require(isinstance(inputs, dict) and set(inputs) == {'baseline', 'candidate', 'dockerfile'},
                'Exact protected transition input documents are required.')
        baseline = json.loads(self.compose(inputs['baseline'], 'config', '--format', 'json'))
        candidate = json.loads(self.compose(inputs['candidate'], 'config', '--format', 'json'))
        verify_compose_preservation(baseline, candidate)
        hashes = self.hashes(inputs['candidate'], candidate['services'])
        images = self.image_ids(inputs['dockerfile'])
        daemon = self.daemon_id()
        containers, networks, volumes = self.snapshot()
        validate_snapshot(containers, networks, volumes, allow_livy_transition=True)
        require({n['Name'] for n in networks} == {NETWORK, ACCESS_NETWORK},
                'Both existing project networks must be present; creation is prohibited.')
        services = {}
        for container in containers:
            service = (container['Config'].get('Labels') or {}).get('com.docker.compose.service')
            require(service in ALLOWED, 'Unexpected project or organiser-client service.')
            require(container['Config'].get('Image') == REFERENCES[service]
                    and container.get('Image') == images[REFERENCES[service]]
                    and container['Config']['Labels'].get('com.docker.compose.config-hash')
                        == hashes[service], 'Existing service image or configuration differs.')
            running(container)  # Reject paused/restarting states before executing probes.
            services[service] = container
        require({'spark-master', 'spark-worker-1'} <= set(services)
                and running(services['spark-master']) and running(services['spark-worker-1']),
                'Existing master and single worker must already be running.')
        master = json.loads(self.command('exec', full_id(services['spark-master']['Id']),
                                         'python3', '-c', MASTER_PROBE))
        inventory = None
        if 'spark-livy' in services and running(services['spark-livy']):
            inventory = self.inventory(services['spark-livy']['Id'])
        require(self.daemon_id() == daemon, 'Docker daemon changed during observation.')
        observation = {
            'containers': containers, 'networks': networks, 'volumes': volumes,
            'master_status': master, 'image_ids': images, 'expected_hashes': hashes,
            'livy_inventory': inventory, 'daemon_id': daemon,
        }
        plan(observation)
        return observation

    def stop_client(self, identifier):
        full_id(identifier)
        fresh = plan(self.observe())
        require(fresh['stop_client_id'] == identifier,
                'Only the freshly validated direct client may be stopped.')
        self.command('container', 'stop', '--time', '15', identifier)

    def start_services(self, services, existing_ids):
        require(isinstance(services, tuple) and bool(services)
                and len(services) == len(set(services)) and set(services) <= STARTABLE,
                'Only explicitly missing Livy/access services may be started.')
        require(isinstance(existing_ids, dict) and set(existing_ids) <= set(services),
                'Invalid existing start-service identities.')
        for identifier in existing_ids.values():
            full_id(identifier)
        fresh = plan(self.observe())
        require(fresh['stop_client_id'] is None
                and tuple(fresh['start_services']) == services
                and fresh['existing_start_service_ids'] == existing_ids,
                'Fresh startup plan differs or direct access is still running.')
        self.command(*COMPOSE, '--file', TRANSITION_CONFIG, 'up', '--detach',
                     '--no-deps', '--no-recreate', '--no-build', '--pull', 'never',
                     *services)
        if 'spark-livy' in services:
            self.wait_for_new_livy = True

    def verify_ready(self):
        observation = self.observe()
        final = plan(observation)
        require(final['stop_client_id'] is None and not final['start_services'],
                'Warm transition has not completed.')
        services = {c['Config']['Labels']['com.docker.compose.service']: c
                    for c in observation['containers']}
        livy = services['spark-livy']
        require(livy['HostConfig'].get('Memory') == 2147483648
                and not livy['HostConfig'].get('PortBindings')
                and livy['HostConfig'].get('NetworkMode') != 'host',
                'Livy memory or private endpoint configuration differs.')
        self.command('exec', full_id(livy['Id']), 'python3', '-c', HEAP_PROBE)
        self.command('exec', full_id(services['spark-livy-access']['Id']),
                     'python3', '-c', GATEWAY_PROBE)


def transition_with_docker(*, maintenance_window, submission_lock, read_inputs,
                           record_event, run=subprocess.run, sleep=time.sleep):
    docker = TransitionDocker(read_inputs=read_inputs, run=run, sleep=sleep)
    return execute_transition(
        maintenance_window=maintenance_window, submission_lock=submission_lock,
        observe=docker.observe, stop_client=docker.stop_client,
        start_services=docker.start_services, verify_ready=docker.verify_ready,
        record_event=record_event,
    )
