"""The Cloud Computing SOA TA audit stays with the TAs, and CHECKS.md matches it.

workshop_assets/cloud-computing-soa/ta-audit/ holds the scripts that teaching
assistants run against students' submissions to Assignments 1-3. Deployment
code may only read the module folders next to it, so the audit never reaches
the central server or a participant. CHECKS.md lists every check and is
generated from the scripts by `python audit_common.py`.
"""
import importlib
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COURSE = "workshop_assets/cloud-computing-soa"
AUDIT = ROOT / COURSE / "ta-audit"
COURSE_PATH = re.compile(re.escape(COURSE) + r"(?:/[^\s'\"]*)?")


def delivery_files():
    """Files that decide what reaches the central server and the participants."""
    for pattern in ("roles/**/*.yml", "roles/**/*.j2", "roles/**/*.sh", "playbooks/**/*.yml",
                    "scripts/**/*.sh", "scripts/**/*.py", "workshop_assets/**/asset-map.tsv"):
        yield from ROOT.glob(pattern)


def audit_modules():
    """The three audit scripts, imported without writing caches into the repository."""
    try:
        import requests  # noqa: F401  (the audit scripts need it)
    except ImportError:
        raise unittest.SkipTest("requests is not installed")
    sys.path.insert(0, str(AUDIT))
    written = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        return [importlib.import_module(name) for name in ("audit_common", "audit_a1", "audit_a2", "audit_a3")]
    finally:
        sys.dont_write_bytecode = written
        sys.path.remove(str(AUDIT))


class DeliveryTests(unittest.TestCase):
    def test_deployment_code_reads_only_module_folders(self):
        found = []
        for path in delivery_files():
            for match in COURSE_PATH.findall(path.read_text(encoding="utf-8", errors="replace")):
                if not match.startswith(f"{COURSE}/module"):
                    found.append(f"{path.relative_to(ROOT)}: {match}")
        self.assertEqual([], found)

    def test_deployment_code_never_names_the_audit(self):
        found = [str(path.relative_to(ROOT)) for path in delivery_files()
                 if "ta-audit" in path.read_text(encoding="utf-8", errors="replace")]
        self.assertEqual([], found)


class CatalogueTests(unittest.TestCase):
    def test_check_ids_are_unique_and_failures_explained(self):
        _, audit_a1, audit_a2, audit_a3 = audit_modules()
        for name, checks in (("A1", audit_a1.CHECKS), ("A2", audit_a2.CHECKS),
                             ("A3", audit_a3.CHECKS_31 + audit_a3.CHECKS_32)):
            ids = [check.id for check in checks]
            with self.subTest(assignment=name):
                self.assertEqual(sorted(set(ids)), sorted(ids))
                unexplained = [check.id for check in checks
                               if check.severity in ("FAIL", "WARN") and not (check.why and check.ask)]
                self.assertEqual([], unexplained)

    def test_checks_md_is_up_to_date(self):
        audit_common = audit_modules()[0]
        self.assertEqual(audit_common.catalogue(), (AUDIT / "CHECKS.md").read_text(encoding="utf-8"),
                         "run python audit_common.py in workshop_assets/cloud-computing-soa/ta-audit")


if __name__ == "__main__":
    unittest.main()
