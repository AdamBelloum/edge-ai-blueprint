"""Offline logging regression tests; no live Spark or SSH connections."""
import argparse
import ast
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'workshop_assets/big-data/spark/beginner/spark_direct_submit.py'
PROFILE = '/home/workshop/work/.spark-direct-log4j2-warn.properties'


class SparkRemoteLauncherLoggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = LAUNCHER.read_text(encoding='utf-8')
        cls.nodes = [n for n in ast.parse(cls.source).body
                     if isinstance(n, ast.FunctionDef)]

    def helpers(self, **extra):
        namespace = dict(argparse=argparse, Path=Path, re=re, shlex=shlex,
                         sys=sys, time=time, __file__=str(LAUNCHER))
        namespace.update(extra)
        exec(compile(ast.Module(body=self.nodes, type_ignores=[]),
                     str(LAUNCHER), 'exec'), namespace)
        return namespace

    def test_quiet_driver_profile_and_verbose_defaults(self):
        h = self.helpers()
        for verbose in (False, True):
            commands = [h['sparkpi_command'](verbose=verbose),
                        h['analysis_command']('payload.py', verbose=verbose)]
            for command in commands:
                tokens = shlex.split(command)
                if verbose:
                    self.assertNotIn('--driver-java-options', tokens)
                else:
                    value = tokens[tokens.index('--driver-java-options') + 1]
                    self.assertEqual(value, '-Dlog4j.configurationFile=file:' + PROFILE)
                self.assertNotIn('spark.executor.extraJavaOptions', command)
                self.assertNotIn('2>/dev/null', command)
                self.assertNotIn('grep', command)
                self.assertIn('--master "$SPARK_MASTER_URL"', command)
                self.assertIn('--deploy-mode client', command)
                subprocess.run(['bash', '-n', '-c', command],
                               check=True, capture_output=True)

    def test_activities_preserve_quoting_and_validation(self):
        h = self.helpers()
        filename = 'analysis with spaces; echo unwanted.py'
        for verbose in (False, True):
            for activity in range(1, 6):
                command = h['analysis_command'](filename, activity, verbose)
                self.assertEqual(shlex.split(command)[-3:],
                                 [filename, '--activity', str(activity)])
                subprocess.run(['bash', '-n', '-c', command],
                               check=True, capture_output=True)
        for activity in (True, 0, 6, '1'):
            with self.assertRaises(ValueError):
                h['analysis_command']('payload.py', activity)

    def test_profile_retains_warning_and_error_console_output(self):
        profile = self.helpers()['warning_logging_config']()
        for setting in ('rootLogger.level = warn', 'logger.spark.level = warn',
                        'appender.console.target = SYSTEM_ERR',
                        'rootLogger.appenderRef.console.ref = console',
                        'appender.console.layout.pattern ='):
            self.assertIn(setting, profile)
        self.assertNotIn('level = off', profile)
        self.assertNotIn('type = Null', profile)

    def test_sftp_upload_path_content_and_permissions(self):
        h = self.helpers()
        client = MagicMock()
        sftp = client.open_sftp.return_value.__enter__.return_value
        handle = sftp.open.return_value.__enter__.return_value
        h['upload_warning_logging'](client)
        sftp.open.assert_called_once_with(PROFILE, 'w')
        handle.write.assert_called_once_with(h['warning_logging_config']())
        sftp.chmod.assert_called_once_with(PROFILE, 0o644)

    def test_sftp_failure_propagates(self):
        client = MagicMock()
        client.open_sftp.side_effect = OSError('mock SFTP failure')
        with self.assertRaisesRegex(OSError, 'mock SFTP failure'):
            self.helpers()['upload_warning_logging'](client)

    def run_cli(self, argv, status=0, upload_error=None):
        client = MagicMock()
        client.get_host_keys.return_value = {'[192.0.2.10]:2222': object()}
        channel = client.get_transport.return_value.open_session.return_value
        channel.recv_ready.return_value = False
        channel.recv_stderr_ready.return_value = False
        channel.exit_status_ready.return_value = True
        channel.recv_exit_status.return_value = status
        ssh = SimpleNamespace(SSHClient=MagicMock(return_value=client),
                              RejectPolicy=MagicMock())
        h = self.helpers(paramiko=ssh)
        upload = MagicMock(side_effect=upload_error)
        h['upload_warning_logging'] = upload
        with patch('sys.argv', ['spark_direct_submit.py', *argv]), \
             patch.object(Path, 'is_file', return_value=True), \
             patch.object(Path, 'stat', return_value=SimpleNamespace(st_mode=0o600)), \
             patch('builtins.print'):
            try:
                result = h['main']()
            finally:
                client.close.assert_called_once()
                if upload_error:
                    channel.exec_command.assert_not_called()
        return result, client, channel, upload

    def test_quiet_cli_upload_and_nonzero_exit_status(self):
        for argv in (['test'], ['analyse', '--activity', '1']):
            result, client, channel, upload = self.run_cli(argv, status=7)
            self.assertEqual(result, 7)
            upload.assert_called_once_with(client)
            self.assertIn('--driver-java-options',
                          channel.exec_command.call_args.args[0])

    def test_verbose_and_custom_run_do_not_upload_profile(self):
        for argv in (['test', '--verbose'],
                     ['analyse', '--activity', '1', '--verbose'],
                     ['run', '--', 'printf', 'hello']):
            result, client, channel, upload = self.run_cli(argv)
            self.assertEqual(result, 0)
            upload.assert_not_called()
            self.assertNotIn('log4j.configurationFile',
                             channel.exec_command.call_args.args[0])

    def test_failed_profile_upload_prevents_submission(self):
        with self.assertRaisesRegex(OSError, 'mock profile upload failure'):
            self.run_cli(['test'], upload_error=OSError('mock profile upload failure'))

    def test_streaming_security_and_organiser_evidence_are_retained(self):
        for marker in ('paramiko.RejectPolicy()',
                       'args.key.stat().st_mode & 0o077', 'allow_agent=False',
                       'look_for_keys=False', 'channel.recv_stderr_ready()',
                       'sys.stderr.buffer.write(channel.recv_stderr(32768))',
                       'return status'):
            self.assertIn(marker, self.source)
        runner = (ROOT / 'scripts/workshops/big-data/spark/step1-direct/container-runner.py').read_text()
        self.assertIn('Connected to Spark cluster with app ID', runner)
        self.assertNotIn('SparkDirectParticipantWarnings', runner)


if __name__ == '__main__':
    unittest.main()
