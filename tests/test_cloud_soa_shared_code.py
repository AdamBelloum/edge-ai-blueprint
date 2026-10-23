"""Cloud Computing SOA Modules 2 and 3 share their service code and grading script.

The Module 3 reference solution runs the Module 2 reference services in
containers, the Module 3 advanced track starts from the Module 2 beginner
services as they are, and both modules use the same grading script. Edit the
first file of each entry below and copy it to the others.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOA = ROOT / "workshop_assets" / "cloud-computing-soa"
MODULE2 = SOA / "module2-microservices"
MODULE3 = SOA / "module3-containerization-orchestration"

COPIES = {
    MODULE2 / "solutions/auth_service/auth.py": [
        MODULE3 / "solutions/containerization/auth_service/auth.py",
        MODULE3 / "solutions/orchestration/auth_service/auth.py",
    ],
    MODULE2 / "solutions/shortener_service/shortener.py": [
        MODULE3 / "solutions/containerization/shortener_service/shortener.py",
        MODULE3 / "solutions/orchestration/shortener_service/shortener.py",
    ],
    MODULE2 / "beginner/auth_service/auth.py": [MODULE3 / "advanced/auth_service/auth.py"],
    MODULE2 / "beginner/shortener_service/shortener.py": [MODULE3 / "advanced/shortener_service/shortener.py"],
    MODULE2 / "beginner/setup_local_keys.sh": [MODULE3 / "advanced/setup_local_keys.sh"],
    MODULE2 / "requirements.lock": [MODULE3 / "advanced/requirements.lock"],
    MODULE2 / "shared/tests/test_microservices.py": [MODULE3 / "shared/tests/test_microservices.py"],
    MODULE2 / "shared/tests/test_ownership_isolation.py": [MODULE3 / "shared/tests/test_ownership_isolation.py"],
    MODULE2 / "shared/tests/read_from.csv": [
        MODULE3 / "shared/tests/read_from.csv",
        SOA / "module1-rest-api/shared/tests/read_from.csv",
    ],
}


class SharedCodeTests(unittest.TestCase):
    maxDiff = None

    def test_copies_are_identical(self):
        different = [
            f"{copy.relative_to(ROOT)} differs from {source.relative_to(ROOT)}"
            for source, copies in COPIES.items()
            for copy in copies
            if copy.read_bytes() != source.read_bytes()
        ]
        self.assertEqual([], different)

    def test_solution_images_listen_publicly_and_keep_data(self):
        # Without these settings the shared code listens on 127.0.0.1 and
        # keeps its data in memory.
        dockerfiles = sorted(MODULE3.glob("solutions/*/*/Dockerfile"))
        self.assertEqual(4, len(dockerfiles))
        for dockerfile in dockerfiles:
            text = dockerfile.read_text(encoding="utf-8")
            with self.subTest(dockerfile=str(dockerfile.relative_to(ROOT))):
                self.assertIn("HOST=0.0.0.0", text)
                self.assertIn("DATA_DIR=/app/data", text)


if __name__ == "__main__":
    unittest.main()
