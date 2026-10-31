"""Offline regression checks for local MPI slot declarations."""
from argparse import Namespace
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "workshop_assets/hpc/MPI/helpers/mpi_start"


class MPIRunnerTests(unittest.TestCase):
    def test_local_slots_match_requested_processes(self):
        run = runpy.run_path(str(RUNNER))["run_exercise"]
        for processes in (2, 4):
            with self.subTest(processes=processes), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "participant code.c"
                source.write_text("participant working source\n")
                compiler = Path(tmp) / "fake mpicc"
                launcher = Path(tmp) / "fake mpirun"
                calls = []

                def execute(command, **kwargs):
                    calls.append(list(command))
                    if command[0] == str(compiler):
                        output = Path(command[command.index("-o") + 1])
                        output.write_text("simulated executable\n")
                        output.chmod(0o755)
                    return 0

                args = Namespace(processes=processes, repeat=1, timeout=10)
                replacements = {
                    "prepared_tools": lambda: (compiler, launcher),
                    "execute": execute,
                }
                with patch.dict(run.__globals__, replacements), \
                        patch("os.geteuid", return_value=1000):
                    self.assertEqual(run(source, args), 0)

                self.assertEqual(len(calls), 2)
                command = calls[1]
                self.assertEqual(command[0], str(launcher))
                self.assertEqual(command[command.index("--host") + 1],
                                 f"localhost:{processes}")
                self.assertEqual(command[command.index("-np") + 1],
                                 str(processes))
                self.assertEqual(command[command.index("--bind-to") + 1], "none")
                self.assertEqual(source.read_text(), "participant working source\n")
                self.assertFalse(Path(command[-1]).parent.exists())
