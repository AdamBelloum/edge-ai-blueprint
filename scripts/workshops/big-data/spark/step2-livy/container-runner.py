#!/usr/bin/env python3
"""Root-run organiser-only Livy test. Trusted Exercise 2 source arrives on stdin.

Requires the playbook's reviewed Spark and Livy preflight. Not a participant
endpoint or an untrusted-code sandbox. No shared services are started/stopped.
A separate non-root client joins only the existing private bridge. Evidence is
retained. Cleanup targets its unique container and returned Livy session ID.
An ambiguous POST without a returned ID is reported, never guessed away.
"""
import csv
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

IMAGE = 'apache/spark@sha256:d0f5d63bfbbffdbec08debb4911554ba671a2fa7398374db8db314d80328f576'
ROOT = Path('/opt/digitafrica/big-data/runtime/spark')
DATA = Path('/opt/digitafrica/big-data/spark/data')
PROJECT = 'digitafrica-spark'
NETWORK = PROJECT + '_spark-private'
LABEL = 'org.digitafrica.livy-client-run-id'

# Runs only in the owned client container. Reuses the unmodified exercise helpers.
CLIENT = r'''
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
import time
from urllib.error import HTTPError

out = Path('/work/outputs')
record = out / 'client.json'
report = {'status': 'failed', 'session_request_sent': False,
          'session_id': None, 'application_id': None, 'session_removed': False,
          'session_name': 'digitafrica-livy-client-' + os.environ['RUN_ID']}
base = 'http://spark-livy:8998'

def save():
    temporary = record.with_suffix('.tmp')
    temporary.write_text(json.dumps(report), encoding='utf-8')
    temporary.replace(record)

def interrupted(number, frame):
    raise RuntimeError('Client interrupted or exceeded its total computation deadline: ' + str(number))

spec = importlib.util.spec_from_file_location('exercise2', '/work/02_spark_via_livy.py')
exercise = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exercise)
exercise.HTTP_TIMEOUT = 8
exercise.WAIT_TIMEOUT = 120
signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)
signal.signal(signal.SIGALRM, interrupted)
signal.alarm(300)
try:
    save()
    settings = exercise.read_connection_settings()
    if settings['LIVY_URL'] != base:
        raise RuntimeError('Unexpected Livy URL')
    exercise.preview_local_dataset(Path('/work/data/Bank_Personal_Loan_Modelling.csv'))
    sessions = exercise.livy_request(base, 'GET', '/sessions?from=0&size=1')
    if sessions.get('total') != 0:
        raise RuntimeError('Existing Livy sessions; test refused')
    payload = {
        'kind': 'pyspark', 'name': report['session_name'],
        'driverMemory': '512m', 'executorMemory': '512m',
        'executorCores': 1, 'numExecutors': 1,
        'conf': {'spark.cores.max': '1', 'spark.dynamicAllocation.enabled': 'false',
                 'spark.default.parallelism': '2', 'spark.sql.shuffle.partitions': '2',
                 'spark.driver.maxResultSize': '64m', 'spark.ui.enabled': 'false'}
    }
    report['requested_resources'] = payload
    report['session_request_sent'] = True
    save()
    created = exercise.livy_request(base, 'POST', '/sessions', payload)
    report['session_id'] = exercise.response_id(created)
    if isinstance(created.get('appId'), str):
        report['application_id'] = created['appId']
    save()
    sid = report['session_id']
    exercise.wait_for_session(base, sid)
    current = exercise.livy_request(base, 'GET', f'/sessions/{sid}')
    if isinstance(current.get('appId'), str):
        report['application_id'] = current['appId']
        save()
    code = """import json
conf = sc.getConf()
print(json.dumps({'application_id': sc.applicationId, 'master': sc.master,
'spark_version': sc.version, 'driver_host': conf.get('spark.driver.host', 'unset'),
'driver_memory': conf.get('spark.driver.memory', 'unset'),
'executor_memory': conf.get('spark.executor.memory', 'unset'),
'cores_max': conf.get('spark.cores.max', 'unset')}))
"""
    observed = json.loads(exercise.run_statement(base, sid, code).strip())
    report['observed'] = observed
    report['application_id'] = observed['application_id']
    save()
    expected = {'master': 'spark://spark-master:7077', 'spark_version': '3.5.3',
                'driver_host': 'spark-livy', 'driver_memory': '512m',
                'executor_memory': '512m', 'cores_max': '1'}
    for key, value in expected.items():
        if str(observed.get(key, '')).lower() != value.lower():
            raise RuntimeError('Unexpected observed Spark setting: ' + key)
    for heading, code in exercise.analysis_steps(settings['LIVY_DATA_PATH']):
        print(heading, flush=True)
        print(exercise.run_statement(base, sid, code), flush=True)
    hosts = json.loads(exercise.run_statement(base, sid,
        "import json, socket\nprint(json.dumps(sorted(set(sc.parallelize(range(2), 2).map(lambda _: socket.gethostname()).collect()))))").strip())
    report['worker_hosts'] = hosts
    if hosts != ['spark-worker-1']:
        raise RuntimeError('Unexpected executor placement')
    exercise.export_preview(base, sid, out)
    report['status'] = 'computation_passed'
except BaseException as error:
    report['error'] = type(error).__name__ + ': ' + str(error)
finally:
    signal.alarm(0)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if report['session_id'] is not None:
        path = '/sessions/' + str(report['session_id'])
        try:
            try:
                current = exercise.livy_request(base, 'GET', path)
            except HTTPError as error:
                if error.code != 404:
                    raise
                report['session_removed'] = True
            else:
                if current.get('name') != report['session_name']:
                    raise RuntimeError('Refusing cleanup: session name differs from owned run')
                if isinstance(current.get('appId'), str):
                    report['application_id'] = current['appId']
                save()
                try:
                    exercise.livy_request(base, 'DELETE', path)
                except HTTPError as error:
                    if error.code != 404:
                        raise
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    try:
                        exercise.livy_request(base, 'GET', path)
                    except HTTPError as error:
                        if error.code != 404:
                            raise
                        report['session_removed'] = True
                        break
                    time.sleep(2)
            if not report['session_removed']:
                raise RuntimeError('Owned session deletion not confirmed')
        except BaseException as error:
            report['cleanup_error'] = type(error).__name__ + ': ' + str(error)
    elif report['session_request_sent']:
        report['cleanup_error'] = 'Session creation outcome unknown: inspect Livy before retrying; no guessed ID deleted'
    save()
    print(json.dumps(report), flush=True)
sys.exit(0 if report['status'] == 'computation_passed' and report['session_removed'] else 1)
'''

