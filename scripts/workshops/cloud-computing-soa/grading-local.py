"""Organiser side of the Cloud Computing SOA grading runs (see grading-main.sh).

    grading-local.py script OPERATION ...   print the remote script for one step
    grading-local.py receive OPERATION ...  read that step's Ansible output
    grading-local.py summary --run-dir DIR  write summary.md and summary.csv

The remote script carries grading-remote.py and a payload; for a start, the
payload holds the files of the grading pods: grading-pod.py, a manifest of the
delivered and reference files, and the grading script or the TA audit from
this checkout. The results are written under DIR, one folder per group.
Standard library only.
"""
import argparse
import base64
import csv
import gzip
import hashlib
import json
import re
import subprocess
import sys
import time
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MODULES = {
    "1": {
        "title": "Module 1 (REST API)", "assignment": "Assignment 1",
        "assets": REPO / "workshop_assets/cloud-computing-soa/module1-rest-api",
        "code": ["app.py"],
        "tests": ["test_api.py", "read_from.csv"],
        "audit": ["audit_common.py", "audit_a1.py"],
    },
    "2": {
        "title": "Module 2 (Microservices and JWT Authentication)", "assignment": "Assignment 2",
        "assets": REPO / "workshop_assets/cloud-computing-soa/module2-microservices",
        "code": ["auth_service/auth.py", "shortener_service/shortener.py"],
        "tests": ["test_microservices.py", "test_ownership_isolation.py", "read_from.csv"],
        "audit": ["audit_common.py", "audit_a1.py", "audit_a2.py"],
    },
}
# The TA audit is not delivered to participants; only grading pods use it, in
# their grader container (tests/test_cloud_soa_grading_remote.py).
AUDIT = REPO / "workshop_assets/cloud-computing-soa/ta-audit"
TRACKS = ("beginner", "intermediate", "advanced")
TIMEOUTS = {"tests": 600, "audit": 2400}  # seconds for the grading script or the audit in a pod
WAIT = 150                                # seconds a pod waits for the group's services
SCRIPT_LIMIT = 95000  # Ansible passes the script, base64-encoded, as one 128 KiB argument
ANSWER_BEGIN, ANSWER_END = "===== GRADING ANSWER BEGIN =====", "===== GRADING ANSWER END ====="
RESULT_FILES = ("prepare.json", "grade.json", "tests.txt", "tests.json", "audit.txt", "audit.md", "audit.json")
GROUP = re.compile(r"^group_\d+$")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def clean(text):
    """Text from the cluster without terminal control characters."""
    return CONTROL.sub("?", str(text))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pack(data):
    return base64.b64encode(gzip.compress(json.dumps(data).encode())).decode()


def bundle(module, kind, audit_dir):
    """The files of the grading pods' ConfigMap: name -> text."""
    spec = MODULES[module]
    folder = spec["assets"] / "shared/tests" if kind == "tests" else audit_dir
    paths = {"grading-pod.py": HERE / "grading-pod.py"}
    paths.update({name: folder / name for name in spec[kind]})
    for name, path in paths.items():
        if not path.is_file():
            hint = " (set CLOUD_SOA_TA_AUDIT_DIR to the TA audit folder)" if kind == "audit" else ""
            fail(f"Missing {path}{hint}")
    files = {name: path.read_text(encoding="utf-8") for name, path in paths.items()}
    manifest = {"delivered": {}, "solution": {}}
    for track in TRACKS:
        manifest["delivered"][track] = {
            code: sha256(spec["assets"] / track / code) for code in spec["code"]
            if (spec["assets"] / track / code).is_file()}
    manifest["solution"] = {code: sha256(spec["assets"] / "solutions" / code) for code in spec["code"]}
    files["manifest.json"] = json.dumps(manifest, indent=2) + "\n"
    return files, paths


