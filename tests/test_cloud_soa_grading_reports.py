"""The --json results of the Cloud Computing SOA grading scripts and TA audit.

Batch grading reads these files, so they must say exactly what the printed
reports say. Uses made-up test outcomes; no services are started.
"""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOA = ROOT / "workshop_assets/cloud-computing-soa"


def load(name, path):
    try:
        import requests  # noqa: F401  (the scripts need it)
    except ImportError:
        raise unittest.SkipTest("requests is not installed")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    written = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # no caches next to the files under test
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = written
    return module


def printed(function, *arguments):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        value = function(*arguments)
    return output.getvalue(), value


class GradingScriptJsonTests(unittest.TestCase):
    def check(self, module, title, rubric, not_tested, outcomes):
        module.NOTES[:] = ["The 100 new ids are 1 to 2 characters long."]
        text, report = printed(module.print_report, types.SimpleNamespace(outcomes=outcomes), title, rubric,
                               not_tested)
        lines = text.splitlines()
        rows = [line for line in lines if line[:2].strip().isdigit() or line.startswith(" -/")]
        self.assertEqual(len(rows), len(report["lines"]) + 1)
        for row, line in zip(rows, report["lines"]):
            earned = " -" if line["status"] == "not checked" else f"{line['earned']:>2}"
            self.assertEqual(row, f"{earned}/{line['points']:<4} {line['line']}")
        self.assertEqual(rows[-1], f"{report['earned']:>2}/{report['possible']:<4} tested by this script")
        for line in report["lines"]:
            for problem in line["problems"]:
                self.assertIn(f"          {problem['outcome']}: {problem['detail'][:160]}", lines)
        self.assertEqual(report["notes"], module.NOTES)
        self.assertEqual(sum(item["points"] for item in report["not_tested"]),
                         sum(points for _, points in not_tested))
        json.dumps(report)  # serialisable as it is
        return report

    def test_assignment_1(self):
        api = load("grading_test_api", SOA / "module1-rest-api/shared/tests/test_api.py")
        outcomes = {name: ("pass", "") for _, _, tests in api.RUBRIC for name in tests}
        report = self.check(api, "A1", api.RUBRIC, api.NOT_TESTED, outcomes)
        self.assertEqual((report["earned"], report["possible"], report["not_checked"]), (12, 12, 0))
        outcomes["TestApi.test_put_id"] = ("fail", "PUT /1 with a valid URL: expected 200,\n got 500")
        outcomes["TestUrlValidation.test_other_input"] = ("error", "AssertionError: cannot connect")
        report = self.check(api, "A1", api.RUBRIC, api.NOT_TESTED, outcomes)
        self.assertEqual((report["earned"], report["possible"]), (10, 12))
        failed = [line for line in report["lines"] if line["status"] == "failed"]
        self.assertEqual([line["line"] for line in failed],
                         ["Methods: PUT /:id (200, 400, 404)", "URL validity: other input, such as \"uva.nl\""])
        self.assertEqual(failed[0]["problems"],
                         [{"outcome": "fail", "detail": "PUT /1 with a valid URL: expected 200, got 500"}])
        # A service decides what the failure messages quote: the JSON keeps their start.
        outcomes["TestApi.test_put_id"] = ("fail", "GET /1: expected 'https://x', got '" + "y" * 10000 + "'")
        report = self.check(api, "A1", api.RUBRIC, api.NOT_TESTED, outcomes)
        self.assertEqual(len(report["lines"][2]["problems"][0]["detail"]), 300)
        # A service that is not running fails every line.
        report = self.check(api, "A1", api.RUBRIC, api.NOT_TESTED,
                            {"setUpModule (grading_test_api)": ("error", "cannot connect")})
        self.assertEqual((report["earned"], report["possible"]), (0, 12))

    def test_assignments_2_and_3_with_lines_not_checked(self):
        microservices = load("grading_test_microservices",
                             SOA / "module2-microservices/shared/tests/test_microservices.py")
        for assignment, (title, rubric, not_tested) in microservices.RUBRICS.items():
            with self.subTest(assignment=assignment):
                outcomes = {name: ("pass", "") for _, _, tests in rubric for name in tests}
                first = rubric[0][2][0]
                outcomes[first] = ("skipped", "pass --restart or --namespace")
                report = self.check(microservices, title, rubric, not_tested, outcomes)
                skipped = [line for line in report["lines"] if line["status"] == "not checked"]
                self.assertEqual(report["not_checked"], sum(line["points"] for line in skipped))
                self.assertEqual(report["possible"] + report["not_checked"],
                                 sum(points for _, points, _ in rubric))
                self.assertEqual(report["earned"], report["possible"])


class AuditJsonTests(unittest.TestCase):
    def test_write_json_lists_every_result(self):
        sys.path.insert(0, str(SOA / "ta-audit"))
        written = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            common = load("audit_common", SOA / "ta-audit/audit_common.py")
        finally:
            sys.dont_write_bytecode = written
            sys.path.remove(str(SOA / "ta-audit"))
        check = common.Check("A1-URL-03", "URL validity", "Rejects bad URLs", "FAIL", "why", "ask", None)
        info = common.Check("A1-ID-01", "Identifiers", "Id scheme", "INFO", "", "", None)
        results = [common.Result(check, "FAIL", problems=["POST / accepted 'www'"], evidence=["POST / -> 201"]),
                   common.Result(info, "INFO", notes=["base 62"])]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "audit.json"
            common.write_json(path, "TA audit, Assignment 1", "Service: x", results)
            data = json.loads(path.read_text())
        self.assertEqual(data["counts"], {"FAIL": 1, "ERROR": 0, "WARN": 0, "INFO": 1, "SKIP": 0, "PASS": 0})
        self.assertEqual([item["id"] for item in data["checks"]], ["A1-ID-01", "A1-URL-03"])
        self.assertEqual(data["checks"][1]["problems"], ["POST / accepted 'www'"])
        self.assertEqual(data["checks"][1]["evidence"], ["POST / -> 201"])
        self.assertEqual((data["checks"][1]["why"], data["checks"][1]["ask"]), ("why", "ask"))
        # The details quote the service: at most 50, of at most 1,000 characters each.
        results[0].problems = ["x" * 5000] * 60
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "audit.json"
            common.write_json(path, "TA audit, Assignment 1", "Service: x", results)
            problems = json.loads(path.read_text())["checks"][1]["problems"]
        self.assertEqual(len(problems), 51)
        self.assertEqual(problems[-1], "... 10 more")
        self.assertEqual({len(problem) for problem in problems[:50]}, {1000})


if __name__ == "__main__":
    unittest.main()
