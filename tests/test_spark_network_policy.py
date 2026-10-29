"""Unit tests for Spark direct-access NetworkPolicy generation.

Run from the repository root:
    python3 tests/test_spark_network_policy.py
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "spark_network_policy",
    ROOT / "scripts/workshops/big-data/spark/spark_network_policy.py",
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

BIND = "145.100.135.172"
NAT = (
    "-A POSTROUTING -s 172.29.0.2/32 -d 172.29.0.2/32 -p tcp -m tcp --dport 2222 -j MASQUERADE\n"
    f"-A DOCKER -d {BIND}/32 ! -i br-d617e7c53ba1 -p tcp -m tcp --dport 2222 "
    "-j DNAT --to-destination 172.29.0.2:2222\n"
)


def request(nat=NAT, group="group_01", bind=BIND):
    return {
        "namespace": "digitafrica",
        "groups": [{"group_id": group, "worker": "tier2-worker-1",
                    "bind_ip": bind, "nat_text": nat}],
    }


class DestinationTests(unittest.TestCase):
    def test_reads_post_dnat_destination(self):
        self.assertEqual(module.parse_dnat_destination(NAT, BIND), "172.29.0.2")

    def test_identical_duplicate_rules_are_accepted(self):
        self.assertEqual(module.parse_dnat_destination(NAT + NAT, BIND), "172.29.0.2")

    def test_masquerade_alone_is_not_a_destination(self):
        with self.assertRaises(ValueError):
            module.parse_dnat_destination(NAT.splitlines()[0], BIND)

    def test_other_bind_address_is_not_matched(self):
        with self.assertRaises(ValueError):
            module.parse_dnat_destination(NAT, "145.100.135.241")

    def test_conflicting_destinations_are_rejected(self):
        other = NAT.replace("172.29.0.2:2222", "172.28.0.4:2222").splitlines()[1]
        with self.assertRaises(ValueError):
            module.parse_dnat_destination(NAT + other + "\n", BIND)

    def test_public_loopback_and_wrong_port_targets_are_rejected(self):
        for target in ("8.8.8.8:2222", "127.0.0.1:2222", "172.29.0.2:22"):
            text = NAT.replace("172.29.0.2:2222", target)
            with self.assertRaises(ValueError, msg=target):
                module.parse_dnat_destination(text, BIND)


class PolicyTests(unittest.TestCase):
    def test_policy_is_narrow_and_labelled_for_cleanup(self):
        plan = module.build_plan(request())
        policy = plan["policies"][0]
        self.assertEqual(policy["metadata"]["name"], "digitafrica-spark-direct-group-01")
        self.assertEqual(policy["metadata"]["labels"], module.MANAGED_LABELS)
        spec = policy["spec"]
        self.assertEqual(spec["policyTypes"], ["Egress"])
        self.assertEqual(spec["podSelector"]["matchLabels"]["digitafrica.eu/spark-group"], "group_01")
        self.assertEqual(spec["egress"], [{
            "to": [{"ipBlock": {"cidr": "172.29.0.2/32"}}],
            "ports": [{"protocol": "TCP", "port": 2222}],
        }])
        self.assertEqual(plan["summary"][0]["destination"], "172.29.0.2")

    def test_invalid_input_is_rejected(self):
        bad = [request(group="alice"), request(bind="not-an-ip"),
               {"namespace": "Bad_NS", "groups": request()["groups"]},
               {"groups": []}]
        for item in bad:
            with self.assertRaises(ValueError):
                module.build_plan(item)

    def test_duplicate_group_is_rejected(self):
        item = request()
        item["groups"].append(dict(item["groups"][0]))
        with self.assertRaises(ValueError):
            module.build_plan(item)

    def test_group_errors_name_the_group(self):
        with self.assertRaisesRegex(ValueError, "group_01"):
            module.build_plan(request(nat=""))


if __name__ == "__main__":
    unittest.main()
