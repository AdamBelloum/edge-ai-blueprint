"""Offline compilation checks for independent workshop hook includes.

Uses the existing shared test renderer. No workshop activation, cluster
access, or simultaneous workshop execution.
"""
import unittest

from test_spark_workspace_hook import CURRENT, load_hook


class WorkshopHookBoundaryTests(unittest.TestCase):
    def test_neutral_configuration_compiles(self):
        load_hook(CURRENT)

    def test_spark_alone_compiles(self):
        load_hook(CURRENT, enabled=True)

    def test_module5_alone_compiles(self):
        load_hook(CURRENT, module5=True)

    def test_hpc_alone_compiles(self):
        load_hook(CURRENT, hpc=True, runtime=True)

    def test_hpc_workspace_without_runtime_compiles(self):
        load_hook(CURRENT, hpc=True)

    def test_hpc_runtime_without_workspace_compiles(self):
        load_hook(CURRENT, runtime=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
