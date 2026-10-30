"""Render-only tests for the dormant Livy SSH gateway.

These tests exercise Jinja/YAML configuration, not Docker, effective sshd
configuration, runtime transitions, teardown or participant connectivity.
Save as tests/test_spark_livy_access_template.py.
"""
from pathlib import Path
import unittest

from ansible.plugins.filter.core import to_bool
from jinja2 import Environment, FileSystemLoader, StrictUndefined
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/big_data_spark_runtime"


class LivyAccessTemplateTests(unittest.TestCase):
    """Check the enabled gateway without performing infrastructure operations."""

    @classmethod
    def setUpClass(cls):
        cls.defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        cls.environment = Environment(
            loader=FileSystemLoader(str(ROLE / "templates")),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        cls.environment.filters["bool"] = to_bool
        cls.template = cls.environment.get_template("compose.yaml.j2")

    def render(self, gateway=False, direct=False, livy=True):
        settings = dict(self.defaults)
        settings.update(
            big_data_livy_access_enabled=gateway,
            big_data_spark_client_enabled=direct,
            big_data_livy_enabled=livy,
            big_data_spark_worker_count=1,
            big_data_spark_client_bind_ip="192.0.2.10",
        )
        return yaml.safe_load(self.template.render(**settings))

    def gateway(self):
        return self.render(gateway=True)["services"]["spark-livy-access"]

    def test_default_is_disabled_and_baseline_services_remain(self):
        self.assertIs(self.defaults["big_data_livy_access_enabled"], False)
        services = self.render()["services"]
        self.assertNotIn("spark-livy-access", services)
        self.assertEqual(set(services), {"spark-master", "spark-worker-1", "spark-livy"})

    def test_disabled_access_does_not_add_access_network(self):
        compose = self.render(gateway=False, direct=False, livy=False)
        self.assertNotIn("spark-access", compose["networks"])
        self.assertNotIn("spark-livy-access", compose["services"])

    def test_gateway_requires_explicit_profile_and_uses_existing_image(self):
        gateway = self.gateway()
        self.assertEqual(gateway["profiles"], ["participant-livy"])
        self.assertEqual(gateway["depends_on"], ["spark-livy"])
        self.assertEqual(gateway["image"], self.defaults["big_data_spark_client_image"])
        self.assertNotIn("build", gateway)
        self.assertEqual(gateway["pull_policy"], "never")

    def test_gateway_reuses_direct_endpoint_without_rest_publication(self):
        # Render both definitions for comparison only. They must not run together.
        compose = self.render(gateway=True, direct=True)
        services = compose["services"]
        self.assertEqual(services["spark-client"]["ports"], services["spark-livy-access"]["ports"])
        self.assertEqual(services["spark-livy-access"]["ports"], ["192.0.2.10:2222:2222"])
        self.assertNotIn("ports", services["spark-livy"])

    def test_forwarding_is_restricted_and_sessions_are_disabled(self):
        command = self.gateway()["command"]
        self.assertEqual(command[:5], ["/usr/sbin/sshd", "-D", "-e", "-f", "/etc/ssh/workshop_sshd_config"])
        tail = command[5:]
        self.assertEqual(len(tail) % 2, 0)
        self.assertTrue(all(tail[index] == "-o" for index in range(0, len(tail), 2)))
        options = tail[1::2]
        self.assertEqual(len(options), len(set(options)))
        self.assertEqual(set(options), {
            "AllowTcpForwarding=local",
            "AllowStreamLocalForwarding=no",
            "PermitOpen=spark-livy:8998",
            "PermitListen=none",
            "MaxSessions=0",
            "AllowAgentForwarding=no",
            "PermitTunnel=no",
            "GatewayPorts=no",
            "X11Forwarding=no",
            "PermitTTY=no",
        })

    def test_gateway_mounts_only_existing_readonly_ssh_server_inputs(self):
        mounts = self.gateway()["volumes"]
        expected = {
            "/etc/ssh/workshop_host_key": "/client-access/host_key",
            "/etc/ssh/workshop_authorized_keys": "/client-access/login_key.pub",
        }
        self.assertEqual(len(mounts), len(expected))
        self.assertEqual({mount["target"] for mount in mounts}, set(expected))
        for mount in mounts:
            self.assertEqual(mount["type"], "bind")
            self.assertIs(mount["read_only"], True)
            self.assertIs(mount["bind"]["create_host_path"], False)
            self.assertEqual(mount["source"], self.defaults["big_data_spark_runtime_host_path"] + expected[mount["target"]])

    def test_gateway_has_small_limits_and_inherited_security_controls(self):
        gateway = self.gateway()
        self.assertEqual(gateway["mem_limit"], "128m")
        self.assertEqual(gateway["cpus"], 0.25)
        self.assertEqual(gateway["cap_drop"], ["ALL"])
        self.assertEqual(gateway["cap_add"], ["SETUID", "SETGID", "SYS_CHROOT"])
        self.assertEqual(gateway["security_opt"], ["no-new-privileges:true"])
        self.assertEqual(gateway["restart"], "no")
        self.assertEqual(gateway["labels"]["org.digitafrica.managed-by"], "organiser")

    def test_access_network_is_not_attached_to_shared_spark_services(self):
        compose = self.render(gateway=True)
        self.assertEqual(compose["services"]["spark-livy-access"]["networks"], ["spark-private", "spark-access"])
        for name in ("spark-master", "spark-worker-1", "spark-livy"):
            self.assertEqual(compose["services"][name]["networks"], ["spark-private"])
        self.assertIs(compose["networks"]["spark-private"]["internal"], True)
        self.assertIs(compose["networks"]["spark-access"]["internal"], False)

    def test_step1_image_keeps_forwarding_disabled(self):
        dockerfile = (ROLE / "templates/client.Dockerfile.j2").read_text()
        self.assertIn("AllowTcpForwarding no", dockerfile)


if __name__ == "__main__":
    unittest.main()
