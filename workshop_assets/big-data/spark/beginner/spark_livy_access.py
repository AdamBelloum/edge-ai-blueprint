"""Managed, temporary participant forwarding for the existing Livy exercise.

Only the assigned endpoint in the managed known_hosts is accepted. Forwarding
is loopback-only and uses direct-tcpip to the gateway-approved private Livy
service. No SSH shell, exec, SFTP, installation or container operation occurs.
Paramiko is imported lazily and is already in the prepared requirements.lock.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import select
import socket
import socketserver
import stat
import threading
import time
from urllib.error import HTTPError

DESTINATION = ('spark-livy', 8998)
DATA_CANDIDATE = '/opt/spark-data/data/Bank_Personal_Loan_Modelling.csv'
DATA_MARKER = 'DIGITAFRICA_VERIFIED_DATA:'


def pinned_endpoint(host_keys):
    entries = list(host_keys.keys())
    if len(entries) != 1:
        raise RuntimeError('Expected exactly one assigned, pinned SSH endpoint.')
    match = re.fullmatch(r'\[([^\]]+)\]:(\d+)', entries[0])
    if match is None:
        raise RuntimeError('Expected a pinned [host]:port SSH record.')
    host, port = match.group(1), int(match.group(2))
    if not host or any(ord(char) <= 32 or ord(char) == 127 for char in host) or not 1 <= port <= 65535:
        raise RuntimeError('Invalid assigned SSH endpoint.')
    return host, port


def _credential_file(path, private=False):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError(f'{path.name} must be a regular file owned by this participant.')
    if info.st_mode & (0o077 if private else 0o022):
        raise RuntimeError(f'Unsafe permissions on managed {path.name}.')


def _relay(local, remote, stop):
    local.settimeout(15)
    remote.settimeout(15)
    local_read = remote_read = True
    last_activity = time.monotonic()
    while not stop.is_set() and (local_read or remote_read):
        readers = ([local] if local_read else []) + ([remote] if remote_read else [])
        readable, _, _ = select.select(readers, [], [], 1)
        if not readable:
            if time.monotonic() - last_activity > 30:
                raise TimeoutError('Forwarded HTTP connection idle timeout.')
            continue
        for source in readable:
            data = source.recv(65536)
            last_activity = time.monotonic()
            if source is local:
                if data:
                    remote.sendall(data)
                else:
                    local_read = False
                    remote.shutdown_write()
            elif data:
                local.sendall(data)
            else:
                remote_read = False
                try:
                    local.shutdown(socket.SHUT_WR)
                except OSError:
                    pass


@contextmanager
def _ssh_forward():
    import paramiko
    credentials = Path.home() / '.ssh' / 'spark-direct'
    key = credentials / 'login_key'
    known = credentials / 'known_hosts'
    _credential_file(key, private=True)
    _credential_file(known)
    client = paramiko.SSHClient()
    server = thread = None
    stop = threading.Event()
    try:
        client.load_host_keys(str(known))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        host, port = pinned_endpoint(client.get_host_keys())
        client.connect(host, port, username='workshop', key_filename=str(key),
                       allow_agent=False, look_for_keys=False,
                       timeout=15, auth_timeout=15, banner_timeout=15)
        transport = client.get_transport()
        if transport is None or not transport.is_authenticated():
            raise RuntimeError('Managed SSH authentication was not established.')
        transport.set_keepalive(20)

        class ForwardHandler(socketserver.BaseRequestHandler):
            def handle(self):
                channel = None
                try:
                    channel = transport.open_channel('direct-tcpip', DESTINATION,
                                                     self.client_address, timeout=15)
                    if channel is None:
                        raise RuntimeError('The gateway did not open its permitted forwarding channel.')
                    _relay(self.request, channel, stop)
                except Exception as error:
                    if not stop.is_set():
                        print(f'Livy forwarding error: {type(error).__name__}: {error}', flush=True)
                finally:
                    if channel is not None:
                        channel.close()

        class LoopbackServer(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = False

        server = LoopbackServer(('127.0.0.1', 0), ForwardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_address[1]}'
        print(f'Managed Livy forwarding: assigned SSH endpoint {host}:{port}; loopback only.', flush=True)
        yield url
    finally:
        stop.set()
        if server is not None:
            if thread is not None and thread.is_alive():
                server.shutdown()
            server.server_close()
        client.close()
        if thread is not None:
            thread.join(timeout=2)


@contextmanager
def managed_connection(read_explicit_settings):
    """Explicit complete settings remain supported; partial overrides fail.

    With neither setting present, use the managed assigned SSH identity. The
    returned candidate is verified in the owned session before CSV analysis;
    it is not exported or represented as a verified data path in advance.
    """
    supplied = [os.environ.get(name, '').strip() for name in ('LIVY_URL', 'LIVY_DATA_PATH')]
    if any(supplied):
        settings = dict(read_explicit_settings())
        settings['VERIFY_DATASET'] = False
        yield settings
        return
    with _ssh_forward() as url:
        yield {'LIVY_URL': url, 'LIVY_DATA_PATH': DATA_CANDIDATE, 'VERIFY_DATASET': True}


def verify_dataset(run_statement, base_url, session_id, candidate, local_csv):
    digest = hashlib.sha256()
    with Path(local_csv).open('rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    expected = digest.hexdigest()
    code = """
