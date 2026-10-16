# Big Data — Spark participant workspace

> **Pilot status — not yet ready for participant execution.** The organiser must validate the Python runtime, Spark connection, dataset access and worker-to-driver networking before either interface is used. Neither interface is a workaround for incomplete preparation.

## Start here

Complete the exercises in order. For each exercise, choose the notebook
(recommended for beginners) or its equivalent Python script—not both.
The scripts are alternatives, not extra exercises or advanced solutions.

| Order | Goal | Notebook | Python alternative |
|---|---|---|---|
| 01 — Spark basics | Analyse the CSV with a workspace-side Spark driver. | `01_spark_basics.ipynb` | `01_spark_basics.py` |
| 02 — Spark via Livy | Repeat the analysis through pre-deployed Livy. | `02_spark_via_livy.ipynb` | `02_spark_via_livy.py` |

Use the organiser-prepared notebook kernel or terminal interpreter.
Complete Exercise 1 and stop its Spark session before starting Exercise 2.

Exercise 1 exports `outputs/filtered_preview.csv`.
Exercise 2 exports `outputs/02_filtered_preview.csv`.
Re-running either alternative replaces that exercise's output.

Do not install software or manage containers. The organiser confirms readiness
separately for each exercise. Exercise 2 live Livy validation remains pending.

## Included files

- `01_spark_basics.ipynb`: guided bank-loan analysis.
- `01_spark_basics.py`: documented terminal-based alternative to the notebook, using the same prepared Spark connection and analysis steps.
- `02_spark_via_livy.ipynb`: guided Livy session and remote analysis.
- `02_spark_via_livy.py`: terminal alternative and shared notebook helpers.
- `data/Bank_Personal_Loan_Modelling.csv`: the included input dataset.
- `docs/spark-DA.pdf`: teaching material.
- `participants-instructions.md`: managed-workshop guide for both participant interfaces.
- `outputs/`: created by either interface for your own exported results.

The organiser provisions Spark separately using the managed runtime configuration. The legacy `docker-compose.yml` is not delivered to participant workspaces and is not used for managed provisioning.

## Prepared connection — Exercise 1

Workspace preparation must provide a compatible PySpark/Java runtime and these settings:

- `SPARK_MASTER_URL`: your group's Spark master address.
- `SPARK_DATA_PATH`: the CSV path accessible to the driver and workers.
- `SPARK_DRIVER_HOST`: the notebook driver address reachable from Spark workers.
- `SPARK_DRIVER_PORT` and `SPARK_BLOCK_MANAGER_PORT`, when fixed ports are required.

If the notebook reports missing configuration, missing dependencies or connection errors,
report the error to the organiser. Do not work around it by installing software yourself.

## Prepared connection — Exercise 2

The organiser supplies `LIVY_URL` and `LIVY_DATA_PATH`.
The remote path identifies the same CSV accessible to the Livy-side driver
and executors; it need not equal the local path or `SPARK_DATA_PATH`.

Livy is pre-deployed and configured for Spark. Participants only connect.
Exercise 2 does not use Exercise 1's participant-driver callback settings.
Both Exercise 2 files must be delivered together: the notebook imports the
Python companion's helpers without running its terminal workflow.

This simple client assumes organiser-approved access without additional API
authentication. JupyterHub login does not automatically protect Livy.
Do not expose an unauthenticated Livy endpoint publicly.

## Integration status

Asset publication does not prove execution readiness. The organiser must
confirm runtime, settings and dataset access for each exercise. Exercise 2
requires end-to-end Livy validation. Delivery preserves participant files:
it does not update a running server or overwrite an existing README.

## Dataset snapshot and source status

### Verified local snapshot

These facts describe the bundled `data/Bank_Personal_Loan_Modelling.csv`, not a
verified upstream release or a completed live Spark run:

- **Records:** 5,000; **columns:** 14; **file size:** 206,883 bytes.
- **SHA-256:** `513c2b9963fadd84afc019df62607e5210073239f45a838bb31c2c087900b5b5`.
- **Blank values:** none, checking empty or whitespace-only fields across all columns.
- **Exact duplicate records:** none, comparing all 14 fields, including `ID`.
  This does not establish that every row represents a distinct person.
- **Strict filter `Age > 30`:** 4,376 records.
- **`Personal Loan` raw codes:** `0` occurs 4,520 times; `1` occurs 480 times.
  Code meanings are not yet verified.
- **Data-quality flag:** 52 negative `Experience` values; observed range −3 to 43.
  Investigate against source documentation rather than silently modifying them.

The checksum identifies this local byte sequence. It does not authenticate the
source or prove identity with any downloaded/upstream dataset version.

### Observed fields — not an authoritative data dictionary

The observations below come from the local CSV. Units, code meanings and original
collection context require source verification; names alone are insufficient.

| Field | Local observation / interpretation status |
|---|---|
| `ID` | Present; identifier semantics and assignment process unverified. |
| `Age` | Numeric range 23–67; source unit definition unverified. |
| `Experience` | Numeric range −3–43; 52 negative values; unit definition unverified. |
| `Income` | Numeric range 8–224; currency, scaling and time basis unverified. |
| `ZIP Code` | Present; coding scheme and geographic context unverified. Do not treat code magnitude as a measurement. |
| `Family` | Observed values `1`, `2`, `3`, `4`; precise definition unverified. |
| `CCAvg` | Present; meaning, currency, scaling and averaging period unverified. |
| `Education` | Observed codes `1`, `2`, `3`; category mapping unverified. |
| `Mortgage` | Present; units and interpretation of zero unverified. |
| `Personal Loan` | Observed codes `0`, `1`; counts 4,520 and 480; category mapping unverified. |
| `Securities Account` | Observed codes `0`, `1`; category mapping unverified. |
| `CD Account` | Observed codes `0`, `1`; category mapping unverified. |
| `Online` | Observed codes `0`, `1`; category mapping unverified. |
| `CreditCard` | Observed codes `0`, `1`; category mapping and scope unverified. |

### Source citation, provenance and redistribution

The archived standalone tutorial cites
[Kaggle: krantiswalke/bank-personal-loan-modelling](https://www.kaggle.com/datasets/krantiswalke/bank-personal-loan-modelling).
This is a historical source lead, not proof that the bundled bytes came from that
page or that the uploader is the original data creator.

Original provenance, upstream version, download date, authoritative field
interpretations, dataset licence and redistribution permission are **not yet
verified**. Direct automated retrieval encountered a browser check; inaccessible
metadata is not evidence that a licence or data dictionary is absent.
Do not substitute the licence or definitions of a similarly named dataset copy
without establishing the relationship to this snapshot.

Before publishing or redistributing the snapshot, verify permissions and record
the supporting source, attribution and licence information. The repository's
software licence does not automatically establish rights to third-party data.

### Teaching and runtime limitations

Both participant interfaces leave the input unchanged. They perform descriptive
analysis, not predictive modelling, causal inference or automated data cleaning.
The counts above were checked locally with Python's CSV reader. Confirmation of
those results through the prepared Spark cluster remains pending. Successful
session creation alone does not prove that every worker participated in execution.
The accompanying `docs/spark-DA.pdf` has completed a **text-only review** and is
conceptual/historical background, not executable managed-workshop instructions or
an authoritative dataset dictionary. Visual checks, slide revisions and example
execution remain pending. The source-repository review is recorded at
`docs/spark-teaching-material-review.md`, outside the participant bundle.
