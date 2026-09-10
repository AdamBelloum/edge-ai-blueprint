#!/usr/bin/env python3
"""Create reproducible, non-overlapping stratified FL data partitions."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def label_seed(seed: int, label: object) -> int:
    suffix = int(hashlib.sha256(str(label).encode()).hexdigest()[:8], 16)
    return (seed + suffix) % (2**32)


parser = argparse.ArgumentParser()
parser.add_argument("--groups", type=int, required=True)
parser.add_argument("--seed", type=int, default=42)
parser.add_argument(
    "--data-root",
    type=Path,
    required=True,
    help="Workshop data workspace containing source/train.csv and partitions/",
)
args = parser.parse_args()

if args.groups < 1:
    raise SystemExit("--groups must be at least 1")

data_root = args.data_root
source = data_root / "source" / "train.csv"

if not source.is_file():
    raise SystemExit(
        f"Canonical source CSV not found: {source}. "
        "Run the organiser data-preparation step first."
    )

df = pd.read_csv(source)
required_columns = {"image", "label"}
missing_columns = sorted(required_columns.difference(df.columns))
if missing_columns:
    raise SystemExit(
        f"Source CSV {source} is missing required column(s): "
        f"{', '.join(missing_columns)}"
    )
if df.empty:
    raise SystemExit(f"Source CSV {source} contains no rows")
if df["image"].isna().any() or df["label"].isna().any():
    raise SystemExit(
        f"Source CSV {source} contains missing image or label values"
    )

labels = sorted(df["label"].unique().tolist())
if len(labels) < 2:
    raise SystemExit("Source dataset must contain at least two labels")

label_counts = df["label"].value_counts()
too_small = label_counts[label_counts < args.groups]
if not too_small.empty:
    raise SystemExit(
        "Cannot create a stratified partition for every group; "
        f"these labels have fewer rows than groups: {too_small.to_dict()}"
    )

partitions: list[list[pd.DataFrame]] = [[] for _ in range(args.groups)]

for label in labels:
    label_rows = df[df["label"] == label]
    indices = label_rows.index.to_numpy().copy()
    rng = np.random.default_rng(label_seed(args.seed, label))
    rng.shuffle(indices)

    for group_index, chunk in enumerate(np.array_split(indices, args.groups)):
        partitions[group_index].append(df.loc[chunk])

partition_root = data_root / "partitions"
partition_root.mkdir(parents=True, exist_ok=True)

# Remove only previously generated partition directories and manifest.
# This prevents stale groups from a previous run being deployed accidentally.
for stale_group in partition_root.glob("Group_*"):
    if not stale_group.is_dir():
        raise SystemExit(
            f"Refusing to replace non-directory partition artifact: {stale_group}"
        )
    shutil.rmtree(stale_group)

stale_manifest = partition_root / "partition-manifest.json"
if stale_manifest.exists():
    stale_manifest.unlink()

manifest = {
    "source_file": str(source),
    "source_sha256": sha256(source),
    "strategy": "stratified_non_overlapping",
    "seed": args.seed,
    "groups": args.groups,
    "source_rows": len(df),
    "labels": [str(label) for label in labels],
    "partitions": {},
}

total_rows = 0
for index, chunks in enumerate(partitions, start=1):
    group_id = f"Group_{index:02d}"
    group_dir = partition_root / group_id
    output = group_dir / "train.csv"

    group_dir.mkdir(parents=True, exist_ok=True)
    partition = pd.concat(chunks, ignore_index=True)
    partition = partition.sample(
        frac=1.0,
        random_state=args.seed + index,
    ).reset_index(drop=True)

    partition.to_csv(output, index=False)
    total_rows += len(partition)

    manifest["partitions"][group_id] = {
        "rows": len(partition),
        "label_counts": {
            str(label): int(count)
            for label, count in partition["label"].value_counts()
            .sort_index()
            .items()
        },
        "sha256": sha256(output),
    }

if total_rows != len(df):
    raise SystemExit(
        f"Partition integrity failure: {total_rows} output rows, "
        f"{len(df)} source rows"
    )

manifest_path = partition_root / "partition-manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

print(
    json.dumps(
        {
            "groups": args.groups,
            "manifest": str(manifest_path),
            "partition_rows": {
                group_id: details["rows"]
                for group_id, details in manifest["partitions"].items()
            },
            "source_sha256": manifest["source_sha256"],
        },
        sort_keys=True,
    )
)
