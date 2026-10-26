# Big Data — Spark participant workspace

> **Pilot status — participant execution is not yet validated.** Organiser-controlled container validation has passed on both Tier-2 VMs. Before participants submit work, the organiser must confirm the approved launch command, runtime, data access, network path and output retrieval for each step. Publishing these guides does not establish readiness.

## Start here

Complete the steps in order. Each notebook is a **Markdown-only reading guide**, not an executable notebook. Read it in JupyterLab and perform the exercise separately using the corresponding Python script through the organiser-approved terminal submission path.

The notebook and script are complementary: the notebook explains the exercise; the script performs it. There are no notebook code cells to run and no notebook kernel to select for these guides.

| Order | Goal | Reading guide | Analysis script |
|---|---|---|---|
| 01 — Direct Spark submission | Analyse the CSV with a driver in the prepared submission environment. | `01_spark_basics.ipynb` | `01_spark_basics.py` |
| 02 — Spark through Livy | Repeat the analysis through the prepared Livy service, with a remote driver. | `02_spark_via_livy.ipynb` | `02_spark_via_livy.py` |

Wait for the organiser's exact launch command. Do not assume that JupyterLab's default terminal Python has the correct dependencies or access. The administrator's Ansible environment is not the participant runtime.

Complete Step 1 and confirm its cleanup before Step 2. Do not submit multiple copies while an earlier application or session may remain active.

Step 1 writes `outputs/filtered_preview.csv`; Step 2 writes `outputs/02_filtered_preview.csv`, relative to the analysis script's directory. A rerun replaces that step's preview. The organiser must explain how container-local results are mapped or retrieved into your workspace.

Do not install software, change ports, manage containers or use organiser-only runtime test scripts as participant commands.

## Included files

- `01_spark_basics.ipynb`: Markdown-only guide to direct Spark submission and analysis.
- `01_spark_basics.py`: Step 1 analysis script for the approved execution environment.
- `02_spark_via_livy.ipynb`: Markdown-only guide to Livy submission and remote analysis.
- `02_spark_via_livy.py`: Step 2 analysis script and reusable Livy helpers.
- `data/Bank_Personal_Loan_Modelling.csv`: the supplied input snapshot; see the provenance and permission limitations below.
- `docs/spark-DA.pdf`: conceptual/historical teaching material.
- `participants-instructions.md`: shared guidance for reading the notebooks and executing separately.
- `outputs/`: created by analysis execution for bounded preview files, with visibility depending on the prepared output mapping.

The organiser provisions Spark separately using the managed runtime configuration. The legacy `docker-compose.yml` is not delivered to participant workspaces and is not used for managed provisioning.

## Prepared connection — Step 1

The execution environment must provide compatible PySpark/Java and the organiser's settings:

- `SPARK_MASTER_URL`: the assigned Spark master address.
- `SPARK_DATA_PATH`: the CSV path accessible to the driver and executors.
- `SPARK_DRIVER_HOST`: the driver address reachable from workers.
- `SPARK_DRIVER_PORT` and `SPARK_BLOCK_MANAGER_PORT`, when fixed ports are required.

The driver belongs to the running application, not the Markdown guide. Reaching the master alone is insufficient; executor-to-driver connectivity also matters. Local preview and distributed input paths can differ but must identify the same supplied dataset.

Report missing configuration, dependencies or connectivity to the organiser. Do not substitute guessed settings or local Spark.

## Prepared connection — Step 2

The organiser supplies `LIVY_URL` and `LIVY_DATA_PATH`. The remote path identifies the same CSV accessible to the Livy-side driver and executors; it need not equal the local path or Step 1's `SPARK_DATA_PATH`.

The running client sends requests to prepared Livy. The driver runs on the Livy side, so Step 1's participant-driver callback settings are not reused. The Markdown guide does not import helpers or create a session.

The current helper assumes organiser-approved access without additional API authentication. JupyterHub login does not automatically protect Livy. Do not expose an unauthenticated Livy endpoint publicly or disable TLS verification.

## Validation and integration status

The separate organiser-controlled client tests completed on both Tier-2 VMs. The Livy tests observed the expected bank-loan counts, exported ten rows, and confirmed owned-client removal, session deletion and application inactivity.

These are educational one-worker pilots within each VM's runtime, not evidence of a Spark cluster spanning both VMs. Participant terminal access, concurrent capacity, isolation and failure-path recovery remain unvalidated.

The tested Step 2 runner applies explicit resource limits and verifies cleanup. The standalone participant script does not send that same bounded session payload; it requests session deletion but does not verify completed teardown. The organiser must approve the participant submission path before use.

Repository changes do not automatically update delivered workspaces or running services. Existing participant files must not be overwritten without an explicit, reviewed update procedure.

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

The notebooks contain guidance only. Both analysis scripts leave the input unchanged and perform descriptive analysis, not predictive modelling, causal inference or automated data cleaning.

The counts above were checked locally with Python's CSV reader and also observed through Spark in the organiser-controlled Tier-2 Livy tests. That runtime evidence does not resolve source provenance, field definitions or redistribution permissions. Participant execution remains unvalidated. Successful session creation alone does not prove that every worker participated in execution.

The accompanying `docs/spark-DA.pdf` has completed a **text-only review** and is
conceptual/historical background, not executable managed-workshop instructions or
an authoritative dataset dictionary. Visual checks, slide revisions and example
execution remain pending. The source-repository review is recorded at
`docs/spark-teaching-material-review.md`, outside the participant bundle.
