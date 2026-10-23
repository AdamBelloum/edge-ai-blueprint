#!/usr/bin/env python3
"""Verify pinned FL partition recovery without publishing or staging data."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovery-manifest", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--groups", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--export-root", type=Path,
                        help="New temporary directory for verified partitions")
    args = parser.parse_args()

    if args.recovery_manifest is not None:
        if any(value is not None for value in (
            args.data_root, args.groups, args.seed
        )):
            parser.error(
                "--recovery-manifest cannot be combined with explicit parameters"
            )
        raw = args.recovery_manifest.read_bytes()
        if hashlib.sha256(raw).hexdigest() != args.expected_manifest_sha256:
            parser.error("retained recovery manifest checksum mismatch")
        evidence = json.loads(raw)
        source_path = Path(evidence.get("source_file", ""))
        if (
            not source_path.is_absolute()
            or source_path.name != "train.csv"
            or source_path.parent.name != "source"
        ):
            parser.error("invalid canonical source path in recovery evidence")
        args.data_root = source_path.parent.parent
        args.groups = evidence.get("groups")
        args.seed = evidence.get("seed")
        if (
            type(args.groups) is not int
            or args.groups < 1
            or type(args.seed) is not int
        ):
            parser.error("invalid group count or seed in recovery evidence")
        source_digest = hashlib.sha256()
        with source_path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                source_digest.update(block)
        if source_digest.hexdigest() != evidence.get("source_sha256"):
            parser.error("canonical source checksum differs from recovery evidence")
    elif any(value is None for value in (
        args.data_root, args.groups, args.seed
    )):
        parser.error(
            "provide --recovery-manifest or all of --data-root, --groups, --seed"
        )

    if not args.data_root.is_absolute():
        parser.error("--data-root must be absolute")
    if args.groups < 1:
        parser.error("--groups must be at least 1")
    if not re.fullmatch(r"[0-9a-f]{64}", args.expected_manifest_sha256):
        parser.error("expected manifest checksum must be lowercase SHA-256")

    if args.export_root is not None:
        destination = args.export_root.resolve()
        canonical = args.data_root.resolve()
        if args.export_root.exists() or args.export_root.is_symlink():
            parser.error("export destination must not already exist")
        if (
            destination == canonical
            or canonical in destination.parents
            or destination in canonical.parents
        ):
            parser.error("export destination must be outside canonical data")

    # Preserve the supplied source path spelling: it is part of the manifest.
    generator = Path(__file__).with_name("prepare_fl_partitions.py")
    with tempfile.TemporaryDirectory(prefix="fl-partition-recovery-") as tmp:
        output = Path(tmp) / "partitions"
        result = subprocess.run(
            [
                sys.executable, str(generator),
                "--data-root", str(args.data_root),
                "--groups", str(args.groups),
                "--seed", str(args.seed),
                "--partition-root", str(output),
            ],
            text=True, capture_output=True,
        )
        if result.returncode:
            print(result.stderr, file=sys.stderr, end="")
            return result.returncode

        manifest = output / "partition-manifest.json"
        actual = hashlib.sha256(manifest.read_bytes()).hexdigest()
        if actual != args.expected_manifest_sha256:
            print(
                "ERROR: Recovered manifest differs from the recorded checksum.\n"
                f"Expected: {args.expected_manifest_sha256}\n"
                f"Actual:   {actual}\n"
                "No partitions published, workers staged, or release record changed.",
                file=sys.stderr,
            )
            return 3

        candidate = json.loads(manifest.read_bytes())
        expected_groups = {
            f"group_{index:02d}" for index in range(1, args.groups + 1)
        }
        partitions = candidate.get("partitions")
        if (
            candidate.get("groups") != args.groups
            or candidate.get("group_id_format") != "group_{NN}"
            or not isinstance(partitions, dict)
            or set(partitions) != expected_groups
        ):
            print("ERROR: Candidate partition topology mismatch.", file=sys.stderr)
            return 3

        for group in sorted(expected_groups):
            entry = partitions[group]
            partition = output / group / "train.csv"
            if not isinstance(entry, dict) or not partition.is_file():
                print("ERROR: Missing candidate partition: " + group, file=sys.stderr)
                return 3
            hasher = hashlib.sha256()
            with partition.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(block)
            if hasher.hexdigest() != entry.get("sha256"):
                print(
                    "ERROR: candidate partition checksum mismatch: " + group,
                    file=sys.stderr,
                )
                return 3
            with partition.open(newline="", encoding="utf-8") as handle:
                rows = sum(1 for _ in csv.reader(handle)) - 1
            if (
                type(entry.get("rows")) is not int
                or rows < 0
                or rows != entry["rows"]
            ):
                print(
                    "ERROR: Candidate partition row count mismatch: " + group,
                    file=sys.stderr,
                )
                return 3

        # Export only after every candidate validation has succeeded.
        # copytree refuses an existing destination; canonical data is untouched.
        if args.export_root is not None:
            shutil.copytree(output, args.export_root)

        print(json.dumps({
            "recovery_verified": True,
            "manifest_sha256": actual,
            "groups": args.groups,
            "seed": args.seed,
            "published": False,
            "workers_staged": False,
        }, sort_keys=True))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
