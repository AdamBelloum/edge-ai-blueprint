#!/usr/bin/env python3
"""Root-run organiser test helper; trusted exercise source arrives on stdin.

Not a participant endpoint or a sandbox for untrusted Python. Requires an
already-running reviewed Spark runtime. Creates one bounded driver container,
retains a unique evidence directory, and removes only its owned container.
The caller must perform the full Spark preflight before invoking this helper.
"""
import csv
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
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
OWNER_LABEL = 'org.digitafrica.direct-run-id'


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
                'Cannot establish container existence: ' + result.stderr.strip())
        return None
    return json.loads(result.stdout)[0]


def master_status(master_id):
    probe = ('import json, urllib.request; '
             'r=urllib.request.urlopen("http://spark-master:8080/json/", timeout=5); '
             'print(json.dumps(json.load(r)))')
    return json.loads(output(['docker', 'exec', master_id, 'python3', '-c', probe]))


def interrupted(signum, frame):
    raise RuntimeError('Runner interrupted by signal {}'.format(signum))


def main():
    require(os.geteuid() == 0, 'This organiser helper requires root on the worker VM')
    root_stat = ROOT.lstat()
    require(stat.S_ISDIR(root_stat.st_mode) and root_stat.st_uid == 0,
            'Expected the root-owned runtime directory, not a symlink')
    source = sys.stdin.buffer.read(131073)
    require(0 < len(source) <= 131072, 'Expected at most 128 KiB of trusted exercise source')
    compile(source.decode('utf-8'), '01_spark_basics.py', 'exec')
    lock_fd = os.open(str(ROOT / '.direct-run.lock'),
                      os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        lock_stat = os.fstat(lock_fd)
        require(stat.S_ISREG(lock_stat.st_mode) and lock_stat.st_uid == 0
                and stat.S_IMODE(lock_stat.st_mode) == 0o600,
                'Invalid organiser lock file')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        os.close(lock_fd)
        raise
    token = uuid.uuid4().hex
    name = 'digitafrica-direct-' + token
    report = {'status': 'failed', 'run_id': token, 'container_name': name,
              'container_created': False, 'container_removed': False,
              'source_sha256': hashlib.sha256(source).hexdigest(),
              'scope': 'organiser-only single-job test; not participant isolation or capacity validation'}
    run_dir = None
    create_attempted = False
    master_id = None
    application_id = None
    logs = ''
    error = None
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        image = json.loads(output(['docker', 'image', 'inspect', IMAGE]))[0]
        require(image['Os'] == 'linux' and image['Architecture'] == 'amd64'
                and IMAGE in image.get('RepoDigests', []), 'Pinned image is unavailable')
        network = json.loads(output(['docker', 'network', 'inspect', NETWORK]))[0]
        labels = network.get('Labels') or {}
        require(network['Internal'] and network['Driver'] == 'bridge'
                and labels.get('com.docker.compose.project') == PROJECT
                and labels.get('com.docker.compose.network') == 'spark-private',
                'Private project network identity is invalid')
        ids = output(['docker', 'ps', '-q', '--filter',
                      'label=com.docker.compose.project=' + PROJECT, '--filter',
                      'label=com.docker.compose.service=spark-master']).split()
        require(len(ids) == 1, 'Expected one running project master')
        master_id = ids[0]
        master_container = inspect_container(master_id)
        require(master_container['Image'] == image['Id']
                and NETWORK in master_container['NetworkSettings']['Networks'],
                'Master image or network changed since preflight')
        before = master_status(master_id)
        require('activeapps' in before and not before['activeapps'],
                'Cluster is not idle; do not compete with another application')
        live = before.get('workers', [])
        require(len(live) in (1, 2) and all(w.get('state') == 'ALIVE' for w in live),
                'Expected one or two live Spark workers')
        mem = dict((line.split()[0].rstrip(':'), int(line.split()[1]))
                   for line in Path('/proc/meminfo').read_text().splitlines()
                   if line.startswith(('MemAvailable:', 'MemTotal:')))
        require(mem.get('MemAvailable', 0) >= 2097152,
                'Available RAM fell below 2 GiB; no driver started')
        # Resolve the pinned image account through the already-running master.
        uid = int(output(['docker', 'exec', master_id, 'id', '-u', 'spark']))
        gid = int(output(['docker', 'exec', master_id, 'id', '-g', 'spark']))
        require(uid > 0 and gid > 0, 'Driver must use a non-root image account')
        require(stat.S_ISDIR(DATA.lstat().st_mode)
                and stat.S_ISREG((DATA / 'Bank_Personal_Loan_Modelling.csv').lstat().st_mode),
                'Dataset directory and CSV must not be symlinks')
        run_dir = Path(tempfile.mkdtemp(prefix='direct-run-', dir=str(ROOT)))
        # Parent runtime remains protected; bind-mounted run directory is traversable.
        run_dir.chmod(0o755)
        script = run_dir / '01_spark_basics.py'
        script.write_bytes(source)
        script.chmod(0o444)
        (run_dir / 'data').mkdir(mode=0o755)
        results = run_dir / 'outputs'
        results.mkdir(mode=0o700)
        os.chown(str(results), uid, gid)
        report['evidence_directory'] = str(run_dir)
        report['driver_uid_gid'] = '{}:{}'.format(uid, gid)
        args = ['docker', 'create', '--name', name, '--hostname', name,
                '--network', NETWORK, '--network-alias', name,
                '--label', OWNER_LABEL + '=' + token,
                '--label', 'org.digitafrica.workshop=big-data',
                '--label', 'org.digitafrica.module=spark',
                '--label', 'org.digitafrica.managed-by=organiser',
                '--pull=never', '--init', '--restart=no', '--read-only',
                '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
                '--user', '{}:{}'.format(uid, gid), '--cpus=1',
                '--memory=1536m', '--memory-swap=1536m', '--pids-limit=256',
                '--tmpfs', '/tmp:rw,exec,nosuid,nodev,size=256m,mode=1777',
                '--log-driver=json-file', '--log-opt=max-size=10m', '--log-opt=max-file=1',
                '--workdir=/tmp',
                '--mount', 'type=bind,src={},dst=/work,readonly'.format(run_dir),
                '--mount', 'type=bind,src={},dst=/work/outputs'.format(results),
                '--mount', 'type=bind,src={},dst=/work/data,readonly'.format(DATA),
                '--mount', 'type=bind,src={},dst=/opt/spark-data/data,readonly'.format(DATA),
                '--env', 'SPARK_MASTER_URL=spark://spark-master:7077',
                '--env', 'SPARK_DRIVER_HOST=' + name,
                '--env', 'SPARK_DATA_PATH=/opt/spark-data/data/Bank_Personal_Loan_Modelling.csv',
                '--env', 'PYSPARK_PYTHON=python3', '--env', 'PYSPARK_DRIVER_PYTHON=python3',
                '--env', 'PYTHONUNBUFFERED=1', '--env', 'HOME=/tmp',
                '--entrypoint=/opt/spark/bin/spark-submit', IMAGE,
                '--master', 'spark://spark-master:7077', '--deploy-mode', 'client',
                '--driver-memory', '512m', '--executor-memory', '512m',
                '--conf', 'spark.executor.cores=1', '--conf', 'spark.cores.max=1',
                '--conf', 'spark.driver.host=' + name,
                '--conf', 'spark.driver.bindAddress=0.0.0.0',
                '--conf', 'spark.local.dir=/tmp/spark-local',
                '--conf', 'spark.ui.enabled=false', '/work/01_spark_basics.py']
        create_attempted = True
        container_id = output(args)
        report['container_created'] = True
        report['container_id'] = container_id
        owned = inspect_container(name)
        require(owned['Id'] == container_id and owned['Image'] == image['Id']
                and owned['Config']['Labels'].get(OWNER_LABEL) == token,
                'Created container identity could not be confirmed')
        output(['docker', 'start', container_id])
        deadline = time.monotonic() + 180
        while True:
            state = inspect_container(container_id)['State']
            if not state['Running']:
                break
            require(time.monotonic() < deadline, 'Driver exceeded the 180-second execution limit')
            time.sleep(1)
        report['exit_code'] = state['ExitCode']
        report['oom_killed'] = state.get('OOMKilled', False)
        # Docker separates stderr; Spark logs usually appear there.
        log_result = call(['docker', 'logs', container_id])
        logs = log_result.stdout + log_result.stderr
        (run_dir / 'driver.log').write_text(logs, encoding='utf-8')
        match = re.search(r'Connected to Spark cluster with app ID (app-[\w-]+)', logs)
        application_id = match.group(1) if match else None
        report['application_id'] = application_id
        require(state['ExitCode'] == 0 and not state.get('OOMKilled'), 'Driver did not exit successfully')
        require('Analysis completed successfully.' in logs
                and 'Spark master: spark://spark-master:7077' in logs,
                'Expected exercise completion and standalone master evidence are missing')
        require(application_id is not None, 'Standalone application registration was not found in logs')
        preview = results / 'filtered_preview.csv'
        require(stat.S_ISREG(preview.lstat().st_mode) and preview.stat().st_size <= 65536,
                'Expected a small regular preview CSV, not a symlink')
        text = preview.read_text(encoding='utf-8')
        rows = list(csv.reader(io.StringIO(text)))
        require(rows and rows[0] == ['Age', 'Income', 'Family'] and 1 < len(rows) <= 11,
                'Preview CSV header or bounded row count is invalid')
        report['preview_csv'] = text
        report['preview_rows'] = len(rows) - 1
        report['status'] = 'computation_passed'
    except Exception as exc:
        error = '{}: {}'.format(type(exc).__name__, exc)
    finally:
        # Keep cleanup running if a second ordinary interrupt arrives.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            if create_attempted:
                owned = inspect_container(name)
                if owned is not None:
                    require(owned['Name'] == '/' + name
                            and owned['Config']['Labels'].get(OWNER_LABEL) == token,
                            'Refusing cleanup: container ownership was not confirmed')
                    if run_dir is not None and not logs:
                        result = call(['docker', 'logs', owned['Id']], check=False)
                        logs = result.stdout + result.stderr
                        (run_dir / 'driver.log').write_text(logs, encoding='utf-8')
                    output(['docker', 'rm', '--force', owned['Id']])
                require(inspect_container(name) is None, 'Owned container removal was not confirmed')
                report['container_removed'] = True
            if application_id is None and logs:
                match = re.search(r'Connected to Spark cluster with app ID (app-[\w-]+)', logs)
                application_id = match.group(1) if match else None
                report['application_id'] = application_id
            if application_id and master_id:
                for attempt in range(15):
                    active = master_status(master_id).get('activeapps', [])
                    if not any(a.get('id') == application_id for a in active):
                        report['application_no_longer_active'] = True
                        break
                    time.sleep(1)
                require(report.get('application_no_longer_active'),
                        'Owned application is still active; no unrelated application was removed')
        except Exception as exc:
            report['cleanup_error'] = '{}: {}'.format(type(exc).__name__, exc)
        if error:
            report['error'] = error
        if error or report.get('cleanup_error'):
            report['status'] = 'failed'
        report['log_tail'] = logs[-12000:]
        if run_dir is not None:
            evidence = run_dir / 'run.json'
            evidence.write_text(json.dumps(report, indent=2), encoding='utf-8')
            evidence.chmod(0o600)
        os.close(lock_fd)
        print(json.dumps(report))
    return 0 if report['status'] == 'computation_passed' and report['container_removed'] else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'status': 'failed_before_execution',
                          'error': '{}: {}'.format(type(exc).__name__, exc)}))
        raise SystemExit(1)
