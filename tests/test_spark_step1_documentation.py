"""Offline Step 1 documentation/launcher contract tests; no SSH or Spark."""
import ast
import json
from pathlib import Path
import re
import shlex
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'workshop_assets/big-data/spark/beginner'


def normalise(text):
    return re.sub(r'\s+', ' ', text.replace('**', '')).lower()


class Step1DocumentationTests(unittest.TestCase):
    def setUp(self):
        self.notebook = json.loads((BASE / '01_spark_basics.ipynb').read_text())
        self.docs = {
            'guide': (BASE / 'STEP1-DIRECT-SUBMISSION.md').read_text(),
            'readme': (BASE / 'README.md').read_text().split('## Prepared connection — Step 2')[0],
            'instructions': (BASE / 'participants-instructions.md').read_text().split('## Step 2 — Spark through Livy')[0],
            'notebook': '\n'.join(''.join(c['source']) for c in self.notebook['cells']),
            'script-docstring': ast.get_docstring(ast.parse((BASE / '01_spark_basics.py').read_text())),
        }

    def test_step1_notebook_remains_markdown_only(self):
        self.assertEqual(len(self.notebook['cells']), 18)
        self.assertTrue(all(c['cell_type'] == 'markdown' for c in self.notebook['cells']))

    def test_notebook_contains_five_guided_terminal_activities(self):
        cells = self.notebook['cells']
        for activity in range(1, 6):
            with self.subTest(activity=activity):
                activity_cells = [
                    cell for cell in cells
                    if cell.get('id') == f'step1-activity{activity}'
                ]
                self.assertEqual(len(activity_cells), 1)
                text = ''.join(activity_cells[0]['source'])
                self.assertIn(f'## Activity {activity} —', text)
                self.assertIn('### Predict', text)
                self.assertIn('### Copy to the terminal', text)
                self.assertIn('### Observe', text)
                self.assertIn('```python', text)
                self.assertEqual(
                    text.count(f'python3 spark_direct_submit.py analyse --activity {activity}'),
                    1,
                )
                answer_cells = [
                    cell for cell in cells
                    if cell.get('id') == f'step1-activity{activity}-answers'
                ]
                self.assertEqual(len(answer_cells), 1)
                self.assertEqual(answer_cells[0]['cell_type'], 'markdown')
                self.assertIn('### Your answers', ''.join(answer_cells[0]['source']))

    def test_entry_guides_direct_participants_to_numbered_activities(self):
        from pathlib import Path
        base = Path(__file__).resolve().parents[1] / 'workshop_assets/big-data/spark/beginner'
        for name in ('README.md', 'participants-instructions.md'):
            with self.subTest(document=name):
                text = (base / name).read_text()
                normalised = ' '.join(text.lower().split())
                self.assertIn('follow the five numbered activities', normalised)
                self.assertIn('read → predict → run → observe → record → reflect', normalised)
                self.assertIn('optional organiser-requested reference', normalised)
                self.assertIn('python3 spark_direct_submit.py analyse --activity', text)
        participant_text = (base / 'participants-instructions.md').read_text()
        for activity in range(1, 6):
            self.assertEqual(
                participant_text.count(f'python3 spark_direct_submit.py analyse --activity {activity}'),
                1,
            )

    def test_all_step1_documents_use_existing_launcher_commands(self):
        for name, text in self.docs.items():
            with self.subTest(document=name):
                self.assertIn('python3 spark_direct_submit.py test', text)
                self.assertIn('python3 spark_direct_submit.py analyse', text)

    def test_no_document_claims_participant_execution_is_validated(self):
        for name, text in self.docs.items():
            with self.subTest(document=name):
                self.assertRegex(normalise(text), r'participant execution (?:is not yet validated|remains unvalidated)')

    def test_all_documents_warn_against_concurrent_group_submissions(self):
        for name, text in self.docs.items():
            with self.subTest(document=name):
                self.assertIn('one active submission per group', normalise(text))
                self.assertIn('outputs/remote-<unique-id>/filtered_preview.csv', text)

    def test_main_guides_describe_managed_credential_path(self):
        for name in ('guide', 'readme', 'instructions', 'notebook'):
            with self.subTest(document=name):
                self.assertIn('~/.ssh/spark-direct/', self.docs[name])

    def test_launcher_declares_documented_subcommands(self):
        tree = ast.parse((BASE / 'spark_direct_submit.py').read_text())
        commands = {
            node.args[0].value for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'add_parser' and node.args
            and isinstance(node.args[0], ast.Constant)
        }
        self.assertTrue({'test', 'analyse'}.issubset(commands))

    def test_documented_remote_command_bounds_match_launcher(self):
        # Evaluate ONLY the pure command-string builders, not launcher main/imports.
        tree = ast.parse((BASE / 'spark_direct_submit.py').read_text())
        expected = {'sparkpi_command', 'analysis_command', 'spark_logging_options'}
        builders = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name in expected]
        self.assertEqual({node.name for node in builders}, expected)
        namespace = {'shlex': shlex}
        exec(compile(ast.Module(body=builders, type_ignores=[]), '<command-builders>', 'exec'), namespace)
        for name, timeout in (('sparkpi_command', 120), ('analysis_command', 300)):
            command = namespace[name]() if name == 'sparkpi_command' else namespace[name]('01_spark_basics.py')
            self.assertIn(f'timeout {timeout} spark-submit', command)
            for flag in ('--deploy-mode client', '--total-executor-cores 1',
                         '--executor-memory 512m', '--driver-memory 512m'):
                self.assertIn(flag, command)

    def test_step2_documents_and_assets_remain_present(self):
        self.assertIn('## Prepared connection — Step 2', (BASE / 'README.md').read_text())
        self.assertIn('## Step 2 — Spark through Livy', (BASE / 'participants-instructions.md').read_text())
        self.assertTrue((BASE / '02_spark_via_livy.py').is_file())
        notebook = json.loads((BASE / '02_spark_via_livy.ipynb').read_text())
        self.assertTrue(notebook['cells'])
        self.assertTrue(all(c['cell_type'] == 'markdown' for c in notebook['cells']))


if __name__ == '__main__':
    unittest.main()
