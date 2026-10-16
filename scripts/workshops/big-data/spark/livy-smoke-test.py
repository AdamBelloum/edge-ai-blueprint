#!/usr/bin/env python3
"""One organiser-controlled synthetic computation; delete only our own session."""
import datetime
import json
import signal
import sys
import time
import urllib.error
import urllib.request

BASE = 'http://127.0.0.1:8998'
report = {
    'status': 'FAILED',
    'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'submission_origin': 'organiser docker compose exec inside spark-livy',
    'workload': 'sum of integers 0 through 999, two partitions',
    'session_request_sent': False,
    'session_id': None,
    'cleanup': 'not required: no session request sent',
    'scope': 'single-session educational smoke test, not capacity or scalability evidence'
}
session_id = None
failure = None
started = time.monotonic()
deadline = started + 240


def request(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        raw = response.read()
        return json.loads(raw.decode()) if raw else {}


def wait_for(path, target):
    while time.monotonic() < deadline:
        result = request('GET', path)
        state = result.get('state')
        if state == target:
            return result
        if state in ('error', 'dead', 'killed', 'success', 'cancelled', 'cancelling'):
            raise RuntimeError('Unexpected state for ' + path + ': ' + str(state))
        time.sleep(3)
    raise RuntimeError('Smoke-test deadline exceeded while waiting for ' + path)


def interrupted(signum, frame):
    raise RuntimeError('Test interrupted by signal ' + str(signum))


signal.signal(signal.SIGTERM, interrupted)
payload = {
    'kind': 'pyspark',
    'name': 'organiser-educational-livy-smoke',
    'driverMemory': '512m',
    'executorMemory': '512m',
    'executorCores': 1,
    'numExecutors': 1,
    'conf': {
        'spark.cores.max': '1',
        'spark.dynamicAllocation.enabled': 'false',
        'spark.default.parallelism': '2',
        'spark.sql.shuffle.partitions': '2',
        'spark.driver.maxResultSize': '64m',
        'spark.ui.enabled': 'false'
    }
}
report['requested_resources'] = payload
try:
    assert request('GET', '/sessions?from=0&size=1').get('total') == 0, 'Existing sessions; test refused'
    with urllib.request.urlopen('http://spark-master:8080/json/', timeout=8) as response:
        master = json.load(response)
    assert len(master.get('activeapps', [])) == 0, 'Existing Spark applications; test refused'
    report['session_request_sent'] = True
    report['cleanup'] = 'creation outcome unknown until a session ID is received'
    created = request('POST', '/sessions', payload)
    assert isinstance(created.get('id'), int), 'Session creation returned no integer ID; inspect before retrying'
    session_id = created['id']
    report['session_id'] = session_id
    print('Created smoke-test session ID ' + str(session_id) + '; cleanup targets only this ID.', file=sys.stderr, flush=True)
    session_path = '/sessions/' + str(session_id)
    wait_for(session_path, 'idle')
    code = '\n'.join([
        'import json, socket',
        'conf = sc.getConf()',
        'rows = sc.parallelize(range(1000), 2).mapPartitions(lambda values: [(socket.gethostname(), sum(values))]).collect()',
        "print(json.dumps({'sum': sum(row[1] for row in rows), 'worker_hosts': sorted(set(row[0] for row in rows)), 'partitions': len(rows), 'application_id': sc.applicationId, 'master': sc.master, 'spark_version': sc.version, 'driver_host': conf.get('spark.driver.host', 'unset'), 'driver_memory': conf.get('spark.driver.memory', 'unset'), 'executor_memory': conf.get('spark.executor.memory', 'unset'), 'cores_max': conf.get('spark.cores.max', 'unset')}))"
    ])
    submitted = request('POST', session_path + '/statements', {'kind': 'pyspark', 'code': code})
    statement_id = submitted.get('id')
    assert isinstance(statement_id, int), 'No statement ID returned'
    statement = wait_for(session_path + '/statements/' + str(statement_id), 'available')
    output = statement.get('output') or {}
    if output.get('status') != 'ok':
        raise RuntimeError('Statement failed: ' + json.dumps(output)[:8000])
    observed = json.loads(output['data']['text/plain'].strip())
    report['observed'] = observed
    assert observed['sum'] == 499500, 'Incorrect result'
    assert observed['partitions'] == 2, 'Unexpected partition count'
    assert observed['worker_hosts'] == ['spark-worker-1'], 'Computation did not run on the expected worker'
    assert observed['master'] == 'spark://spark-master:7077', 'Unexpected Spark master'
    assert observed['spark_version'] == '3.5.3', 'Unexpected Spark version'
    assert observed['driver_host'] == 'spark-livy', 'Unexpected advertised driver host'
    assert observed['driver_memory'].lower() == '512m', 'Driver heap setting not verified'
    assert observed['executor_memory'].lower() == '512m', 'Executor heap setting not verified'
    assert observed['cores_max'] == '1', 'Spark core budget not verified'
except BaseException as error:
    failure = type(error).__name__ + ': ' + str(error)
    report['error'] = failure
    if session_id is not None:
        try:
            report['session_log_tail'] = request(
                'GET', '/sessions/' + str(session_id) + '/log?from=0&size=40'
            ).get('log', [])
        except Exception as log_error:
            report['log_read_error'] = str(log_error)
finally:
    if session_id is not None:
        try:
            session_path = '/sessions/' + str(session_id)
            try:
                request('DELETE', session_path)
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    raise
            cleanup_deadline = time.monotonic() + 30
            removed = False
            while time.monotonic() < cleanup_deadline:
                try:
                    request('GET', session_path)
                except urllib.error.HTTPError as error:
                    if error.code == 404:
                        removed = True
                        break
                    raise
                time.sleep(2)
            assert removed, 'Session deletion was not confirmed'
            report['cleanup'] = 'own session deletion confirmed by HTTP 404'
            report['remaining_session_count'] = request('GET', '/sessions?from=0&size=1').get('total')
        except BaseException as cleanup_error:
            report['cleanup'] = 'NOT CONFIRMED; inspect owned session ID before retrying'
            report['cleanup_error'] = type(cleanup_error).__name__ + ': ' + str(cleanup_error)
            failure = failure or report['cleanup_error']
    if failure is None and session_id is not None and report.get('remaining_session_count') == 0:
        report['status'] = 'PASSED'
    report['elapsed_seconds_including_cleanup'] = round(time.monotonic() - started, 2)
    report['finished_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(json.dumps(report, indent=2), flush=True)
sys.exit(0 if report['status'] == 'PASSED' else 1)
