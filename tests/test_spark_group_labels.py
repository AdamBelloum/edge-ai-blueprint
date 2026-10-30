#!/usr/bin/env python3
"""Local regression tests for authorised Spark participant pod labels.

Save as tests/test_spark_group_labels.py and run from the repository root:
    python3 tests/test_spark_group_labels.py

Reuses the existing mocked workspace-hook renderer. Requires Jinja2.
Does not contact Kubernetes, deploy templates, read credentials or test
actual KubeSpawner pod-label rendering or NetworkPolicy enforcement.
"""
from copy import deepcopy
import unittest

import test_spark_workspace_hook as hooks

LABEL = "digitafrica.eu/spark-group"
OTHER_LABEL = "example.org/existing"


class SparkGroupLabelTests(unittest.TestCase):
    def instance(self, **kwargs):
        instance = hooks.spawner(**kwargs)
        instance.extra_labels = {OTHER_LABEL: "preserved"}
        return instance

    def test_oidc_label_uses_authorised_group_not_username(self):
        instance = self.instance(username="alice", groups=("group_02",))
        hooks.run_hook(hooks.load_hook(hooks.CURRENT, enabled=True), instance)
        self.assertEqual(instance.extra_labels, {
            OTHER_LABEL: "preserved", LABEL: "group_02",
        })
        self.assertEqual(instance.environment["GROUP_ID"], "group_02")
        self.assertEqual(
            instance.node_selector["kubernetes.io/hostname"],
            hooks.GROUP_NODES["group_02"],
        )

    def test_legacy_assignment_remains_supported(self):
        instance = self.instance(username="group_02", groups=())
        hooks.run_hook(
            hooks.load_hook(hooks.CURRENT, enabled=True, oidc=False), instance,
        )
        self.assertEqual(instance.extra_labels[LABEL], "group_02")

    def test_absent_extra_labels_is_supported(self):
        instance = hooks.spawner()
        self.assertFalse(hasattr(instance, "extra_labels"))
        hooks.run_hook(hooks.load_hook(hooks.CURRENT, enabled=True), instance)
        self.assertEqual(instance.extra_labels, {LABEL: "group_01"})

    def test_none_extra_labels_is_supported(self):
        instance = hooks.spawner()
        instance.extra_labels = None
        hooks.run_hook(hooks.load_hook(hooks.CURRENT, enabled=True), instance)
        self.assertEqual(instance.extra_labels, {LABEL: "group_01"})

    def test_existing_dictionary_is_not_mutated(self):
        shared = {OTHER_LABEL: "preserved", LABEL: "group_02"}
        before = deepcopy(shared)
        instance = self.instance(groups=("group_01",))
        instance.extra_labels = shared
        hooks.run_hook(hooks.load_hook(hooks.CURRENT, enabled=True), instance)
        self.assertEqual(shared, before)
        self.assertIsNot(instance.extra_labels, shared)
        self.assertEqual(instance.extra_labels, {
            OTHER_LABEL: "preserved", LABEL: "group_01",
        })

    def test_unassigned_admin_has_no_spark_label(self):
        for stale in (False, True):
            with self.subTest(stale=stale):
                instance = self.instance(username="admin", groups=())
                if stale:
                    instance.extra_labels[LABEL] = "group_01"
                hooks.run_hook(
                    hooks.load_hook(hooks.CURRENT, enabled=True), instance,
                )
                self.assertEqual(instance.extra_labels, {OTHER_LABEL: "preserved"})

    def test_rejected_oidc_assignment_clears_stale_label(self):
        for groups in ((), ("group_01", "group_02")):
            for enabled in (False, True):
                with self.subTest(groups=groups, enabled=enabled):
                    instance = self.instance(groups=groups)
                    instance.extra_labels[LABEL] = "group_01"
                    with self.assertRaises(RuntimeError):
                        hooks.run_hook(
                            hooks.load_hook(hooks.CURRENT, enabled=enabled),
                            instance,
                        )
                    self.assertEqual(
                        instance.extra_labels, {OTHER_LABEL: "preserved"},
                    )

    def test_disabled_spark_clears_only_its_stale_label(self):
        instance = self.instance(seed_count=0)
        instance.extra_labels[LABEL] = "group_01"
        hooks.run_hook(hooks.load_hook(hooks.CURRENT, enabled=False), instance)
        self.assertEqual(instance.extra_labels, {OTHER_LABEL: "preserved"})
        self.assertEqual(instance.environment["GROUP_ID"], "group_01")

    def test_disabled_spark_preserves_unrelated_label_dictionary(self):
        instance = self.instance(seed_count=0)
        original = instance.extra_labels
        hooks.run_hook(hooks.load_hook(hooks.CURRENT, enabled=False), instance)
        self.assertIs(instance.extra_labels, original)
        self.assertEqual(instance.extra_labels, {OTHER_LABEL: "preserved"})

    def test_reset_neutral_does_not_assign_spark_label(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                instance = self.instance()
                instance.extra_labels[LABEL] = "group_02"
                hooks.run_hook(
                    hooks.load_hook(hooks.CURRENT, enabled=enabled, neutral=True),
                    instance,
                )
                self.assertEqual(instance.extra_labels, {OTHER_LABEL: "preserved"})

    def test_repeated_hook_reconciles_current_group_label(self):
        instance = self.instance()
        namespace = hooks.load_hook(hooks.CURRENT, enabled=True)
        hooks.run_hook(namespace, instance)
        self.assertEqual(instance.extra_labels[LABEL], "group_01")
        instance.user.groups = [hooks.SimpleNamespace(name="group_02")]
        hooks.run_hook(namespace, instance)
        self.assertEqual(instance.extra_labels, {
            OTHER_LABEL: "preserved", LABEL: "group_02",
        })
        self.assertEqual(
            instance.node_selector["kubernetes.io/hostname"],
            hooks.GROUP_NODES["group_02"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
