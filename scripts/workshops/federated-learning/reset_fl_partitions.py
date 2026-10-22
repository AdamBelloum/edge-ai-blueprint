#!/usr/bin/env python3
"""Remove default local FL partition artifacts; preserve canonical source."""

import argparse
import hashlib
import re
import shutil
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refuse(message):
    raise SystemExit("Partition cleanup refused: " + message)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--repository-root", type=Path, required=True)
args = parser.parse_args()

root = args.repository_root.absolute()
if root.resolve() != root or not root.is_dir():
    refuse("repository root must be an existing, canonical directory")

data = root / "data"
source = data / "source" / "train.csv"
partitions = data / "partitions"

for path in (data, source.parent, source, partitions):
    if path.is_symlink() or path.resolve() != path:
        refuse(f"symlinked or redirected path: {path}")

if not source.is_file():
    refuse(f"canonical source is missing or not a regular file: {source}")

source_before = digest(source)

if partitions.exists() and not partitions.is_dir():
    refuse(f"partition root is not a directory: {partitions}")

artifacts = list(partitions.iterdir()) if partitions.exists() else []

# Validate every artifact before deleting anything.
for artifact in artifacts:
    if artifact.is_symlink():
        refuse(f"symlinked artifact: {artifact}")
    if re.fullmatch(r"(?:group|Group)_[0-9]{2,}", artifact.name):
        if not artifact.is_dir():
            refuse(f"group artifact is not a directory: {artifact}")
    elif artifact.name == "partition-manifest.json":
        if not artifact.is_file():
            refuse(f"manifest is not a regular file: {artifact}")
    else:
        refuse(f"unexpected artifact: {artifact}")

for artifact in artifacts:
    if artifact.is_dir():
        shutil.rmtree(artifact)
    else:
        artifact.unlink()

if partitions.exists() and any(partitions.iterdir()):
    refuse("partition artifacts remain")

if not source.is_file() or digest(source) != source_before:
    refuse("canonical source changed during cleanup")

print("Local generated partitions absent; canonical source unchanged.")
