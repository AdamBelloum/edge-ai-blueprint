"""Offline tests of Module 3 remote endpoint-output handling; no cluster access."""
import os
import re
import subprocess
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
RUNTIME = REPOSITORY / "scripts/workshops/cloud-computing-soa/module3-runtime.sh"
MARKER_LITERAL = "'MODULE3_REMOTE_END'"
ENDPOINT_START = "printf 'AUTH_ENDPOINT=%s"
AUTH = "10.42.1.1:5001"
SHORTENER = "10.42.1.1:5000"


def runtime_text():
    return RUNTIME.read_text()


def extractor_source():
    match = re.search(
        r"^cloud_module3_runtime_endpoint_value\(\) \{\n.*?^\}\n",
        runtime_text(), re.S | re.M,
    )
    assert match, "extractor function not found"
    return match.group(0)


def remote_tail():
    """Real endpoint printf lines through the final marker of the start branch."""
    text = runtime_text()
    assert text.count(ENDPOINT_START) == 1
    assert text.count(MARKER_LITERAL) == 1
    start = text.rfind("\n", 0, text.index(ENDPOINT_START)) + 1
    marker = text.index(MARKER_LITERAL)
    end = text.index("\n", marker) + 1
    return text[start:end], text[end:]


def run_bash(script, *arguments, extra_env=None):
    environment = os.environ.copy()
    for name in ("BASH_ENV", "ENV"):
        environment.pop(name, None)
    environment.update(extra_env or {})
    return subprocess.run(
        ["bash", "-c", script, "bash", *arguments],
        env=environment, capture_output=True, text=True, timeout=10,
    )


def remote_stdout(snippet):
    result = run_bash(
        snippet,
        extra_env={"AUTH_HOST_PORT": AUTH, "SHORTENER_HOST_PORT": SHORTENER},
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def ansible_view(stdout, stderr=""):
    # Ansible's default callback strips the final stdout newline and appends
    # stderr directly after it.
    return "tier2-worker-1 | CHANGED | rc=0 >>\n" + stdout.rstrip("\n") + stderr


def extract(key, output):
    script = extractor_source() + '\ncloud_module3_runtime_endpoint_value "$1" "$2"\n'
    return run_bash(script, key, output)


COMPOSE_STDERR = "Container m3-containerization-group_01-auth-1 Running\n"
POLICY_LINE = "MODULE3_POLICY_TARGET group_01 172.18.0.2 172.18.0.3\n"


class RemoteEndpointOutputTests(unittest.TestCase):
    def test_marker_keeps_endpoint_lines_intact_with_merged_stderr(self):
        snippet, _ = remote_tail()
        output = ansible_view(POLICY_LINE + remote_stdout(snippet), COMPOSE_STDERR)
        for key, value in (("AUTH_ENDPOINT", AUTH), ("SHORTENER_ENDPOINT", SHORTENER)):
            result = extract(key, output)
            self.assertEqual(result.returncode, 0, output)
            self.assertEqual(result.stdout, value + "\n")

    def test_without_marker_merged_stderr_is_rejected(self):
        snippet, _ = remote_tail()
        unmarked = "".join(
            line for line in snippet.splitlines(keepends=True)
            if MARKER_LITERAL not in line
        )
        output = ansible_view(POLICY_LINE + remote_stdout(unmarked), COMPOSE_STDERR)
        self.assertEqual(extract("AUTH_ENDPOINT", output).returncode, 0)
        self.assertNotEqual(extract("SHORTENER_ENDPOINT", output).returncode, 0)

    def test_extractor_stays_strict(self):
        valid = "AUTH_ENDPOINT=10.42.1.1:5001\n"
        result = extract("AUTH_ENDPOINT", valid)
        self.assertEqual((result.returncode, result.stdout),
                         (0, "10.42.1.1:5001\n"))
        for label, output in (
            ("duplicate", "AUTH_ENDPOINT=a:1\nAUTH_ENDPOINT=a:2\n"),
            ("missing", "SHORTENER_ENDPOINT=a:1\n"),
            ("empty", "AUTH_ENDPOINT=\n"),
            ("whitespace", "AUTH_ENDPOINT=a:1 extra\n"),
            ("equals", "AUTH_ENDPOINT=a=1\n"),
            ("prefixed lookalike", "XAUTH_ENDPOINT=a:1\n"),
            ("indented", " AUTH_ENDPOINT=a:1\n"),
        ):
            with self.subTest(case=label):
                self.assertNotEqual(extract("AUTH_ENDPOINT", output).returncode, 0)

    def test_marker_is_final_output_of_start_branch(self):
        snippet, remainder = remote_tail()
        self.assertEqual(
            remote_stdout(snippet),
            f"AUTH_ENDPOINT={AUTH}\nSHORTENER_ENDPOINT={SHORTENER}\nMODULE3_REMOTE_END\n",
        )
        self.assertTrue(
            remainder.lstrip().startswith('elif [[ "$operation" == "status" ]]'),
            "Start branch must end with the marker line.",
        )


if __name__ == "__main__":
    unittest.main()
