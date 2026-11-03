"""Offline canonical group mapping tests; Ansible inventory objects are fake."""
from contextlib import redirect_stdout, redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/workshops/big-data/spark/livy_cohort_scope.py"
spec = importlib.util.spec_from_file_location("tested_livy_cohort_scope", SOURCE)
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)


class CohortScopeTests(unittest.TestCase):
    def test_inventory_order_is_not_sorted(self):
        self.assertEqual(scope.assignments(["worker-z", "worker-a", "worker-m"]), [
            {"group_id": "group_01", "worker": "worker-z"},
            {"group_id": "group_02", "worker": "worker-a"},
            {"group_id": "group_03", "worker": "worker-m"}])

    def test_one_worker_is_one_group(self):
        self.assertEqual(scope.assignments(["only-worker"]),
                         [{"group_id": "group_01", "worker": "only-worker"}])

    def test_group_ids_match_existing_percent_02d_convention(self):
        records = scope.assignments([f"worker-{i}" for i in range(100)])
        self.assertEqual(records[8]["group_id"], "group_09")
        self.assertEqual(records[98]["group_id"], "group_99")
        self.assertEqual(records[99]["group_id"], "group_100")

    def test_empty_duplicate_and_nonsequence_inputs_are_refused(self):
        for names in ([], None, "worker-a", ("worker-a",),
                      ["worker-a", "worker-a"]):
            with self.subTest(names=names), self.assertRaises(scope.ScopeError):
                scope.assignments(names)

    def test_patterns_options_and_unsafe_aliases_are_refused(self):
        for name in (None, 1, "", "-host", "vm*", "vm1:vm2", "vm1,vm2",
                     "vm1 vm2", "vm1\nvm2", "$(false)", "../vm1"):
            with self.subTest(name=name), self.assertRaises(scope.ScopeError):
                scope.assignments([name])

    def fake_ansible(self, names, *, group_exists=True, ambiguous=False):
        loader = Mock()
        inventory = Mock()
        group = Mock()
        group.get_hosts.return_value = [Mock(get_name=Mock(return_value=name))
                                        for name in names]
        inventory.groups = {"workers": group} if group_exists else {}
        if ambiguous:
            inventory.groups[names[0]] = Mock()
        loader_factory = Mock(return_value=loader)
        manager_factory = Mock(return_value=inventory)
        modules = {}
        for name in ("ansible", "ansible.inventory", "ansible.parsing"):
            module = types.ModuleType(name)
            module.__path__ = []
            modules[name] = module
        manager = types.ModuleType("ansible.inventory.manager")
        manager.InventoryManager = manager_factory
        modules[manager.__name__] = manager
        dataloader = types.ModuleType("ansible.parsing.dataloader")
        dataloader.DataLoader = loader_factory
        modules[dataloader.__name__] = dataloader
        return modules, loader, manager_factory, group

    def test_resolver_uses_canonical_group_get_hosts_and_exact_source(self):
        modules, loader, factory, group = self.fake_ansible(["vm-z", "vm-a"])
        with patch.dict(sys.modules, modules):
            records = scope.resolve_assignments("inventory.ini", "workers")
        self.assertEqual([record["worker"] for record in records], ["vm-z", "vm-a"])
        factory.assert_called_once_with(loader=loader, sources=["inventory.ini"])
        group.get_hosts.assert_called_once_with()
        loader.cleanup_all_tmp_files.assert_called_once_with()

    def test_missing_empty_and_ambiguous_groups_fail_without_a_fallback(self):
        for names, options in ((["vm1"], {"group_exists": False}),
                               ([], {}), (["vm1"], {"ambiguous": True})):
            with self.subTest(names=names, options=options):
                modules, loader, _, _ = self.fake_ansible(names, **options)
                with patch.dict(sys.modules, modules), self.assertRaises(scope.ScopeError):
                    scope.resolve_assignments("inventory.ini", "workers")
                loader.cleanup_all_tmp_files.assert_called_once_with()

    def test_invalid_group_and_inventory_are_refused_before_loading(self):
        modules, _, factory, _ = self.fake_ansible(["vm1"])
        for inventory, group in (("inventory.ini", "workers:all"),
                                  ("inventory.ini", "-workers"),
                                  ("inventory.ini", ""), ("", "workers")):
            with self.subTest(inventory=inventory, group=group):
                with patch.dict(sys.modules, modules), self.assertRaises(scope.ScopeError):
                    scope.resolve_assignments(inventory, group)
        factory.assert_not_called()

    def test_cli_emits_only_public_plan_with_no_readiness_claim(self):
        output, errors = io.StringIO(), io.StringIO()
        records = scope.assignments(["vm-z", "vm-a"])
        with patch.object(scope, "resolve_assignments", return_value=records), \
                redirect_stdout(output), redirect_stderr(errors):
            rc = scope.main(["inventory.ini", "workers"])
        self.assertEqual(rc, 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan, {"status": "PLANNED", "scope": "all-groups",
                                "runtime_readiness": "NOT_VERIFIED", "groups": records})
        self.assertEqual(errors.getvalue(), "")

    def test_cli_blocks_without_printing_private_exception_details(self):
        for error in (RuntimeError("PRIVATE-TOKEN"), ImportError("PRIVATE-TOKEN"),
                      scope.ScopeError("No workshop machines.")):
            with self.subTest(error=type(error).__name__):
                output, errors = io.StringIO(), io.StringIO()
                with patch.object(scope, "resolve_assignments", side_effect=error), \
                        redirect_stdout(output), redirect_stderr(errors):
                    rc = scope.main(["inventory.ini", "workers"])
                self.assertEqual(rc, 2)
                self.assertEqual(output.getvalue(), "")
                self.assertIn("BLOCKED:", errors.getvalue())
                self.assertNotIn("PRIVATE-TOKEN", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
