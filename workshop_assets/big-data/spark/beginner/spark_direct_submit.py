#!/usr/bin/env python3
"""Workshop-local SSH/SFTP transport, not a replacement Spark submission API.

Use the organiser-prepared Python environment; do not install software here.
From the prepared participant workspace:
    python3 spark_direct_submit.py test
    python3 spark_direct_submit.py analyse
    python3 spark_direct_submit.py analyse --activity 1

Activities: 1=schema/count, 2=selection, 3=filter, 4=aggregation, 5=export.
Each activity is a separate submission with its own analysis session cleanup.
Only full analysis/activity 5 retrieves the bounded preview. Use the supplied
updated analysis payload; custom payloads must implement any selected activity.

Credentials default to ~/.ssh/spark-direct/login_key and known_hosts.
The endpoint defaults to the single organiser-pinned known_hosts record.
Explicit --host/--port/--key/--known-hosts options remain supported.
The updated client image must be prepared and started before execution.

SSH keys/known_hosts are supplied separately by the organiser for your VM.
Host-key verification is mandatory. No auto-trust or password fallback.
"""
import argparse
import re
from pathlib import Path
import shlex
import sys
import time
import uuid
import paramiko


def spark_logging_options(verbose=False):
    """Override only this driver; verbose retains the image defaults."""
    if verbose:
        return ''
    option = '-Dlog4j.configurationFile=file:/home/workshop/work/.spark-direct-log4j2-warn.properties'
    return '--driver-java-options ' + shlex.quote(option) + ' '


def warning_logging_config():
    """Keep warnings and errors on stderr; application output is not filtered."""
    return """status = error
name = SparkDirectParticipantWarnings
appender.console.type = Console
appender.console.name = console
appender.console.target = SYSTEM_ERR
appender.console.layout.type = PatternLayout
appender.console.layout.pattern = %d{yy/MM/dd HH:mm:ss} %p %c{1}: %m%n
rootLogger.level = warn
rootLogger.appenderRef.console.ref = console
logger.spark.name = org.apache.spark
logger.spark.level = warn
logger.spark.additivity = true
"""


def upload_warning_logging(client):
    """Write a small fixed-content profile through the pinned SFTP connection.

    The profile remains in the assigned client workspace; installed Spark
    configuration and master/worker/organiser logging remain unchanged.
    """
    path = '/home/workshop/work/.spark-direct-log4j2-warn.properties'
    with client.open_sftp() as sftp:
        with sftp.open(path, 'w') as handle:
            handle.write(warning_logging_config())
        sftp.chmod(path, 0o644)


def sparkpi_command(verbose=False):
    return (
        'set -eu; cd /home/workshop/work; '
        ': "${SPARK_HOME:?Missing organiser SPARK_HOME}"; '
        ': "${SPARK_MASTER_URL:?Missing organiser SPARK_MASTER_URL}"; '
        ': "${SPARK_DRIVER_HOST:?Missing organiser SPARK_DRIVER_HOST}"; '
        'set -- "$SPARK_HOME"/examples/jars/spark-examples_*.jar; '
        'test -f "$1"; '
        'timeout 120 spark-submit '
        '--master "$SPARK_MASTER_URL" '
        '--deploy-mode client '
        '--total-executor-cores 1 '
        '--executor-memory 512m '
        '--driver-memory 512m '
        + spark_logging_options(verbose)
        + '--conf "spark.driver.host=$SPARK_DRIVER_HOST" '
        '--conf spark.driver.bindAddress=0.0.0.0 '
        '--class org.apache.spark.examples.SparkPi "$1" 2'
    )


def analysis_command(filename, activity=None, verbose=False):
    if activity is not None and (
        type(activity) is not int or activity not in range(1, 6)
    ):
        raise ValueError('Activity must be an integer from 1 to 5.')
    command = (
        'set -eu; cd /home/workshop/work; '
        ': "${SPARK_MASTER_URL:?Missing organiser SPARK_MASTER_URL}"; '
        ': "${SPARK_DRIVER_HOST:?Missing organiser SPARK_DRIVER_HOST}"; '
        ': "${SPARK_DATA_PATH:?Missing organiser SPARK_DATA_PATH}"; '
        'timeout 300 spark-submit '
        '--master "$SPARK_MASTER_URL" '
        '--deploy-mode client '
        '--total-executor-cores 1 '
        '--executor-memory 512m '
        '--driver-memory 512m '
        + spark_logging_options(verbose)
        + '--conf "spark.driver.host=$SPARK_DRIVER_HOST" '
        '--conf spark.driver.bindAddress=0.0.0.0 '
        + shlex.quote(filename)
    )
    if activity is not None:
        command += ' ' + shlex.join(['--activity', str(activity)])
    return command


