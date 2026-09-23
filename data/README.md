# Workshop dataset metadata

## Contents

- `source/train.csv` — cassava training metadata with `image` and `label`
  columns.
- `partitions/group_XX/train.csv` — one prepared local metadata partition for
  each workshop group. The number of groups is determined when the organiser
  prepares the workshop.
- `partitions/partition-manifest.json` — records the source-row count, source
  SHA-256 digest, partition configuration, and partition metadata.

The prepared `group_XX` files are disjoint partitions of `source/train.csv`.
Together, they must cover every source metadata row exactly. The organiser
workflow verifies this relationship using the manifest.

## Current local preparation

The currently prepared local data contain two partitions:

- `partitions/group_01/train.csv`
- `partitions/group_02/train.csv`

The associated manifest records 5,656 source rows and this source SHA-256
digest:

    c3a8c96436fafb8d97216eddc1d3c479d1ce4e280e598eded03ca9713401921b

The number, names, and contents of prepared partitions may change when a
workshop organiser prepares a new session.

## Source, citation, and terms

The configured source is the
[Kaggle Cassava Leaf Disease Classification competition](https://www.kaggle.com/competitions/cassava-leaf-disease-classification/data),
which originates from the iCassava 2019 challenge.

Recommended academic citation:

> Mwebaze, E., Gebru, T., Frome, A., Nsumba, S., & Tusubira, J. (2019).
> *iCassava 2019 Fine-Grained Visual Categorization Challenge*.
> arXiv:1908.02900. https://arxiv.org/abs/1908.02900

This repository must **not** represent the source images or metadata as
CC0-licensed. Use, access, and any redistribution remain subject to the
applicable Kaggle competition terms and any required permissions. Confirm
those terms before publishing or distributing prepared metadata outside the
authorised workshop context.

## Data handling and workshop scope

The CSV files contain image identifiers and class labels only. The source image
files are not included in this repository.

The workshop uses these metadata records to demonstrate partitioning and
federated-learning workflow mechanics. Its current client creates synthetic
features from local metadata and does not open or classify image pixels.
