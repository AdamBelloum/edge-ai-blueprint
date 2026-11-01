# Big Data — Spark participant workspace

> **Pilot status — participant execution is not yet validated.** Organiser-controlled container validation has passed on both Tier-2 VMs. Before participants submit work, the organiser must confirm the approved launch command, runtime, data access, network path and output retrieval for each step. Publishing these guides does not establish readiness.

## Start here

Complete the steps in order. Each notebook is a **Markdown-only reading guide**, not an executable notebook. Read it in JupyterLab and perform the exercise separately using the corresponding Python script through the organiser-approved terminal submission path.

The notebook and script are complementary: the notebook explains the exercise; the script performs it. There are no notebook code cells to run and no notebook kernel to select for these guides.

| Order | Goal | Reading guide | Analysis script |
|---|---|---|---|
| 01 — Direct Spark submission | Analyse the CSV with a driver in the prepared submission environment. | `01_spark_basics.ipynb` | `01_spark_basics.py` |
| 02 — Spark through Livy | Repeat the analysis through the prepared Livy service, with a remote driver. | `02_spark_via_livy.ipynb` | `02_spark_via_livy.py` |

For the managed Step 1 launch path, read `STEP1-DIRECT-SUBMISSION.md` before
submitting. In the organiser-prepared participant terminal environment, run
`python3 spark_direct_submit.py test` only after permission. After successful
test completion and organiser approval, **follow the five numbered activities**
in `01_spark_basics.ipynb`, using the cycle:
**read → predict → run → observe → record → reflect**.

Copy each activity command from the notebook individually; for example,
`python3 spark_direct_submit.py analyse --activity 1` runs activity 1. Continue
through activities 2–5 only after checking completion and recording your answers.
Do not paste command batches or run `01_spark_basics.py` directly in JupyterLab.
Only activity 5 writes and downloads a bounded preview; activities 1–4 do not.

The unchanged `python3 spark_direct_submit.py analyse` command is an
**optional organiser-requested reference**, not an additional required
submission in the guided exercise. It runs the complete analysis and downloads
a bounded preview. Participant execution remains unvalidated; documented
commands and offline tests do not establish readiness. Step 2 still requires a
separately approved launch path; the administrator's Ansible environment is not
the participant runtime.

Complete Step 1 and confirm its cleanup before Step 2. Do not submit multiple copies while an earlier application or session may remain active.

For Step 2, wait for separate organiser approval, then **follow the five numbered
activities** in `02_spark_via_livy.ipynb` using the same cycle:
**read → predict → run → observe → record → reflect**. Use the prepared JupyterLab
terminal and copy only one command at a time:

| Activity | Step 2 command to copy individually |
|---|---|
| 1 — Load and inspect | `python3 02_spark_via_livy.py --activity 1` |
| 2 — Select columns | `python3 02_spark_via_livy.py --activity 2` |
| 3 — Filter rows | `python3 02_spark_via_livy.py --activity 3` |
| 4 — Count categories | `python3 02_spark_via_livy.py --activity 4` |
| 5 — Export and retrieve | `python3 02_spark_via_livy.py --activity 5` |

Each command owns a fresh Livy session. Only activity 5 writes the Step 2 preview;
activities 1–4 do not. The no-option `python3 02_spark_via_livy.py` command is an
**optional organiser-requested reference**, not an additional required submission.
Guided participant execution remains unvalidated.

Step 1 writes `outputs/filtered_preview.csv` on the assigned remote client. After successful analysis, the launcher downloads it to a new local `outputs/remote-<unique-id>/filtered_preview.csv` directory beside the submitted script and prints `Downloaded preview:`. A rerun replaces the shared remote preview, not earlier unique local downloads. Submit one job per group at a time; unique download directories do not prevent remote concurrency conflicts. Only Step 2 activity 5 or full analysis writes `outputs/02_filtered_preview.csv` relative to its client script. An exporting rerun replaces that participant-local preview; it does not replace Step 1 downloads or the input. Follow the printed `Saved:` path and the separately approved Step 2 procedure.

Do not install software, change ports, manage containers or use organiser-only runtime test scripts as participant commands.

## Included files

- `01_spark_basics.ipynb`: Markdown-only guide to direct Spark submission and analysis.
- `01_spark_basics.py`: Step 1 analysis script for the approved execution environment.
- `02_spark_via_livy.ipynb`: Markdown-only guide to Livy submission and remote analysis.
- `02_spark_via_livy.py`: Step 2 HTTP client supporting five guided activities and optional full analysis.
- `spark_livy_access.py`: existing managed loopback-forwarding, dataset-verification and owned-session cleanup helper.
- `data/Bank_Personal_Loan_Modelling.csv`: the supplied input snapshot; see the provenance and permission limitations below.
- `docs/spark-DA.pdf`: conceptual/historical teaching material.
- `STEP1-DIRECT-SUBMISSION.md`: current managed Step 1 launch, credentials, result retrieval and safety instructions.
- `spark_direct_submit.py`: existing SSH/SFTP launcher; it submits real `spark-submit` commands in the assigned client.
- `participants-instructions.md`: shared guidance for reading the notebooks and executing separately.
- `outputs/`: contains bounded previews; managed Step 1 downloads use separate `remote-<unique-id>/` subdirectories.