# Host-side fallback uses the existing Livy container, never a new service.
SESSION_PROBE = r'''
import json, sys, urllib.request, urllib.error
base = 'http://127.0.0.1:8998'
method, sid, expected = sys.argv[1:]
path = '/sessions/' + sid
headers = {'Content-Type': 'application/json', 'X-Requested-By': 'digitafrica-organiser-cleanup'}
def request(verb):
    req = urllib.request.Request(base + path, method=verb, headers=headers)
    with urllib.request.urlopen(req, timeout=8) as response:
        data = response.read()
        return json.loads(data) if data else {}
try:
    current = request('GET')
except urllib.error.HTTPError as error:
    if error.code != 404:
        raise
    print(json.dumps({'removed': True}))
else:
    if current.get('name') != expected:
        raise RuntimeError('Owned session name not confirmed; refusing cleanup')
    result = {'removed': False, 'application_id': current.get('appId')}
    if method == 'DELETE':
        try:
            request('DELETE')
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            result['removed'] = True
    print(json.dumps(result))
'''


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def call(args, timeout=30, check=True):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout, check=check)


def output(args):
    return call(args).stdout.strip()


def inspect_container(name):
    result = call(['docker', 'container', 'inspect', name], check=False)
    if result.returncode:
        require('No such container' in result.stderr or 'No such object' in result.stderr,
                'Container existence cannot be established: ' + result.stderr.strip())
        return None
    return json.loads(result.stdout)[0]


def service_id(service):
    ids = output(['docker', 'ps', '-q', '--filter',
                  'label=com.docker.compose.project=' + PROJECT, '--filter',
                  'label=com.docker.compose.service=' + service]).split()
    require(len(ids) == 1, 'Expected one running project service: ' + service)
    return ids[0]


