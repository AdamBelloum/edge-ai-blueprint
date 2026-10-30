"""Offline documentation checks; JSON structure is not full nbformat validation."""
import importlib.util
import inspect
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workshop_assets/big-data/spark/beginner"


def source(cell):
    value = cell.get("source", "")
    return "".join(value) if isinstance(value, list) else value


def normalize(text):
    return re.sub(r"\s+", " ", text.replace("**", "").replace("`", "")).casefold()


class Step2DocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notebook = json.loads((BASE / "02_spark_via_livy.ipynb").read_text(encoding="utf-8"))
        cls.cells = {cell["id"]: cell for cell in cls.notebook["cells"]}
        cls.guides = {
            "notebook": "\n".join(source(cell) for cell in cls.notebook["cells"]),
            "README": (BASE / "README.md").read_text(encoding="utf-8"),
            "participant instructions": (BASE / "participants-instructions.md").read_text(encoding="utf-8"),
        }
        spec = importlib.util.spec_from_file_location("_step2_doc_client", BASE / "02_spark_via_livy.py")
        cls.client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.client)

    def test_notebook_has_18_markdown_cells_and_unique_valid_ids(self):
        cells = self.notebook["cells"]
        self.assertEqual(self.notebook["nbformat"], 4)
        self.assertGreaterEqual(self.notebook["nbformat_minor"], 5)
        self.assertEqual(len(cells), 18)
        self.assertEqual(len(self.cells), len(cells))
        for cell in cells:
            with self.subTest(identifier=cell["id"]):
                self.assertEqual(cell["cell_type"], "markdown")
                self.assertRegex(cell["id"], r"^[A-Za-z0-9_-]{1,64}$")
                self.assertNotIn("execution_count", cell)
                self.assertNotIn("outputs", cell)

    def test_notebook_has_exactly_five_individual_activity_commands(self):
        actual = []
        for cell in self.notebook["cells"]:
            for block in re.findall(r"```bash\n(.*?)\n```", source(cell), re.S):
                actual.extend(re.findall(r"^python3 02_spark_via_livy\.py --activity ([1-5])$", block, re.M))
        self.assertEqual(actual, [str(number) for number in range(1, 6)])
        for number in range(1, 6):
            text = source(self.cells[f"step2-activity{number}"])
            self.assertIn(f"python3 02_spark_via_livy.py --activity {number}", text)
            self.assertIn("### Predict", text)
            self.assertIn("### Observe and reflect", text)

    def test_each_activity_has_an_editable_prediction_observation_reflection_cell(self):
        for number in range(1, 6):
            with self.subTest(activity=number):
                text = source(self.cells[f"step2-activity{number}-answers"])
                self.assertIn("### Your answers", text)
                self.assertIn("Predictions before execution", text)
                self.assertIn("Observed results", text)
                self.assertIn("Explanation and comparison with Step 1", text)
                self.assertEqual(text.count("_Write your answer here._"), 3)
        self.assertIn("save your notebook", normalize(self.guides["notebook"]))

    def test_activity_illustrations_match_current_client_source(self):
        for number in range(1, 6):
            with self.subTest(activity=number):
                blocks = re.findall(r"```python\n(.*?)\n```", source(self.cells[f"step2-activity{number}"]), re.S)
                self.assertEqual(len(blocks), 1)
                expected = "\n\n".join(code.strip() for heading, code in
                                       self.client.analysis_steps("PREPARED_LIVY_DATA_PATH", number))
                if number == 5:
                    expected += "\n\n" + inspect.getsource(self.client.export_preview).strip()
                self.assertEqual(blocks[0], expected)

    def test_all_python_illustrations_compile_without_execution(self):
        blocks = re.findall(r"```python\n(.*?)\n```", self.guides["notebook"], re.S)
        self.assertEqual(len(blocks), 5)
        for number, code in enumerate(blocks, start=1):
            compile(code, f"Step 2 activity {number} illustration", "exec")
        text = normalize(self.guides["notebook"])
        self.assertIn("illustrative placeholder", text)
        self.assertIn("do not run the snippets", text)

    def test_all_guides_include_the_five_supported_activity_commands(self):
        for name, text in self.guides.items():
            with self.subTest(guide=name):
                for number in range(1, 6):
                    self.assertIn(f"python3 02_spark_via_livy.py --activity {number}", text)
                values = re.findall(r"02_spark_via_livy\.py --activity (\d+)", text)
                self.assertTrue(values)
                self.assertTrue(set(values).issubset({"1", "2", "3", "4", "5"}))

    def test_all_guides_identify_full_analysis_as_optional_not_additional(self):
        for name, text in self.guides.items():
            with self.subTest(guide=name):
                self.assertIn("`python3 02_spark_via_livy.py`", text)
                normalized = normalize(text)
                self.assertIn("optional organiser-requested reference", normalized)
                self.assertRegex(normalized, r"not an (?:extra|additional) required submission")

    def test_all_guides_explain_fresh_sessions_and_one_active_group_submission(self):
        for name, text in self.guides.items():
            with self.subTest(guide=name):
                normalized = normalize(text)
                self.assertRegex(normalized, r"(?:fresh|new|separate)(?:\s+\w+){0,4}\s+session")
                self.assertRegex(normalized, r"not between (?:separate )?commands|no dataframe survives into another command")
                self.assertIn("variables", normalized)
                self.assertIn("one active submission per group", normalized)
                self.assertIn("concurrency lock", normalized)

    def test_all_guides_limit_preview_to_exporting_commands(self):
        for name, text in self.guides.items():
            with self.subTest(guide=name):
                normalized = normalize(text)
                if name == "notebook":
                    model = source(self.cells["step2-activity-model"])
                    for number in range(1, 5):
                        self.assertRegex(model, rf"(?m)^\| {number} \|[^\n]*\| No \|$")
                    self.assertRegex(model, r"(?m)^\| 5 \|[^\n]*\| Yes \|$")
                else:
                    self.assertRegex(normalized, r"only (?:step 2 )?activity 5")
                self.assertIn("outputs/02_filtered_preview.csv", text)
                self.assertIn("activities 1–4", normalized)
                self.assertIn("saved:", normalized)
                self.assertIn("replace", normalized)
        activity5 = normalize(source(self.cells["step2-activity5"]))
        self.assertIn("at most ten", activity5)
        self.assertIn("header-only", activity5)
        self.assertIn("json", activity5)
        self.assertIn("http", activity5)
        self.assertIn("no shared remote preview file", activity5)

    def test_all_guides_distinguish_http_404_from_application_shutdown(self):
        for name, text in self.guides.items():
            with self.subTest(guide=name):
                normalized = normalize(text)
                self.assertIn("http 404", normalized)
                self.assertIn("not independent", normalized)
                self.assertIn("application", normalized)
                self.assertIn("executor", normalized)
                self.assertNotIn("session deletion requested; cluster containers remain running.", normalized)
        instructions = self.guides["participant instructions"]
        self.assertIn("Owned-session removal confirmed; cluster containers remain running.", instructions)
        self.assertIn("Analysis completed successfully; temporary managed forwarding has closed.", instructions)

    def test_all_guides_preserve_managed_and_explicit_access_distinction(self):
        for name, text in self.guides.items():
            with self.subTest(guide=name):
                normalized = normalize(text)
                for phrase in ("loopback-only", "sha-256", "one executor", "explicit", "partial"):
                    self.assertIn(phrase, normalized)
                self.assertRegex(normalized, r"not perform(?:ed)?")
                self.assertIn("livy_url", normalized)
                self.assertIn("livy_data_path", normalized)

    def test_all_guides_do_not_claim_new_session_resource_limits(self):
        for name, text in self.guides.items():
            with self.subTest(guide=name):
                normalized = normalize(text)
                self.assertIn("{'kind': 'pyspark'}", text)
                self.assertRegex(normalized, r"adds? no resource limits")
                self.assertIn("organiser", normalized)

    def test_all_guides_keep_participant_validation_and_permission_limits(self):
        for name, text in self.guides.items():
            with self.subTest(guide=name):
                normalized = normalize(text)
                self.assertIn("unvalidated", normalized)
                self.assertIn("approval", normalized)
                self.assertIn("do not", normalized)
                self.assertIn("cleanup", normalized)
                self.assertIn("before", normalized)

    def test_step1_assets_and_guided_markdown_notebook_remain_present(self):
        for name in ("01_spark_basics.py", "spark_direct_submit.py", "STEP1-DIRECT-SUBMISSION.md"):
            self.assertTrue((BASE / name).is_file())
        notebook = json.loads((BASE / "01_spark_basics.ipynb").read_text(encoding="utf-8"))
        self.assertTrue(notebook["cells"])
        self.assertTrue(all(cell["cell_type"] == "markdown" for cell in notebook["cells"]))


if __name__ == "__main__":
    unittest.main()
