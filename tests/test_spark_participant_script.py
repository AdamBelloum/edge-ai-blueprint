"""Check the participant Python alternative without importing or starting Spark.

Run from the repository root:
    python3 tests/test_spark_participant_script.py

The script is loaded under a non-__main__ name. Configuration is tested using
process-local environment patches; exports use temporary directories; the Spark
session and analysis are mocked when testing lifecycle behaviour. These tests do
not establish PySpark compatibility, cluster connectivity or distributed results.
"""

import ast
from contextlib import redirect_stdout
import csv
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


class ParticipantScriptTests(unittest.TestCase):
    """Exercise documentation and safe local behaviour of 01_spark_basics.py."""

    def setUp(self):
        """Load a fresh script namespace without executing its entry point."""
        self.script_path = (
            Path(__file__).resolve().parents[1]
            / "workshop_assets/big_data/spark/01_spark_basics.py"
        )
        self.source = self.script_path.read_text(encoding="utf-8")
        self.namespace = {
            "__name__": "spark_participant_script_under_test",
            "__file__": str(self.script_path),
        }
        exec(compile(self.source, str(self.script_path), "exec"), self.namespace)
        self.settings = {
            "SPARK_MASTER_URL": "spark://master.example.test:7077",
            "SPARK_DATA_PATH": "/example/data/input.csv",
            "SPARK_DRIVER_HOST": "driver.example.test",
        }

    def main_replacements(self, spark, analysis):
        """Return mocks that isolate main() from local data and Spark startup."""
        return {
            "preview_local_dataset": Mock(),
            "read_connection_settings": Mock(return_value=self.settings),
            "create_spark_session": Mock(return_value=spark),
            "analyse_dataset": analysis,
        }

    def test_module_and_all_functions_have_docstrings(self):
        """Require valid syntax and documentation for every named function."""
        tree = ast.parse(self.source, filename=str(self.script_path))
        self.assertTrue(ast.get_docstring(tree))
        functions = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.assertTrue(functions)
        for function in functions:
            with self.subTest(function=function.name):
                self.assertTrue(ast.get_docstring(function))

    def test_local_preview_is_limited_to_five_records(self):
        """Preview only five local records without invoking Spark."""
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "input.csv"
            with dataset.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Age", "Income", "Family"])
                writer.writerows((31 + index, 100 + index, 2) for index in range(20))
            output = io.StringIO()
            with redirect_stdout(output):
                self.namespace["preview_local_dataset"](dataset)
            self.assertIn("Columns: Age, Income, Family", output.getvalue())
            self.assertEqual(output.getvalue().count("'Age':"), 5)

    def test_missing_configuration_fails_clearly(self):
        """Reject absent required settings rather than inventing defaults."""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "missing SPARK_MASTER_URL"):
                self.namespace["read_connection_settings"]()

    def test_configuration_strips_whitespace_and_keeps_supplied_ports(self):
        """Read required settings and omit optional ports that are empty."""
        environment = {name: " " + value + " " for name, value in self.settings.items()}
        environment.update({
            "SPARK_DRIVER_PORT": " 32001 ",
            "SPARK_BLOCK_MANAGER_PORT": " ",
        })
        with patch.dict(os.environ, environment, clear=True):
            result = self.namespace["read_connection_settings"]()
        self.assertEqual(result, dict(self.settings, SPARK_DRIVER_PORT="32001"))

    def test_export_is_bounded_and_replaces_existing_preview(self):
        """Limit collection to ten rows and replace the old single CSV."""
        rows = [(31 + index, 100 + index, 2) for index in range(10)]
        frame = Mock()
        frame.columns = ["Age", "Income", "Family"]
        frame.limit.return_value.collect.return_value = rows
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "outputs"
            output_dir.mkdir()
            old_file = output_dir / "filtered_preview.csv"
            old_file.write_text("old result\n", encoding="utf-8")
            result = self.namespace["export_preview"](frame, output_dir)
            self.assertEqual(result, old_file)
            with result.open(newline="", encoding="utf-8") as handle:
                actual = list(csv.reader(handle))
            expected = [frame.columns] + [[str(value) for value in row] for row in rows]
            self.assertEqual(actual, expected)
        frame.limit.assert_called_once_with(10)
        frame.limit.return_value.collect.assert_called_once_with()
        frame.collect.assert_not_called()

    def test_empty_export_creates_directory_and_header(self):
        """Handle an empty filtered result by writing a header-only CSV."""
        frame = Mock()
        frame.columns = ["Age", "Income", "Family"]
        frame.limit.return_value.collect.return_value = []
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "outputs"
            result = self.namespace["export_preview"](frame, output_dir)
            with result.open(newline="", encoding="utf-8") as handle:
                self.assertEqual(list(csv.reader(handle)), [frame.columns])

    def test_main_stops_session_after_success(self):
        """Release the mocked session and announce successful completion."""
        spark = Mock()
        spark.version = "mock-version"
        spark.sparkContext.master = self.settings["SPARK_MASTER_URL"]
        analysis = Mock(return_value=Path("outputs/filtered_preview.csv"))
        output = io.StringIO()
        with patch.dict(self.namespace, self.main_replacements(spark, analysis)):
            with redirect_stdout(output):
                self.namespace["main"]()
        analysis.assert_called_once_with(spark, self.settings, self.script_path.parent)
        spark.stop.assert_called_once_with()
        self.assertIn("Analysis completed successfully.", output.getvalue())

    def test_main_stops_session_after_analysis_failure(self):
        """Release the session on failure without claiming successful completion."""
        spark = Mock()
        analysis = Mock(side_effect=RuntimeError("simulated analysis failure"))
        output = io.StringIO()
        with patch.dict(self.namespace, self.main_replacements(spark, analysis)):
            with redirect_stdout(output):
                with self.assertRaisesRegex(RuntimeError, "simulated analysis failure"):
                    self.namespace["main"]()
        spark.stop.assert_called_once_with()
        self.assertNotIn("Analysis completed successfully.", output.getvalue())

    def test_main_does_not_start_spark_when_configuration_is_missing(self):
        """Keep configuration failure ahead of any Spark startup attempt."""
        replacements = {
            "preview_local_dataset": Mock(),
            "create_spark_session": Mock(),
        }
        with patch.dict(os.environ, {}, clear=True):
            with patch.dict(self.namespace, replacements):
                with self.assertRaisesRegex(RuntimeError, "Workspace preparation is incomplete"):
                    self.namespace["main"]()
        replacements["create_spark_session"].assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