def master_status(master_id):
    probe = ('import json, urllib.request; '
             'r=urllib.request.urlopen("http://spark-master:8080/json/", timeout=8); '
             'print(json.dumps(json.load(r)))')
    value = json.loads(output(['docker', 'exec', master_id, 'python3', '-c', probe]))
    require(isinstance(value.get('activeapps'), list), 'Master application status is unavailable')
    return value


def interrupted(number, frame):
    raise RuntimeError('Host runner interrupted by signal ' + str(number))


def read_client(results):
    path = results / 'client.json'
    if not path.exists() and not path.is_symlink():
        return None
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_size <= 65536,
            'Invalid client evidence file')
    value = json.loads(path.read_text(encoding='utf-8'))
    require(isinstance(value, dict), 'Invalid client evidence JSON')
    return value


def main():
    require(os.geteuid() == 0, 'Organiser helper requires root on the worker VM')
    info = ROOT.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0,
            'Expected root-owned runtime directory, not a symlink')
    source = sys.stdin.buffer.read(131073)
    require(0 < len(source) <= 131072, 'Expected at most 128 KiB of trusted Exercise 2 source')
    compile(source.decode('utf-8'), '02_spark_via_livy.py', 'exec')
    # Shares Step 1's lock so these two organisers cannot overlap on this VM.
    lock = os.open(str(ROOT / '.direct-run.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(lock)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0
                and stat.S_IMODE(info.st_mode) == 0o600, 'Invalid organiser lock')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        os.close(lock)
        raise
    token = uuid.uuid4().hex
    name = 'digitafrica-livy-client-' + token
    report = {'status': 'failed', 'run_id': token, 'container_name': name,
              'container_created': False, 'container_removed': False,
              'session_removed': False, 'application_no_longer_active': False,
              'source_sha256': hashlib.sha256(source).hexdigest(),
              'scope': 'Organiser-only separate private-network HTTP client; not participant isolation or capacity validation'}
    run_dir = results = None
    master_id = livy_id = None
    create_attempted = False
    logs = ''
    client = None
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        image = json.loads(output(['docker', 'image', 'inspect', IMAGE]))[0]
        require(image['Os'] == 'linux' and image['Architecture'] == 'amd64'
                and IMAGE in image.get('RepoDigests', []), 'Pinned client image unavailable')
        network = json.loads(output(['docker', 'network', 'inspect', NETWORK]))[0]
        labels = network.get('Labels') or {}
        require(network['Internal'] and network['Driver'] == 'bridge'
                and labels.get('com.docker.compose.project') == PROJECT
                and labels.get('com.docker.compose.network') == 'spark-private',
                'Private network identity invalid')
        master_id, livy_id = service_id('spark-master'), service_id('spark-livy')
        master = inspect_container(master_id)
        livy = inspect_container(livy_id)
        require(master['Image'] == image['Id'], 'Master image changed after preflight')
        for container in (master, livy):
            require(set(container['NetworkSettings']['Networks']) == {NETWORK},
                    'Shared service must use only the private network')
        require(livy['HostConfig']['Memory'] == 2147483648
                and not livy['HostConfig'].get('PortBindings'), 'Livy limits or privacy changed')
        livy_image = json.loads(output(['docker', 'image', 'inspect',
                                      'digitafrica/livy:0.9.0-incubating-spark3.5.3']))[0]
        require(livy['Image'] == livy_image['Id'], 'Running Livy image changed after preflight')
        before = master_status(master_id)
        require(not before['activeapps'], 'Existing Spark applications; test refused')
        workers = before.get('workers', [])
        require(len(workers) == 1 and workers[0].get('state') == 'ALIVE',
                'Expected the fixed one-worker pilot')
        memory = {line.split()[0].rstrip(':'): int(line.split()[1])
                  for line in Path('/proc/meminfo').read_text().splitlines()
                  if line.startswith(('MemAvailable:', 'MemTotal:'))}
        require(memory.get('MemAvailable', 0) >= 2097152, 'Require 2 GiB available RAM')
        dataset = DATA / 'Bank_Personal_Loan_Modelling.csv'
        require(stat.S_ISDIR(DATA.lstat().st_mode) and stat.S_ISREG(dataset.lstat().st_mode),
                'Dataset directory and CSV must not be symlinks')
        for container in (master, livy, inspect_container(service_id('spark-worker-1'))):
            require(any(m.get('Type') == 'bind' and m.get('Source') == str(DATA)
                        and m.get('Destination') == '/opt/spark-data/data' and m.get('RW') is False
                        for m in container.get('Mounts', [])), 'Shared read-only dataset mount missing')
        uid = int(output(['docker', 'exec', master_id, 'id', '-u', 'spark']))
        gid = int(output(['docker', 'exec', master_id, 'id', '-g', 'spark']))
        require(uid > 0 and gid > 0, 'Client must be non-root')
        run_dir = Path(tempfile.mkdtemp(prefix='livy-client-run-', dir=str(ROOT)))
        run_dir.chmod(0o755)
        for filename, content in [('02_spark_via_livy.py', source), ('client.py', CLIENT.encode())]:
            path = run_dir / filename
            path.write_bytes(content)
            path.chmod(0o444)
        (run_dir / 'data').mkdir(mode=0o755)
        results = run_dir / 'outputs'
        results.mkdir(mode=0o700)
        os.chown(str(results), uid, gid)
        report['evidence_directory'] = str(run_dir)
        report['client_uid_gid'] = f'{uid}:{gid}'
        args = ['docker', 'create', '--name', name, '--hostname', name,
                '--network', NETWORK, '--label', LABEL + '=' + token,
                '--label', 'org.digitafrica.workshop=big-data',
                '--label', 'org.digitafrica.module=spark',
                '--label', 'org.digitafrica.managed-by=organiser',
                '--pull=never', '--init', '--restart=no', '--read-only',
                '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
                '--user', f'{uid}:{gid}', '--cpus=0.5', '--memory=256m',
                '--memory-swap=256m', '--pids-limit=64',
                '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777',
                '--log-driver=json-file', '--log-opt=max-size=10m', '--log-opt=max-file=1',
                '--workdir=/tmp', '--mount', f'type=bind,src={run_dir},dst=/work,readonly',
                '--mount', f'type=bind,src={results},dst=/work/outputs',
                '--mount', f'type=bind,src={DATA},dst=/work/data,readonly',
                '--env', 'LIVY_URL=http://spark-livy:8998',
                '--env', 'LIVY_DATA_PATH=/opt/spark-data/data/Bank_Personal_Loan_Modelling.csv',
                '--env', 'RUN_ID=' + token, '--env', 'HOME=/tmp',
                '--env', 'PYTHONUNBUFFERED=1', '--env', 'PYTHONDONTWRITEBYTECODE=1',
                '--entrypoint=python3', IMAGE, '/work/client.py']
        create_attempted = True
        container_id = output(args)
        report['container_created'] = True
        report['container_id'] = container_id
        owned = inspect_container(container_id)
        require(owned['Image'] == image['Id'] and owned['Config']['Labels'].get(LABEL) == token
                and set(owned['NetworkSettings']['Networks']) == {NETWORK}
                and not owned['HostConfig'].get('PortBindings'), 'Owned client identity invalid')
        output(['docker', 'start', container_id])
        deadline = time.monotonic() + 370
        while True:
            state = inspect_container(container_id)['State']
            if not state['Running']:
                break
            require(time.monotonic() < deadline, 'Client exceeded host execution deadline')
            time.sleep(1)
        report['exit_code'] = state['ExitCode']
        report['oom_killed'] = state.get('OOMKilled', False)
        client = read_client(results)
        require(client is not None, 'Client evidence missing')
        report['client_evidence'] = client
        require(state['ExitCode'] == 0 and not state.get('OOMKilled'), 'Client did not exit successfully')
        require(client.get('status') == 'computation_passed', 'Exercise 2 did not complete')
        preview = results / '02_filtered_preview.csv'
        info = preview.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_size <= 65536, 'Invalid bounded preview CSV')
        text = preview.read_text(encoding='utf-8')
        rows = list(csv.reader(io.StringIO(text)))
        require(rows and rows[0] == ['Age', 'Income', 'Family'] and 1 < len(rows) <= 11,
                'Preview CSV columns or row bound invalid')
        require(all(len(row) == 3 and float(row[0]) > 30 for row in rows[1:]),
                'Preview rows do not satisfy the exercise filter')
        report['preview_csv'] = text
        report['preview_rows'] = len(rows) - 1
        report['status'] = 'computation_passed'
    except Exception as error:
        report['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        cleanup_errors = []
        # Remove the owned HTTP client first; fallback then handles its session.
        try:
            if create_attempted:
                owned = inspect_container(name)
                if owned is not None:
                    require(owned['Name'] == '/' + name and owned['Config']['Labels'].get(LABEL) == token,
                            'Refusing removal: client ownership not confirmed')
                    if owned['State']['Running']:
                        call(['docker', 'stop', '--time', '15', owned['Id']], timeout=25)
                    result = call(['docker', 'logs', owned['Id']], check=False)
                    logs = result.stdout + result.stderr
                    if run_dir is not None:
                        (run_dir / 'client.log').write_text(logs, encoding='utf-8')
                    output(['docker', 'rm', '--force', owned['Id']])
                require(inspect_container(name) is None, 'Owned client removal not confirmed')
                report['container_removed'] = True
        except Exception as error:
            cleanup_errors.append(type(error).__name__ + ': ' + str(error))
        try:
            if results is not None:
                client = read_client(results)
            if client is not None:
                report['client_evidence'] = client
                sid = client.get('session_id')
                app_id = client.get('application_id')
                require(client.get('session_name') == name, 'Evidence session name differs from owned run')
                if sid is not None:
                    require(type(sid) is int and sid >= 0, 'Invalid returned session ID')
                    report['session_id'] = sid
                    require(livy_id is not None, 'Livy container identity unavailable')
                    result = json.loads(output(['docker', 'exec', livy_id, 'python3', '-c',
                                               SESSION_PROBE, 'DELETE', str(sid), name]))
                    app_id = result.get('application_id') or app_id
                    deadline = time.monotonic() + 40
                    while not result.get('removed') and time.monotonic() < deadline:
                        time.sleep(2)
                        result = json.loads(output(['docker', 'exec', livy_id, 'python3', '-c',
                                                   SESSION_PROBE, 'GET', str(sid), name]))
                        app_id = result.get('application_id') or app_id
                    report['session_removed'] = bool(result.get('removed'))
                    require(report['session_removed'], 'Owned session deletion not confirmed')
                elif client.get('session_request_sent'):
                    raise RuntimeError('Session creation outcome unknown; inspect Livy before retrying; no guessed session deleted')
                if app_id:
                    require(isinstance(app_id, str) and app_id.startswith('app-'), 'Invalid application ID')
                    report['application_id'] = app_id
                    require(master_id is not None, 'Master identity unavailable')
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        active = master_status(master_id)['activeapps']
                        if not any(app.get('id') == app_id for app in active):
                            report['application_no_longer_active'] = True
                            break
                        time.sleep(1)
                    require(report['application_no_longer_active'], 'Owned application remains active')
                elif sid is not None:
                    raise RuntimeError('Application ID unavailable; application cleanup cannot be certified')
            elif create_attempted:
                raise RuntimeError('Client evidence missing; session creation outcome cannot be certified; inspect Livy before retrying')
        except Exception as error:
            cleanup_errors.append(type(error).__name__ + ': ' + str(error))
        if cleanup_errors:
            report['cleanup_errors'] = cleanup_errors
        if report.get('error') or cleanup_errors:
            report['status'] = 'failed'
        report['log_tail'] = logs[-12000:]
        if run_dir is not None:
            evidence = run_dir / 'run.json'
            evidence.write_text(json.dumps(report, indent=2), encoding='utf-8')
            evidence.chmod(0o600)
        os.close(lock)
        print(json.dumps(report))
    return 0 if (report['status'] == 'computation_passed' and report['container_removed']
                 and report['session_removed'] and report['application_no_longer_active']) else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'status': 'failed_before_or_during_reporting',
                          'error': type(error).__name__ + ': ' + str(error),
                          'action': 'Inspect retained evidence and owned resources before retrying'}))
        raise SystemExit(1)
