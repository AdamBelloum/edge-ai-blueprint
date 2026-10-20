"""Render and run the complete seeder with local sh, temporary paths and mocked chown.

No Kubernetes or network access. Does not validate full values YAML, Helm,
Alpine BusyBox behaviour or real ownership changes.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'workshop_assets/cloud_computing_soa/module5_openfaas'


class FullSeedScriptTests(unittest.TestCase):
    def setUp(self):
        text = (ROOT / 'roles/k8s_apps/templates/jhub-values.yaml.j2').read_text()
        marker = '    - name: seed-notebooks\n'
        self.assertEqual(text.count(marker), 1)
        container = text.split(marker, 1)[1]
        self.assertIn('      command: ["sh", "-lc"]', text.split(marker, 1)[1].split('      args:', 1)[0])
        self.source = textwrap.dedent(container.split(
            '      args:\n        - |\n', 1)[1].split('      volumeMounts:\n', 1)[0])
        self.environment = Environment(undefined=StrictUndefined)
        # Test inputs are actual booleans, not Ansible-style strings.
        self.environment.filters['bool'] = bool
        temporary = tempfile.TemporaryDirectory(prefix='full-openfaas-seed-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / 'home'
        self.state = self.root / 'state'
        self.state.mkdir()
        self.seed = self.root / 'seed/cloud-computing-soa/module5'
        self.workspace = self.home / 'Cloud-Computing-SOA/Module-5'
        manifest = json.loads((MODULE / 'delivery-manifest.json').read_text())
        self.paths = [entry['path'] for entry in manifest['files']]

    def render(self, enabled):
        return self.environment.from_string(self.source).render(
            cloud_module5_delivery_enabled=enabled).format(**{})

    def stage(self):
        for relative in self.paths:
            destination = self.seed / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(MODULE / relative, destination)

    def run_seed(self, enabled=True, workshop_type='cloud-computing-soa',
                 module='module5', mode='beginner', solutions='false'):
        for name, value in {'workshop_type': workshop_type, 'workshop_module': module,
                            'mode': mode, 'solutions_released': solutions}.items():
            (self.state / name).write_text(value + '\n')
        script = self.render(enabled).replace('/home/jovyan', str(self.home))
        script = script.replace('/seed', str(self.root / 'seed'))
        script = script.replace('state_dir=/state', 'state_dir=' + str(self.state))
        # Execute all original script logic; mock only privileged ownership changes.
        return subprocess.run(['sh', '-c', 'chown() { :; }\n' + script],
                              cwd=self.root, capture_output=True, text=True, timeout=15)

    def test_complete_script_renders_and_passes_sh_syntax(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                result = subprocess.run(['sh', '-n'], input=self.render(enabled),
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_states_reject_before_home_creation(self):
        cases = [
            ({'enabled': False}, 'delivery is disabled'),
            ({'workshop_type': 'introduction-to-ai'}, 'unsupported workshop type/module combination'),
            ({'module': 'module99'}, 'unsupported workshop module'),
            ({'mode': 'advanced'}, 'requires beginner mode'),
            ({'solutions': 'true'}, 'requires beginner mode'),
        ]
        for settings, expected in cases:
            with self.subTest(settings=settings):
                result = self.run_seed(**settings)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(expected, result.stderr)
                self.assertFalse(self.home.exists())

    def test_missing_source_rejects_before_module5_workspace_creation(self):
        self.stage()
        relative = self.paths[-1]
        (self.seed / relative).unlink()
        result = self.run_seed()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('missing required Module 5 seed file: ' + relative, result.stderr)
        self.assertFalse(self.workspace.exists())
        # The complete seeder may already have created its shared digitafrica directory.
        # This test deliberately does not claim that all home writes are prevented.

    def test_complete_delivery_matches_allowlist_and_preserves_edits(self):
        self.stage()
        result = self.run_seed()
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = self.workspace / 'MODULE5_BEGINNER_SEED_RECEIPT.txt'
        files = {str(p.relative_to(self.workspace))
                 for p in self.workspace.rglob('*') if p.is_file()}
        self.assertEqual(files, set(self.paths) | {receipt.name})
        for relative in self.paths:
            self.assertEqual((self.workspace / relative).read_bytes(),
                             (self.seed / relative).read_bytes())
        self.assertIn('live readiness NOT VALIDATED', result.stdout)
        edited = self.workspace / 'examples/greeting/handler.js'
        edited.write_text('participant edits\n')
        local = self.workspace / 'config/lab.local.json'
        local.write_text('local configuration sentinel\n')
        original_receipt = receipt.read_bytes()
        result = self.run_seed()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(edited.read_text(), 'participant edits\n')
        self.assertEqual(local.read_text(), 'local configuration sentinel\n')
        self.assertEqual(receipt.read_bytes(), original_receipt)


if __name__ == '__main__':
    unittest.main(verbosity=2)