The organiser provisions Spark separately using the managed runtime configuration. The legacy `docker-compose.yml` is not delivered to participant workspaces and is not used for managed provisioning.

## Prepared connection — Step 1

Open `~/Big-Data/Spark` in a JupyterLab terminal. The organiser prepares Python
with Paramiko and stages the group's credentials for participant startup under
`~/.ssh/spark-direct/`. The launcher reads `login_key` and `known_hosts` there
and derives the endpoint from its single organiser-pinned host record.
Do not transfer keys manually, guess addresses or disable host-key checks.

JupyterHub is the transport environment, not the Spark driver. The assigned
client container supplies Java/PySpark, `SPARK_MASTER_URL`, `SPARK_DATA_PATH`,
`SPARK_DRIVER_HOST` and the dataset link. The driver runs in that client;
executors run in the assigned VM's worker and must connect back to the driver.
Participants do not export those settings in JupyterLab or install software.

Read `STEP1-DIRECT-SUBMISSION.md` for the test, analysis, downloaded-result and failure
checks. One active submission per group/client is required; the launcher has
no concurrency lock. Missing dependencies, credentials, connectivity or remote
data access require organiser inspection, not guessed settings or local Spark.
The menu's automated participant validation and non-destructive stop remain
unfinished. Publication and organiser-only tests do not establish readiness.

## Prepared connection — Step 2

After separate organiser approval, use `02_spark_via_livy.ipynb` as the guided
learning sequence and run its individual activity commands with the prepared
interpreter. Do not execute notebook snippets or use organiser-only runtime tests
as participant commands. Use matching updated notebook, client and helper copies.

With neither `LIVY_URL` nor `LIVY_DATA_PATH` set, the existing helper uses the
managed group credentials under `~/.ssh/spark-direct/` for temporary loopback-only
SSH forwarding to the assigned private Livy service. Host-key pinning is mandatory.
It verifies the participant-local CSV's SHA-256 on the Livy driver and one executor
before analysis. No manual tunnel, exported settings or participant installation
is needed. Verification is repeated for each independent activity command and
checks that supplied snapshot, not multi-worker capacity.

Complete explicit organiser `LIVY_URL` and `LIVY_DATA_PATH` overrides remain
supported; partial overrides fail. Automatic managed dataset verification is not
performed in that explicit path, so the organiser must validate it separately.
The remote data path need not match the local CSV path or Step 1's Spark path.
Participants must not choose overrides or guess endpoints.

The HTTP client runs in the participant terminal; the driver runs on the Livy
side. Step 1's participant-driver callback settings are not reused. Variables
persist between statements within one command's session, not between separate
commands. Each command uses the returned owned session and statement IDs.

JupyterHub login does not automatically protect Livy's API. The existing access
path does not add API authentication; do not expose an unauthenticated endpoint,
disable TLS verification, replace SSH pins, or exchange group private keys.
**One active submission per group; take turns.** There is no client concurrency
lock, and fresh sessions are not proof of concurrent capacity.

## Validation and integration status

The separate organiser-controlled client tests completed on both Tier-2 VMs. The Livy tests observed the expected bank-loan counts, exported ten rows, and confirmed owned-client removal, session deletion and application inactivity.

These are educational one-worker pilots within each VM's runtime, not evidence of a Spark cluster spanning both VMs. Participant terminal access, concurrent capacity, isolation and failure-path recovery remain unvalidated.

The tested Step 2 organiser runner applies explicit resource limits and independently checks application inactivity and owned-client removal. The participant client retains its existing `{'kind': 'pyspark'}` session payload; guided activities add no resource limits. It deletes only the returned owned session ID and polls until GET returns **HTTP 404** before reporting removal. This confirms owned session-resource disappearance, not independent proof that every Spark application or executor has terminated. The organiser must approve the participant submission path and existing resource configuration before use.

The new five-activity path has offline regression checks only. Prior full-analysis container tests do not validate the guided participant commands, access, concurrent capacity or failure recovery. Guided participant execution remains unvalidated.

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


### Direct-submission logging

Participant `test` and `analyse` submissions use WARN-level driver logging by
default. Warnings, errors, application results and the remote exit status remain
visible; the launcher does not filter either SSH output stream.

For troubleshooting, retain the Spark image's original driver logging:

```bash
python3 spark_direct_submit.py test --verbose
python3 spark_direct_submit.py analyse --activity 1 --verbose
```

Quiet submissions upload a small fixed-content Log4j2 profile to
`/home/workshop/work/.spark-direct-log4j2-warn.properties` over the existing
host-key-verified SFTP connection. It remains in the assigned client workspace
and is selected only for the submitted driver. An upload failure stops submission.
`--verbose` skips the upload and driver logging override. Custom `run` commands,
master/worker logging, Livy and organiser-validation logging remain unchanged.
Executor logs viewed separately are not quieted by this driver profile.

This launcher-only change needs no image rebuild or runtime restart. The updated
launcher must still be delivered to participant workspaces. Offline regression
tests do not establish live JVM behaviour; validate quiet and verbose submissions
before relying on the new output policy.
