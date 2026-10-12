#!/usr/bin/env bash
# Standalone Module 3 helper. No platform context or cluster access required.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
command -v python3 >/dev/null 2>&1 || {
	  printf '%s\n' 'ERROR: python3 is required.' >&2
  exit 1
  }

  exec python3 - "$REPOSITORY_ROOT" "$@" <<'PY'
import argparse
import csv
import io
import subprocess
import sys
import tarfile
from collections import Counter
from pathlib import Path

repository = Path(sys.argv[1])
parser = argparse.ArgumentParser(
    prog="module3-local.sh",
    description="Validate or export local Module 3 assets without cluster access.",
)
commands = parser.add_subparsers(dest="action", required=True)
check = commands.add_parser("check", help="Check the map and selected asset syntax")
check.add_argument("mode", choices=("beginner", "advanced", "solutions"))
export = commands.add_parser("export", help="Create a new standalone .tar.gz bundle")
export.add_argument("mode", choices=("beginner", "advanced", "solutions"))
export.add_argument("destination", help="New archive path ending in .tar.gz")
export.add_argument("--confirm-solutions", action="store_true",
                    help="Explicitly authorise exporting reference solutions")
args = parser.parse_args(sys.argv[2:])

root = repository / "workshop_assets/cloud_computing_soa/module3_containerization_orchestration"
tracks = {
    "beginner": root / "beginner",
    "advanced": root / "advanced",
    "solutions": root / "solutions",
    "tests": root / "shared/tests",
}


def fail(message):
    raise RuntimeError(message)


def validate_map():
    rows = []
    destinations = set()
    keys = set()
    counts = Counter()
    with (root / "asset-map.tsv").open(newline="", encoding="utf-8") as stream:
        for number, row in enumerate(csv.reader(stream, delimiter="\t"), 1):
            if len(row) != 3:
                fail(f"Row {number}: expected three TSV fields")
            track, key, relative = row
            path = Path(relative)
            if track not in tracks:
                fail(f"Row {number}: unknown track {track!r}")
            if not key or not relative or path.is_absolute() or ".." in path.parts:
                fail(f"Row {number}: empty key or unsafe path")
            blocked = {"keys", ".venv", "__pycache__", ".git", "secrets"}
            if blocked.intersection(path.parts) or path.suffix.lower() in {
                ".pem", ".key", ".pyc", ".pyo"
            } or path.name == ".env":
                fail(f"Row {number}: prohibited generated or secret path {relative}")
            source = tracks[track] / path
            if not source.is_file():
                fail(f"Row {number}: missing file {source}")
            # Reject symlinks in the entire source path, not just its last component.
            if any(part.is_symlink() for part in (source, *source.parents)):
                fail(f"Row {number}: symlink in source path {source}")
            try:
                source.resolve().relative_to(tracks[track].resolve())
            except ValueError:
                fail(f"Row {number}: source escapes track directory")
            destination = (track, path.as_posix())
            if destination in destinations or (track, key) in keys:
                fail(f"Row {number}: duplicate destination or asset key")
            destinations.add(destination)
            keys.add((track, key))
            counts[track] += 1
            rows.append((track, key, path.as_posix(), source))
    for track in tracks:
        if not counts[track]:
            fail(f"No mapped assets for {track}")
        print(f"{track}: {counts[track]} mapped assets")
    return rows


def validate_syntax(selected):
    counts = Counter()
    for track, key, relative, source in selected:
        if source.suffix == ".py":
            compile(source.read_bytes(), str(source), "exec")
            counts["Python"] += 1
        elif source.suffix == ".sh":
            result = subprocess.run(
                ["bash", "-n", str(source)], capture_output=True, text=True
            )
            if result.returncode:
                fail(f"Bash syntax error in {source}: {result.stderr.strip()}")
            counts["Bash"] += 1
    print(f"PASS: selected assets: {counts['Python']} Python, {counts['Bash']} Bash files")
    print("Structural and syntax validation only; containers and services are not tested.")


def export_bundle(selected):
    if args.mode == "solutions" and not args.confirm_solutions:
        fail("Solution export requires --confirm-solutions; no archive created.")
    if args.confirm_solutions and args.mode != "solutions":
        fail("--confirm-solutions is only valid for solutions mode")
    destination = Path(args.destination).expanduser()
    if not destination.name.endswith(".tar.gz"):
        fail("Destination must end in .tar.gz")
    if not destination.parent.is_dir():
        fail("Destination parent directory must already exist")
    # Keep generated bundles outside the source asset tree.
    try:
        destination.resolve().relative_to(root.resolve())
    except ValueError:
        pass
    else:
        fail("Destination must be outside the Module 3 source asset directory")
    if destination.exists() or destination.is_symlink():
        fail("Destination already exists; refusing to overwrite")

    prefix = f"module3-{args.mode}"
    notice = (
        f"# Module 3 standalone assets — {args.mode}\n\n"
        "This archive contains the selected track and shared tests only.\n"
        "Generated keys, other tracks, and repository orchestration are not included.\n\n"
        "## Validation status\n\n"
        "The source map and selected Python/Bash syntax were checked at export time.\n"
        "Container builds, dependency installation, YAML semantics, service execution,\n"
        "and functional tests are NOT validated by this helper.\n\n"
        "Participant setup guides are not yet included. This is an asset bundle,\n"
        "not a verified ready-to-run workshop release.\n\n"
        "## Important lab assumptions\n\n"
        "- Compose defaults: auth port 5001, shortener port 5000.\n"
        "- Kubernetes manifests require image registry and NFS configuration.\n"
        "- Generate local keys separately; never distribute private signing keys.\n"
        "- JSON persistence is not safe for concurrent replicas or production use.\n"
        "- Tests accept AUTH_BASE_URL and SHORTENER_BASE_URL.\n"
    ).encode("utf-8")
    created = False
    try:
        with destination.open("xb") as output:
            created = True
            with tarfile.open(fileobj=output, mode="w:gz") as archive:
                for track, key, relative, source in selected:
                    folder = "tests" if track == "tests" else ""
                    name = "/".join(part for part in (prefix, folder, relative) if part)
                    # Read regular files directly; do not recursively archive directories.
                    data = source.read_bytes()
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    info.mode = 0o755 if source.suffix == ".sh" else 0o644
                    archive.addfile(info, io.BytesIO(data))
                info = tarfile.TarInfo(f"{prefix}/BUNDLE-NOTES.md")
                info.size = len(notice)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(notice))
    except BaseException:
        if created:
            destination.unlink()
        raise
    print(f"EXPORTED: {destination.resolve()}")
    print(f"Included {len(selected)} mapped files and BUNDLE-NOTES.md.")


try:
    rows = validate_map()
    selected = [row for row in rows if row[0] in (args.mode, "tests")]
    validate_syntax(selected)
    if args.action == "export":
        export_bundle(selected)
except (OSError, RuntimeError, SyntaxError, ValueError) as error:
    print(f"ERROR: {error}", file=sys.stderr)
    sys.exit(1)
PY
