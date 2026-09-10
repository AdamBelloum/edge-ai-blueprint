# Dataset

## Contents

- `source/train.csv` — cassava training metadata, with `image` and `label` columns.
- `partitions/Group_01/train.csv`
- `partitions/Group_02/train.csv`
- `partitions/Group_03/train.csv`
- `partitions/partition-manifest.json` — records the canonical source path and partition metadata.

The three group files are partitions of `source/train.csv`.

## Licence

The dataset is published under the
[CC0 1.0 Universal Public Domain Dedication](https://creativecommons.org/publicdomain/zero/1.0/).

## Provenance

**Authoritative source / citation:** **TODO — add the official dataset URL or citation before public release.**

## Data handling

The CSV metadata contains image identifiers and class labels only. The image files themselves are not included in this repository.