import json
if not spark.sparkContext.master.startswith('spark://'):
    raise RuntimeError('Managed Livy must use the assigned standalone Spark cluster.')
_digitafrica_candidate = """ + repr(candidate) + """
_digitafrica_expected_sha = """ + repr(expected) + """

def _digitafrica_hash_csv(path):
    import hashlib
    from pathlib import Path
    if not Path(path).is_file():
        raise RuntimeError('Supplied CSV is absent at the reviewed data-mount candidate.')
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()

def _digitafrica_check_executor(values):
    import socket
    for value in values:
        yield {'host': socket.gethostname(), 'sha256': _digitafrica_hash_csv(_digitafrica_candidate)}

_digitafrica_driver_sha = _digitafrica_hash_csv(_digitafrica_candidate)
_digitafrica_workers = (spark.sparkContext.parallelize([0], 1)
                       .mapPartitions(_digitafrica_check_executor).collect())
if (_digitafrica_driver_sha != _digitafrica_expected_sha or len(_digitafrica_workers) != 1
        or _digitafrica_workers[0]['sha256'] != _digitafrica_expected_sha):
    raise RuntimeError('Driver/executor CSV bytes differ from the supplied participant-local CSV.')
print(""" + repr(DATA_MARKER) + """ + json.dumps({'path': _digitafrica_candidate,
    'sha256': _digitafrica_driver_sha, 'executors': _digitafrica_workers}))
"""
    text = run_statement(base_url, session_id, code)
    payloads = [line[len(DATA_MARKER):] for line in text.splitlines() if line.startswith(DATA_MARKER)]
    if len(payloads) != 1:
        raise RuntimeError('Expected exactly one dataset-verification payload.')
    result = json.loads(payloads[0])
    workers = result.get('executors')
    if (result.get('path') != candidate or result.get('sha256') != expected
            or not isinstance(workers, list) or len(workers) != 1
            or not isinstance(workers[0], dict) or workers[0].get('sha256') != expected
            or not isinstance(workers[0].get('host'), str) or not workers[0]['host']):
        raise RuntimeError('Unexpected dataset-verification metadata.')
    print('CSV SHA-256 verified on the Livy driver and executor:', workers[0]['host'], flush=True)
    return result['path']


def delete_owned_session(request, base_url, session_id, timeout=60):
    """Delete only the returned owned ID; require GET 404 before success."""
    if type(session_id) is not int or session_id < 0:
        raise ValueError('A valid owned session ID is required.')
    deletion_error = None
    try:
        request(base_url, 'DELETE', f'/sessions/{session_id}')
    except Exception as error:
        deletion_error = error
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            request(base_url, 'GET', f'/sessions/{session_id}')
        except HTTPError as error:
            if error.code == 404:
                return
            raise RuntimeError(f'Cannot verify cleanup of owned session {session_id}: {error}') from error
        except Exception as error:
            raise RuntimeError(f'Cannot verify cleanup of owned session {session_id}: {error}') from error
        time.sleep(2)
    detail = f'; deletion request error: {deletion_error}' if deletion_error else ''
    raise TimeoutError(f'Cleanup of owned session {session_id} was not confirmed{detail}.')