def resolve_endpoint(args, parser, client):
    if args.host is None:
        entries = list(client.get_host_keys().keys())
        if len(entries) != 1:
            parser.error(
                'Expected one pinned endpoint; supply --host/--port explicitly.'
            )
        match = re.fullmatch(r'\[([^\]]+)\]:(\d+)', entries[0])
        if match is None:
            parser.error(
                'Expected a pinned [host]:port record; supply --host/--port.'
            )
        args.host = match.group(1)
        if args.port is None:
            args.port = int(match.group(2))
    if args.port is None:
        args.port = 2222
    if not args.host or not 1 <= args.port <= 65535:
        parser.error('Supply a nonempty host and valid SSH port.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    credentials = Path.home() / '.ssh' / 'spark-direct'
    p.add_argument('--host')
    p.add_argument('--port', type=int)
    p.add_argument('--key', type=Path, default=credentials / 'login_key')
    p.add_argument('--known-hosts', type=Path, default=credentials / 'known_hosts')
    sub = p.add_subparsers(dest='operation', required=True)
    put = sub.add_parser('put', help='Upload a script to your group client workspace')
    put.add_argument('local', type=Path)
    get = sub.add_parser('get', help='Retrieve a file beneath the group workspace')
    get.add_argument('remote')
    get.add_argument('local', type=Path)
    run = sub.add_parser('run', help='Run the visible command after -- in the client workspace')
    run.add_argument('command', nargs=argparse.REMAINDER)
    test = sub.add_parser('test', help='Submit SparkPi to the prepared cluster')
    test.add_argument('--verbose', action='store_true',
                      help='Keep image default driver logging instead of WARN.')
    analyse = sub.add_parser('analyse', help='Run full bank analysis or one learning activity')
    analyse.add_argument('--verbose', action='store_true',
                         help='Keep image default driver logging instead of WARN.')
    analyse.add_argument(
        'local', type=Path, nargs='?',
        default=Path(__file__).resolve().with_name('01_spark_basics.py'),
    )
    analyse.add_argument(
        '--activity', type=int, choices=range(1, 6),
        help='Run one independent activity (1-5); omit for the full analysis.',
    )
    args = p.parse_args()
    if not args.key.is_file() or args.key.stat().st_mode & 0o077:
        p.error('Private key must exist with mode 0600 or more restrictive.')
    if not args.known_hosts.is_file():
        p.error('Organiser-supplied known_hosts file is required.')
    client = paramiko.SSHClient()
    client.load_host_keys(str(args.known_hosts))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    resolve_endpoint(args, p, client)
    try:
        client.connect(args.host, args.port, username='workshop',
                       key_filename=str(args.key), allow_agent=False,
                       look_for_keys=False, timeout=15, auth_timeout=15,
                       banner_timeout=15)
        if args.operation in ('test', 'analyse') and not args.verbose:
            upload_warning_logging(client)
        if args.operation in ('put', 'analyse'):
            if not args.local.is_file():
                p.error('Upload source must be a regular file.')
            with client.open_sftp() as sftp:
                sftp.put(str(args.local), '/home/workshop/work/' + args.local.name)
            print('Uploaded:', args.local.name, flush=True)
            if args.operation == 'put':
                return 0
        if args.operation == 'get':
            rel = Path(args.remote)
            if rel.is_absolute() or '..' in rel.parts:
                p.error('Retrieve a relative file beneath the group workspace.')
            with client.open_sftp() as sftp:
                sftp.get('/home/workshop/work/' + str(rel), str(args.local))
            print('Retrieved:', args.local)
        else:
            if args.operation == 'test':
                remote = sparkpi_command(verbose=args.verbose)
            elif args.operation == 'analyse':
                remote = analysis_command(
                    args.local.name, activity=args.activity, verbose=args.verbose,
                )
            else:
                cmd = args.command
                if cmd and cmd[0] == '--':
                    cmd = cmd[1:]
                if not cmd:
                    p.error('Supply a command after run --.')
                remote = 'cd /home/workshop/work && ' + shlex.join(cmd)
            print('Remote command:', remote, flush=True)
            # Drain both streams concurrently to avoid SSH flow-control deadlock.
            transport = client.get_transport()
            channel = transport.open_session(timeout=15)
            channel.exec_command(remote)
            try:
                while True:
                    while channel.recv_ready():
                        sys.stdout.buffer.write(channel.recv(32768)); sys.stdout.buffer.flush()
                    while channel.recv_stderr_ready():
                        sys.stderr.buffer.write(channel.recv_stderr(32768)); sys.stderr.buffer.flush()
                    if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                        break
                    time.sleep(0.05)
                status = channel.recv_exit_status()
                print('Remote exit status:', status, flush=True)
                # Only full analysis/activity 5 produces a preview. Do not
                # retrieve an older shared preview after activities 1-4.
                if (status == 0 and args.operation == 'analyse'
                        and args.activity in (None, 5)):
                    output_dir = (
                        args.local.resolve().parent / 'outputs'
                        / ('remote-' + uuid.uuid4().hex[:12])
                    )
                    output_dir.mkdir(parents=True, exist_ok=False)
                    output_file = output_dir / 'filtered_preview.csv'
                    with client.open_sftp() as sftp:
                        sftp.get(
                            '/home/workshop/work/outputs/filtered_preview.csv',
                            str(output_file),
                        )
                    print('Downloaded preview:', output_file, flush=True)
                return status
            finally:
                channel.close()
        return 0
    finally:
        client.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, paramiko.SSHException) as exc:
        print('SSH/SFTP failed: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print('Connection interrupted. Remote Spark cleanup is not guaranteed; ask the organiser before retrying.', file=sys.stderr)
        raise SystemExit(130)
