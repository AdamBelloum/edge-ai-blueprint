"""Offline regression tests for the participant Spark launcher."""
import ast
from pathlib import Path
import re
import shlex
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "workshop_assets/big-data/spark/beginner/spark_remote.py"


class SparkRemoteLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = LAUNCHER.read_text()
        names = {"sparkpi_command", "analysis_command", "resolve_endpoint"}
        nodes = [
            node for node in ast.parse(cls.source).body
            if isinstance(node, ast.FunctionDef) and node.name in names
        ]
        if {node.name for node in nodes} != names:
            raise AssertionError("Required launcher helpers are missing.")
        cls.helpers = {"re": re, "shlex": shlex}
        exec(compile(
            ast.Module(body=nodes, type_ignores=[]),
            str(LAUNCHER), "exec",
        ), cls.helpers)

    def resolve(self, entries, host=None, port=None):
        args = SimpleNamespace(host=host, port=port)
        parser = Mock()
        parser.error.side_effect = ValueError
        client = Mock()
        client.get_host_keys.return_value = dict.fromkeys(entries)
        self.helpers["resolve_endpoint"](args, parser, client)
        return args

    def test_both_commands_select_remote_master_and_driver(self):
        commands = [
            self.helpers["sparkpi_command"](),
            self.helpers["analysis_command"]("01_spark_basics.py"),
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertIn('--master "$SPARK_MASTER_URL"', command)
                self.assertIn('--deploy-mode client', command)
                self.assertIn('spark.driver.host=$SPARK_DRIVER_HOST', command)
                self.assertIn('spark.driver.bindAddress=0.0.0.0', command)
                self.assertNotIn("172.24.0.3", command)

    def test_sparkpi_class_and_analysis_dataset_guard(self):
        self.assertIn(
            "org.apache.spark.examples.SparkPi",
            self.helpers["sparkpi_command"](),
        )
        self.assertIn(
            "${SPARK_DATA_PATH:?",
            self.helpers["analysis_command"]("01_spark_basics.py"),
        )

    def test_analysis_filename_is_shell_quoted(self):
        filename = "analysis with spaces; echo unwanted.py"
        command = self.helpers["analysis_command"](filename)
        self.assertEqual(shlex.split(command)[-1], filename)

    def test_generated_commands_have_valid_shell_syntax(self):
        for command in (
            self.helpers["sparkpi_command"](),
            self.helpers["analysis_command"]("01_spark_basics.py"),
        ):
            subprocess.run(
                ["bash", "-n", "-c", command],
                check=True, capture_output=True,
            )

    def test_endpoint_comes_from_single_pinned_record(self):
        args = self.resolve(["[192.0.2.10]:2244"])
        self.assertEqual((args.host, args.port), ("192.0.2.10", 2244))

    def test_missing_ambiguous_and_invalid_endpoints_are_rejected(self):
        for entries in (
            [],
            ["[192.0.2.10]:2222", "[192.0.2.11]:2222"],
            ["invalid-record"],
        ):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                self.resolve(entries)
        for port in (-1, 0, 65536):
            with self.subTest(port=port), self.assertRaises(ValueError):
                self.resolve([], host="192.0.2.10", port=port)

    def test_explicit_endpoint_overrides_are_preserved(self):
        args = self.resolve([], host="192.0.2.20", port=2244)
        self.assertEqual((args.host, args.port), ("192.0.2.20", 2244))
        args = self.resolve([], host="192.0.2.20")
        self.assertEqual(args.port, 2222)

    def test_startup_requires_inactive_project_and_allows_image_updates(self):
        playbook = (
            ROOT / "playbooks/participant-big-data-spark-direct.yml"
        ).read_text()
        self.assertIn(
            "direct_running_before_start.stdout | trim == ''", playbook,
        )
        self.assertNotIn("- --no-recreate", playbook)
        self.assertLess(
            playbook.index("Require explicit stop before updating the runtime"),
            playbook.index("Start only master, one worker and client"),
        )

    def test_security_guards_and_runtime_settings_are_retained(self):
        for marker in (
            "paramiko.RejectPolicy()",
            "args.key.stat().st_mode & 0o077",
            "allow_agent=False",
            "look_for_keys=False",
        ):
            self.assertIn(marker, self.source)
        template = (
            ROOT / "roles/big_data_spark_runtime/templates/client.Dockerfile.j2"
        ).read_text()
        for prefix in (" 'SetEnv ", "ENV "):
            line = next(line for line in template.splitlines()
                        if line.startswith(prefix))
            for setting in (
                "JAVA_HOME=/opt/java/openjdk",
                "SPARK_MASTER_URL=spark://spark-master:7077",
                "SPARK_DRIVER_HOST=spark-client",
                "SPARK_DATA_PATH=/opt/spark-data/data/Bank_Personal_Loan_Modelling.csv",
            ):
                self.assertIn(setting, line)
        self.assertIn(
            "ln -s /opt/spark-data/data /home/workshop/work/data", template,
        )


if __name__ == "__main__":
    unittest.main()