def checkout():
    def git(*arguments):
        result = subprocess.run(["git", "-C", str(REPO), *arguments], capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else ""
    return {"commit": git("rev-parse", "HEAD"), "changed": bool(git("status", "--porcelain"))}


def remote_script(payload):
    code = (HERE / "grading-remote.py").read_text(encoding="utf-8")
    script = (f"set -euo pipefail\npython3 - {pack(payload)} <<'GRADING_REMOTE'\n{code}\nGRADING_REMOTE\n")
    if len(script) > SCRIPT_LIMIT:
        fail(f"The grading files are too large to send ({len(script)} bytes, at most {SCRIPT_LIMIT}).")
    return script


def saved_groups(run_dir):
    return sorted(path.parent.name for path in run_dir.glob("group_*/result.json"))


def script(args):
    payload = {"operation": args.operation, "namespace": args.namespace}
    if args.operation == "start":
        run_dir = Path(args.run_dir)
        groups = [group for group in (args.groups or "").replace(" ", "").split(",") if group]
        for group in groups:
            if not GROUP.match(group):
                fail(f"Not a group name: {group!r} (expected group_01 and so on).")
        files, paths = bundle(args.module, args.kind, Path(args.audit_dir) if args.audit_dir else AUDIT)
        run = {"run": args.run, "module": args.module, "track": args.track, "kind": args.kind,
               "parallel": args.parallel, "egress": args.egress, "wait": WAIT, "timeout": TIMEOUTS[args.kind],
               "groups": groups, "image": args.image or ""}
        payload.update(run, bundle=pack(files))
        script_text = remote_script(payload)
        if run_dir.exists():
            fail(f"{run_dir} exists already.")
        run_dir.mkdir(parents=True)
        run_dir.chmod(0o700)  # the groups' code and logs
        record = dict(run, created=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), checkout=checkout(),
                      files={name: {"path": str(path.relative_to(REPO)) if REPO in path.parents else str(path),
                                    "sha256": sha256(path)} for name, path in paths.items()},
                      manifest=json.loads(files["manifest.json"]))
        (run_dir / "run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(script_text)
        return
    if args.operation == "step":
        run = json.loads((Path(args.run_dir) / "run.json").read_text(encoding="utf-8"))
        payload.update(run=run["run"], saved=saved_groups(Path(args.run_dir)))
    elif args.operation == "cleanup":
        payload["run"] = args.run
    print(remote_script(payload))


def answer_of(text):
    """The remote answer in Ansible's output; exit with the remote error if there is none."""
    lines = text.splitlines()
    if ANSWER_BEGIN in lines and ANSWER_END in lines[lines.index(ANSWER_BEGIN):]:
        first = lines.index(ANSWER_BEGIN)
        last = lines.index(ANSWER_END, first)
        try:
            return json.loads(gzip.decompress(base64.b64decode("".join(lines[first + 1:last]))))
        except (ValueError, OSError, EOFError, zlib.error):
            fail("The answer from the control plane is damaged.")
    errors = [line for line in lines if "ERROR" in line or "FAILED" in line or "UNREACHABLE" in line]
    for line in (errors or lines[-15:]):
        print(clean(line), file=sys.stderr)
    fail("The grading step did not complete on the control plane.")


def points(result):
    """'12/12 points' or 'FAIL 2, WARN 3', and the problems, from a saved result."""
    summary = (result.get("results") or {}).get("summary") or {}
    files = (result.get("results") or {}).get("files") or {}
    kind = summary.get("kind")
    try:
        if kind == "tests" and "tests.json" in files:
            report = json.loads(files["tests.json"])
            failed = [line["line"] for line in report["lines"] if line["status"] == "failed"]
            if len(failed) > 1 and len(failed) == len(report["lines"]):
                failed = ["all lines"]
            return f"{report['earned']}/{report['possible']} points", failed
        if kind == "audit" and "audit.json" in files:
            report = json.loads(files["audit.json"])
            counts = report["counts"]
            failed = [check["id"] for check in report["checks"] if check["status"] in ("FAIL", "ERROR")]
            return f"FAIL {counts['FAIL']}, WARN {counts['WARN']}, ERROR {counts['ERROR']}", failed
    except (ValueError, KeyError, TypeError):
        return f"unreadable {kind}.json", []
    return "", []


def outcome(result):
    """How a group's grading went, in a few words."""
    summary = (result.get("results") or {}).get("summary") or {}
    if result.get("state") in ("failed", "stuck", "not started") and not summary:
        return f"pod {result['state']}: {result.get('reason') or result.get('pod', {}).get('reason', '')}"
    if summary.get("outcome") == "not graded":
        return f"not graded: {summary.get('reason', '')}"
    if summary.get("outcome") == "timed out":
        return "timed out"
    if summary.get("outcome") == "error":
        return f"error: {summary.get('error', '')}"
    if summary.get("closed"):
        listening = ", ".join(str(port) for port in summary.get("listening", [])) or "none"
        return f"no service on port {', '.join(map(str, summary['closed']))} (listening: {listening})"
    if not summary:
        return "no results"
    kind = summary.get("kind")
    if f"{kind}.json" not in ((result.get("results") or {}).get("files") or {}):
        return f"no {kind}.json (exit {summary.get('exit')}); see {kind}.txt"
    return "graded"


def save(run_dir, group, result):
    folder = run_dir / group
    folder.mkdir(exist_ok=True)
    files = (result.get("results") or {}).get("files") or {}
    for name in RESULT_FILES:
        if isinstance(files.get(name), str):
            (folder / name).write_text(files[name], encoding="utf-8")
    for name, text in (result.get("logs") or {}).items():
        if name in ("grader", "service", "prepare") and text:
            (folder / f"{name}.log").write_text(text, encoding="utf-8")
    record = {key: result.get(key) for key in ("state", "reason", "pod", "events")}
    record["summary"] = (result.get("results") or {}).get("summary")
    (folder / "result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def progress(run_dir, answer):
    for group, result in sorted(answer.get("results", {}).items()):
        if not GROUP.match(group):
            fail(f"Unexpected group name from the cluster: {clean(group)!r}")
        save(run_dir, group, result)
        summary = (result.get("results") or {}).get("summary") or {}
        score, _ = points(result)
        work = summary.get("work") or "-"
        print(clean(f"  {group:<9} {work:<10} {score or outcome(result)}"), file=sys.stderr)
    states = answer.get("groups", {})
    counts = {}
    for state in states.values():
        counts[state] = counts.get(state, 0) + 1
    remaining = sum(1 for group in states if not (run_dir / group / "result.json").is_file())
    busy = ", ".join(f"{counts[state]} {state}" for state in ("running", "pending", "waiting") if state in counts)
    print(f"[{time.strftime('%H:%M:%S')}] {len(states) - remaining} of {len(states)} groups done"
          + (f"; {busy}" if busy else ""), file=sys.stderr)
    print(f"remaining={remaining}")


def receive(args):
    answer = answer_of(sys.stdin.read())
    if args.operation == "status":
        for key, value in sorted(answer["state"].items()):
            print(f"{key}={clean(value)}")
        print(f"groups={len(answer['groups'])}")
        lock = answer.get("lock") or {}
        for key in ("run", "started", "module", "kind", "track", "idle"):
            print(f"lock_{key}={clean('' if lock.get(key) is None else lock[key])}")
        print(f"host={re.sub(r'[^A-Za-z0-9.-]', '-', answer.get('host', '')) or 'cluster'}")
        return
    if args.operation == "cleanup":
        deleted = answer["deleted"]
        print(f"Removed {deleted['pod']} pods, {deleted['networkpolicy']} network policy and "
              f"{deleted['configmap']} ConfigMaps of grading run {clean(answer['run'])}.", file=sys.stderr)
        for error in answer.get("errors") or []:
            print(clean(error), file=sys.stderr)
        if answer["left"]:
            fail(f"Still in the cluster: {clean(json.dumps(answer['left']))}")
        return
    run_dir = Path(args.run_dir)
    if args.operation == "start":
        record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        record.update({key: answer.get(key) for key in ("image", "host", "kubernetes", "started")})
        record["groups"] = answer.get("names") or []
        (run_dir / "run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(clean(f"Started grading run {record['run']} for {len(record['groups'])} groups with "
                    f"{record['image']} (Kubernetes {record['kubernetes']})."), file=sys.stderr)
    progress(run_dir, answer)


def summary(args):
    run_dir = Path(args.run_dir)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    spec = MODULES[run["module"]]
    kind = run["kind"]
    rows = []
    for group in run.get("groups") or []:
        path = run_dir / group / "result.json"
        if not path.is_file():
            rows.append([group, "-", "", "no results", ""])
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        files = {name: (run_dir / group / name).read_text(encoding="utf-8")
                 for name in RESULT_FILES if (run_dir / group / name).is_file()}
        result = {"state": record.get("state"), "reason": record.get("reason"), "pod": record.get("pod") or {},
                  "results": {"summary": record.get("summary") or {}, "files": files}}
        score, problems = points(result)
        work = (record.get("summary") or {}).get("work") or "-"
        rows.append([group, work, score, outcome(result), "; ".join(problems)])
    what = "grading-script points" if kind == "tests" else "TA audit"
    header = ["Group", "Work", "Points" if kind == "tests" else "Findings", "Outcome",
              "Failed lines" if kind == "tests" else "Failed checks"]
    with open(run_dir / "summary.csv", "w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows([header] + rows)
    lines = [f"# Cloud Computing SOA, {spec['title']}: {what}", "",
             f"Run {run['run']}, started {run.get('started') or run['created']}, track {run['track']}, "
             f"{len(rows)} groups, image {run.get('image')}.", ""]
    if kind == "tests":
        lines += [f"Points cover only what the grading script tests; the {spec['assignment']} rubric lines that "
                  "need a TA are listed in each group's tests.txt.", ""]
    else:
        lines += ["FAIL findings are grounds for a deduction (one per bug, not per check), WARN findings are "
                  "questions for the oral exam; see each group's audit.md.", ""]
    lines += ["Work: unchanged means the files the group received, solution the reference solution, "
              "missing that the track's code is not there.", ""]
    lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(clean(cell).replace("|", "\\|") for cell in row) + " |" for row in rows]
    lines += ["", "Each group's folder holds the grading output, prepare.json (the files graded, with checksums), "
              "service.log (the group's services), and result.json (the pod).", ""]
    (run_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    widths = [max(len(clean(row[column])) for row in [header] + rows) for column in range(4)]
    for row in [header] + rows:
        print("  ".join(clean(row[column]).ljust(widths[column]) for column in range(4)).rstrip())
    print(f"\nResults: {run_dir}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("script")
    build.add_argument("operation", choices=("status", "start", "step", "cleanup"))
    build.add_argument("--namespace", required=True)
    build.add_argument("--run-dir")
    build.add_argument("--run")
    build.add_argument("--module", choices=sorted(MODULES))
    build.add_argument("--track", choices=TRACKS)
    build.add_argument("--kind", choices=sorted(TIMEOUTS))
    build.add_argument("--groups", default="")
    build.add_argument("--parallel", type=int, default=4)
    build.add_argument("--egress", choices=("participant", "none"), default="participant")
    build.add_argument("--image", default="")
    build.add_argument("--audit-dir", default="")
    read = commands.add_parser("receive")
    read.add_argument("operation", choices=("status", "start", "step", "cleanup"))
    read.add_argument("--run-dir")
    report = commands.add_parser("summary")
    report.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    if args.command == "script" and args.operation == "start":
        missing = [name for name in ("run_dir", "run", "module", "track", "kind") if not getattr(args, name)]
        if missing:
            parser.error("start needs --" + ", --".join(name.replace("_", "-") for name in missing))
        if not re.fullmatch(r"[0-9a-f]{8}", args.run) or not 1 <= args.parallel <= 20:
            parser.error("--run must be 8 hexadecimal digits and --parallel 1 to 20")
    {"script": script, "receive": receive, "summary": summary}[args.command](args)


if __name__ == "__main__":
    main()
