import json
import os
import re
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/workshops/big-data/spark/module-main.sh'

class ComputationMenuTests(unittest.TestCase):
    def invoke(self, step, host='tier2-worker-1\n', **settings):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            module = directory/'scripts/workshops/big-data/spark'
            module.mkdir(parents=True)
            lib = directory/'scripts/workshops/lib'
            lib.mkdir()
            (lib/'workshop-context.sh').write_text('DIGITAFRICA_DEPLOYMENT_GROUP=unexpected\nload_workshop_context() { return 98; }\n')
            record = directory/'calls'
            for folder in ('step1-direct', 'step2-livy'):
                helper = module/folder/'test-runtime.sh'
                helper.parent.mkdir()
                helper.write_text('#!/usr/bin/env bash\nprintf "run:%s:%s\\n" "$(basename "$(dirname "$0")")" "$*" >> "$RECORD"\nexit "${HELPER_RC:-0}"\n')
                helper.chmod(0o755)
            bin_dir = directory/'bin'
            bin_dir.mkdir()
            inventory = {'all': {'children': ['tier2_agents','outsiders']}, 'tier2_agents': {'children':['workers']}, 'workers': {'hosts':['tier2-worker-1','tier2-worker-2']}, 'outsiders': {'hosts':['other-host']}, '_meta': {'hostvars':{}}}
            command = bin_dir/'ansible-inventory'
            command.write_text('#!/usr/bin/env bash\nprintf \'%s\\n\' ' + shlex.quote(json.dumps(inventory)) + '\nexit "${INVENTORY_RC:-0}"\n')
            command.chmod(0o755)
            env = os.environ.copy()
            env.update(RECORD=str(record), TEST_MODULE=str(module), GUARD_RC='0', CONFIRM_RC='0', HELPER_RC='0', INVENTORY_RC='0', DIGITAFRICA_ASSUME_YES='true', DIGITAFRICA_INVENTORY=str(directory/'hosts.ini'), DIGITAFRICA_DEPLOYMENT_WORKER_GROUP='tier2_agents')
            env['PATH'] = str(bin_dir)+os.pathsep+env['PATH']
            env.update(settings)
            script = 'source '+shlex.quote(str(SOURCE))+r'''
BIG_DATA_SPARK_MODULE_DIR="$TEST_MODULE"
readonly DIGITAFRICA_DEPLOYMENT_GROUP="tier2_agents"
ensure_workshop_activation_allowed() { printf 'guard:%s\n' "$*" >> "$RECORD"; return "$GUARD_RC"; }
confirm() { printf 'confirm:%s\n' "$*" >> "$RECORD"; return "$CONFIRM_RC"; }
'''
            if settings.get('USE_REAL_CONFIRM') == '1':
                common = SOURCE.parents[3] / 'lib/common.sh'
                match = re.search(r'^confirm\(\) \{\n.*?^\}', common.read_text(),
                                  re.MULTILINE | re.DOTALL)
                if match is None:
                    raise AssertionError('Production confirm() definition not found')
                script += '\n' + match.group(0) + '\n'
            script += '\nbig_data_spark_computation_test '+shlex.quote(step)+'\n'
            if settings.get('USE_REAL_CONFIRM') == '1':
                script += r"""
status=$?
printf 'assume_yes_after:%s\n' "$DIGITAFRICA_ASSUME_YES"
exit "$status"
"""
            result = subprocess.run(['bash','-c',script], env=env, input=host, text=True, capture_output=True)
            calls = record.read_text().splitlines() if record.exists() else []
            return result, calls

    def test_readonly_parent_context_is_reused_without_initialisation(self):
        result, calls = self.invoke('direct')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('readonly variable', result.stderr)
        self.assertEqual(calls[-1], 'run:step1-direct:--limit tier2-worker-1')
        self.assertEqual(len(calls), 3)

    def test_exact_hosts_and_distinct_helpers(self):
        for step, folder, host in [('direct','step1-direct','tier2-worker-1'),('livy','step2-livy','tier2-worker-2')]:
            with self.subTest(step=step):
                result, calls = self.invoke(step, host=host+'\n')
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(calls[0],'guard:big-data')
                self.assertIn(' on '+host+';',calls[1])
                self.assertEqual(calls[2],'run:'+folder+':--limit '+host)
                self.assertEqual(len(calls),3)
                self.assertIn('access remain unverified',result.stdout)

    def test_enter_accepts_default_for_both_test_paths(self):
        for step, folder in [('direct', 'step1-direct'), ('livy', 'step2-livy')]:
            with self.subTest(step=step):
                result, calls = self.invoke(step, host='\n')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(' on tier2-worker-1;', calls[1])
                self.assertEqual(calls[-1], 'run:' + folder + ':--limit tier2-worker-1')
                self.assertEqual(len(calls), 3)

    def test_default_requires_membership_and_confirmation(self):
        for settings, expected in [({'DIGITAFRICA_DEPLOYMENT_WORKER_GROUP': 'unknown'}, 2),
                                   ({'CONFIRM_RC': '1'}, 0)]:
            with self.subTest(settings=settings):
                result, calls = self.invoke('direct', host='\n', **settings)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertFalse(any(call.startswith('run:') for call in calls))

    def test_groups_unknown_outside_and_patterns_rejected(self):
        for host in ['', 'all\n','tier2_agents\n','workers\n','other-host\n','unknown\n','tier2-worker-*\n','tier2-worker-1,tier2-worker-2\n','145.100.135.172\n']:
            with self.subTest(host=host):
                result, calls = self.invoke('direct',host=host)
                self.assertEqual(result.returncode,2,result.stderr)
                self.assertEqual(calls,['guard:big-data'])

    def test_guard_inventory_context_and_confirmation_fail_closed(self):
        for settings, expected in [({'GUARD_RC':'23'},23),({'INVENTORY_RC':'7'},2),({'DIGITAFRICA_INVENTORY':''},2),({'DIGITAFRICA_DEPLOYMENT_WORKER_GROUP':'unknown'},2),({'CONFIRM_RC':'1'},0)]:
            with self.subTest(settings=settings):
                result,calls=self.invoke('livy',**settings)
                self.assertEqual(result.returncode,expected,result.stderr)
                self.assertFalse(any(call.startswith('run:') for call in calls))

    def test_helper_failure_propagates_without_success_claim(self):
        result,calls=self.invoke('direct',HELPER_RC='19')
        self.assertEqual(result.returncode,19)
        self.assertEqual(calls[-1],'run:step1-direct:--limit tier2-worker-1')
        self.assertNotIn('completed successfully',result.stdout)
        self.assertIn('before retrying',result.stderr)

    def test_menu_routes_without_live_helpers(self):
        with tempfile.TemporaryDirectory() as name:
            record=Path(name)/'calls'
            env=os.environ.copy()
            env['RECORD']=str(record)
            script='source '+shlex.quote(str(SOURCE))+r'''
workshop_ui_heading() { :; }
workshop_ui_section() { :; }
workshop_ui_option() { :; }
workshop_ui_prompt() { :; }
big_data_spark_computation_test() { printf '%s\n' "$1" >> "$RECORD"; }
run_big_data_spark_menu
'''
            result=subprocess.run(['bash','-c',script],env=env,input='9\n10\n0\n',text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(record.read_text().splitlines(),['direct','livy'])


    def test_real_confirmation_requires_input_and_preserves_auto_yes_setting(self):
        for step, folder in [('direct', 'step1-direct'), ('livy', 'step2-livy')]:
            for response in ('n\n', '\n', '', 'y\n'):
                with self.subTest(step=step, response=response):
                    result, calls = self.invoke(step,
                        host='tier2-worker-1\n' + response,
                        USE_REAL_CONFIRM='1', DIGITAFRICA_ASSUME_YES='true')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    expected = ['guard:big-data']
                    if response == 'y\n':
                        expected.append('run:' + folder + ':--limit tier2-worker-1')
                    self.assertEqual(calls, expected)
                    self.assertIn('assume_yes_after:true', result.stdout)
                    self.assertNotIn('Automatically confirmed', result.stdout)


if __name__=='__main__':
    unittest.main()
