"""Stage 1 context-boundary regression tests; all helpers are mocked.

Requires the existing test_spark_stage1_menu.py harness. No deployment,
credentials, account changes, or live Spark actions are performed.
"""
import shlex
import unittest

import test_spark_stage1_menu as stage1_menu


class Stage1ContextForwardingTests(unittest.TestCase):
    def setUp(self):
        self.harness = stage1_menu.Stage1MenuTests(methodName="runTest")
        self.harness.setUp()
        self.addCleanup(self.harness.doCleanups)
        self.context = {
            "DIGITAFRICA_INVENTORY": str(self.harness.root / "fixture.ini"),
            "DIGITAFRICA_DEPLOYMENT_GROUP": "tier2_server",
            "DIGITAFRICA_DEPLOYMENT_WORKER_GROUP": "tier2_agents",
            "DIGITAFRICA_NAMESPACE": "spark-pilot-7",
        }
        self.checks = "\n".join(
            '[[ "${' + name + ':-}" == ' + shlex.quote(value) + ' ]] || exit 92'
            for name, value in self.context.items()
        )
        helper = self.harness.helpers / "participant-credentials.sh"
        original = helper.read_text()
        self.assertTrue(original.startswith("#!/usr/bin/env bash\n"))
        helper.write_text(
            "#!/usr/bin/env bash\n" + self.checks + "\n"
            + original.split("\n", 1)[1]
        )

    def invoke_unexported(self, action, **settings):
        names = " ".join(self.context)
        entry = (
            "export -n " + names + "\n"
            "readonly " + names + "\n"
            "if " + action + "; then context_test_rc=0; "
            "else context_test_rc=$?; fi\n"
            + self.checks + "\n"
            "for name in " + names + "; do\n"
            '  declaration="$(declare -p "$name")"\n'
            '  [[ "$declaration" == "declare -r "* ]] || exit 93\n'
            "done\n"
            'exit "$context_test_rc"\n'
        )
        return self.harness.invoke(entry, **{**self.context, **settings})

    def test_plan_and_apply_receive_readonly_unexported_context(self):
        result, calls = self.invoke_unexported("big_data_spark_stage1_action credentials")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [
            "guard:big-data", "cohort:require-complete",
            "credentials:plan", "credentials:apply",
        ])

    def test_publication_verify_receives_readonly_unexported_context(self):
        result, calls = self.invoke_unexported(
            "big_data_spark_activate_selected_mode beginner"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [
            "cohort:require-complete", "guard:big-data", "credentials:verify",
            "confirm:publication", "publish-assets", "remote-state", "reconcile",
        ])

    def test_failed_plan_still_blocks_apply(self):
        result, calls = self.invoke_unexported(
            "big_data_spark_stage1_action credentials", MOCK_PLAN_RC="17"
        )
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual(calls, [
            "guard:big-data", "cohort:require-complete", "credentials:plan",
        ])
        self.assertNotIn("Credential staging completed", result.stdout)

    def test_failed_verify_still_blocks_publication(self):
        result, calls = self.invoke_unexported(
            "big_data_spark_stage1_action publish", MOCK_VERIFY_RC="19"
        )
        self.assertEqual(result.returncode, 19, result.stderr)
        self.assertEqual(calls, [
            "cohort:require-complete", "guard:big-data", "credentials:verify",
        ])
        self.assertNotIn("publication completed", result.stdout)


if __name__ == "__main__":
    unittest.main()
