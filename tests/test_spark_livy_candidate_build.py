"""Offline candidate-build tests: fake Ansible and rendered path/guard checks."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from jinja2 import Environment, StrictUndefined
import yaml

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'scripts/workshops/big-data/spark/build-livy-image.sh'
PREFLIGHT = ROOT / 'playbooks/tasks/big-data-livy-preflight.yml'


class CandidateBuildWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        helpers = self.root / 'scripts/workshops/big-data/spark'
        helpers.mkdir(parents=True)
        self.helper = helpers / 'build-livy-image.sh'
        shutil.copyfile(HELPER, self.helper)
        library = self.root / 'scripts/workshops/lib'
        library.mkdir()
        (library / 'workshop-context.sh').write_text(
            'load_workshop_context() { WORKSHOP_CONTEXT_REPOSITORY_ROOT="$TEST_REPO"; }\n')
        playbooks = self.root / 'playbooks'
        playbooks.mkdir()
        (playbooks / 'build-big-data-livy-image.yml').write_text('[]\n')
        self.record = self.root / 'arguments.txt'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        mock = self.bin / 'ansible-playbook'
        mock.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$TEST_RECORD"\n')
        mock.chmod(0o755)

    def invoke(self, *options):
        if self.record.exists():
            self.record.unlink()
        env = dict(os.environ, TEST_REPO=str(self.root), TEST_RECORD=str(self.record),
                   DIGITAFRICA_INVENTORY=str(self.root / 'fixture.ini'),
                   DIGITAFRICA_DEPLOYMENT_WORKER_GROUP='tier2_agents')
        env['PATH'] = str(self.bin) + os.pathsep + env.get('PATH', '')
        result = subprocess.run(['bash', str(self.helper), *options], env=env,
                                text=True, capture_output=True, timeout=10)
        args = self.record.read_text().splitlines() if self.record.exists() else []
        return result, args

    def test_default_invocation_remains_canonical(self):
        result, args = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(args, [
            '-i', str(self.root / 'fixture.ini'),
            str(self.root / 'playbooks/build-big-data-livy-image.yml'),
            '--extra-vars', 'big_data_worker_group=tier2_agents'])

    def test_candidate_adds_only_build_candidate_setting(self):
        result, args = self.invoke('--transition-candidate')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(args[-2:], ['--extra-vars', 'big_data_livy_build_candidate=true'])
        self.assertNotIn('--syntax-check', args)

    def test_syntax_check_supports_both_option_orders(self):
        for options in (('--syntax-check', '--transition-candidate'),
                        ('--transition-candidate', '--syntax-check')):
            with self.subTest(options=options):
                result, args = self.invoke(*options)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(args[-1], '--syntax-check')
                self.assertIn('big_data_livy_build_candidate=true', args)

    def test_duplicate_and_unknown_options_do_not_call_ansible(self):
        for options in (('--transition-candidate', '--transition-candidate'),
                        ('--syntax-check', '--syntax-check'),
                        ('--unexpected',)):
            with self.subTest(options=options):
                result, args = self.invoke(*options)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(args, [])

    def test_help_does_not_call_ansible(self):
        result, args = self.invoke('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('compose.livy-transition.yaml', result.stdout)
        self.assertEqual(args, [])


class CandidatePreflightTests(unittest.TestCase):
    def setUp(self):
        self.tasks = yaml.safe_load(PREFLIGHT.read_text())
        self.env = Environment(undefined=StrictUndefined)
        self.env.filters['bool'] = lambda value: value is True or value in ('true', 'yes', '1')
        argv = next(task['ansible.builtin.command']['argv'] for task in self.tasks
                    if task.get('name') == 'Validate and read the staged Compose configuration')
        self.path = argv[argv.index('--file') + 1]
        assertions = self.tasks[0]['ansible.builtin.assert']['that']
        self.guard = next(item for item in assertions
                          if isinstance(item, str) and 'big_data_livy_build_candidate' in item)

    def test_default_preflight_path_is_unchanged(self):
        rendered = self.env.from_string(self.path).render(
            big_data_spark_runtime_host_path='/opt/digitafrica/big-data/runtime/spark')
        self.assertEqual(rendered, '/opt/digitafrica/big-data/runtime/spark/compose.yaml')

    def test_candidate_path_is_fixed_not_user_supplied(self):
        rendered = self.env.from_string(self.path).render(
            big_data_spark_runtime_host_path='/opt/digitafrica/big-data/runtime/spark',
            big_data_livy_build_candidate=True)
        self.assertEqual(rendered,
                         '/opt/digitafrica/big-data/runtime/spark/compose.livy-transition.yaml')

    def test_candidate_requires_build_only_context(self):
        guard = self.env.compile_expression(self.guard)
        self.assertTrue(guard())
        self.assertFalse(guard(big_data_livy_build_candidate=True))
        self.assertFalse(guard(big_data_livy_build_candidate=True,
                               big_data_livy_build_only=False))
        self.assertTrue(guard(big_data_livy_build_candidate=True,
                              big_data_livy_build_only=True))


class CandidateBuildContextTests(unittest.TestCase):
    def setUp(self):
        self.tasks = yaml.safe_load(PREFLIGHT.read_text())
        self.build_tasks = yaml.safe_load(
            (ROOT / 'playbooks/build-big-data-livy-image.yml').read_text()
        )[0]['tasks']
        self.env = Environment(undefined=StrictUndefined)
        self.env.filters['bool'] = lambda value: (
            value is True or value in ('true', 'yes', '1')
        )
        self.context = next(
            task['ansible.builtin.set_fact']['livy_selected_build_context']
            for task in self.tasks
            if task.get('name') == 'Select the fixed Livy build context'
        )

    def test_fixed_context_selection_preserves_default(self):
        root = '/opt/digitafrica/big-data/runtime/spark'
        for settings, suffix in (
            ({}, '/livy-build'),
            ({'big_data_livy_build_candidate': False}, '/livy-build'),
            ({'big_data_livy_build_candidate': True},
             '/livy-transition/livy-build'),
        ):
            with self.subTest(settings=settings):
                rendered = self.env.from_string(self.context).render(
                    big_data_spark_runtime_host_path=root, **settings)
                self.assertEqual(rendered, root + suffix)

    def test_preflight_reads_and_checks_selected_context(self):
        stat = next(task['ansible.builtin.stat'] for task in self.tasks
                    if 'ansible.builtin.stat' in task)
        slurp = next(task['ansible.builtin.slurp'] for task in self.tasks
                     if 'ansible.builtin.slurp' in task)
        self.assertEqual(stat['path'],
                         '{{ livy_selected_build_context }}/{{ item }}')
        self.assertIs(stat['follow'], False)
        self.assertEqual(slurp['src'],
                         '{{ livy_selected_build_context }}/Dockerfile')
        assertions = [
            expression
            for task in self.tasks
            for expression in task.get('ansible.builtin.assert', {}).get('that', [])
        ]
        self.assertIn(
            "livy_build_compose.services['spark-livy'].build.context == livy_selected_build_context",
            assertions)

    def test_actual_build_uses_verified_context_and_remains_build_only(self):
        task = next(
            task for task in self.build_tasks
            if task.get('name') ==
            'Build the explicit local Livy image without starting containers'
        )
        argv = task['ansible.builtin.command']['argv']
        self.assertEqual(argv[:2], ['docker', 'build'])
        self.assertEqual(argv[argv.index('--file') + 1],
                         '{{ livy_selected_build_context }}/Dockerfile')
        self.assertEqual(argv[-1], '{{ livy_selected_build_context }}')
        self.assertIn('--pull=false', argv)
        self.assertIn('--network=none', argv)
        label = argv[argv.index('--label', argv.index('--label') + 1) + 1]
        self.assertEqual(
            label,
            'org.digitafrica.livy.dockerfile-sha512={{ livy_build_files.results[0].stat.checksum }}')
        self.assertEqual(task['when'],
                         "(livy_image_before_build.stdout | trim) == ''")


if __name__ == '__main__':
    unittest.main()
