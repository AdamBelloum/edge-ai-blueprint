# Spark participant instructions — managed workshop

> **Pilot status:** organiser-controlled container tests have passed on both Tier-2 VMs, but participant execution is not yet validated. Read the guides now; submit work only after the organiser confirms your assigned runtime, launch command, data access, network path and output retrieval.

## Learning path

1. Read `README.md`.
2. Open `01_spark_basics.ipynb` and read the Step 1 guide.
3. Read `STEP1-DIRECT-SUBMISSION.md`; after organiser permission, run `python3 spark_direct_submit.py test`. After successful completion and approval, follow the five numbered activities in the notebook, one submission at a time.
4. Check the results and cleanup before continuing.
5. Open `02_spark_via_livy.ipynb` and read the Step 2 guide.
6. After separate Step 2 approval, follow its five numbered activities one command at a time; record predictions, observations and reflection, then check results and owned-session cleanup.

Both notebooks contain **Markdown cells only**. They serve as participant manuals. There are no code cells to execute, no required kernel selection and no notebook/script alternatives to choose between. The scripts perform the exercises described by the guides.

## Responsibilities and preparation

The organiser provides infrastructure, the approved execution environment, dataset access, connection settings, resource controls and result retrieval. Participants read the guides, use approved submission commands, inspect results and report problems.

Do not install dependencies, manage Docker, change ports, guess settings, substitute local Spark or use organiser-only test scripts as participant commands. JupyterHub login alone does not establish access to Spark or Livy.

Open the assigned Spark workspace in JupyterLab. Confirm that both guides, both scripts and `data/Bank_Personal_Loan_Modelling.csv` are present. Open a terminal when the organiser confirms execution readiness.

**The managed Step 1 commands are documented in `STEP1-DIRECT-SUBMISSION.md`, but actual participant execution remains unvalidated.** Use them only after organiser permission and confirmation of your prepared Python environment. Do not run the analysis script directly in JupyterLab. Step 2 still requires its own separately approved launch command.

Run one exercise at a time. After interruption or uncertain cleanup, ask the organiser to inspect the application/session before retrying.

## Step 1 — Direct Spark submission

### Read, submit and observe

Use `01_spark_basics.ipynb` as the guided learning sequence and
`STEP1-DIRECT-SUBMISSION.md` for operational access and safety instructions.
The notebook is Markdown-only; do not execute its displayed Python snippets
in a notebook kernel. After organiser permission, use the prepared terminal:

```bash
cd ~/Big-Data/Spark
python3 spark_direct_submit.py test
```

After successful test completion and organiser approval, **follow the five
numbered activities** in order. For each one:
**read → predict → run → observe → record → reflect**.
Copy only the current activity's command, wait for completion, then return to
the notebook to record your answers before continuing. Do not paste batches.

| Activity | Command to copy individually |
|---|---|
| 1 — Load and inspect | `python3 spark_direct_submit.py analyse --activity 1` |
| 2 — Select columns | `python3 spark_direct_submit.py analyse --activity 2` |
| 3 — Filter rows | `python3 spark_direct_submit.py analyse --activity 3` |
| 4 — Count categories | `python3 spark_direct_submit.py analyse --activity 4` |
| 5 — Export and retrieve | `python3 spark_direct_submit.py analyse --activity 5` |

Each activity is an independent application with its own preparation and session
cleanup attempt. No live DataFrame is retained between submissions. Activities
1–4 do not write or download a preview. For activity 5, check execution completion
and local preview retrieval separately. An older preview does not prove success.
After an error, interruption or uncertain cleanup, stop and request organiser
inspection before another submission.

The full `python3 spark_direct_submit.py analyse` command remains an
**optional organiser-requested reference**, not an additional required
submission in the guided exercise. It runs all original analysis stages and
downloads a bounded preview.

The launcher uses your group's managed credentials under `~/.ssh/spark-direct/`
and verifies the organiser-pinned SSH host key. Do not create an `.access`
folder, transfer credentials manually, guess addresses or change security checks.

JupyterHub transports commands and files. The driver runs in the assigned
client container, not in JupyterLab or the reading guide. The prepared client
supplies Spark connection settings and dataset paths; workers launch executors
that need to connect back to that driver. Reaching the master alone is
insufficient. This is a VM-local one-worker pilot, not a cross-VM Spark cluster.

`test` submits SparkPi. `analyse` uploads and submits the existing
`01_spark_basics.py`; it performs the analysis automatically. Commands use real
`spark-submit`, one executor core, 512 MB driver/executor memory, and remote
timeouts of 120 seconds for the test and 300 seconds for analysis.

**One active submission per group/client.** Group members share remote script
and output filenames; the launcher does not enforce a concurrency lock.
Unique local download directories do not prevent remote job collisions.

### Analysis checks

Observe the local preview, Spark version/master, inferred schema, five-row data preview, full count, strict age filter and grouped category counts.

| Check for the supplied snapshot | Expected result |
|---|---:|
| Input records | 5,000 |
| Records with Age > 30 | 4,376 |
| Personal Loan raw code 0 | 4,520 |
| Personal Loan raw code 1 | 480 |

Age exactly 30 is excluded. Preview rows are not explicitly ordered. Category counts sum to the input count. These counts were checked locally and observed in the organiser-controlled Tier-2 Livy tests; participant execution is a separate readiness check.

Check units and code meanings against source documentation. The dataset has 52 negative `Experience` values; discuss them rather than changing the input. Consult the README for the fingerprint and unresolved provenance, category definitions and permissions.

### Output and cleanup

The analysis writes `outputs/filtered_preview.csv` in the assigned remote
client. It has the `Age,Income,Family` header and at most ten rows; an empty
filter result produces a header-only file. It is a bounded preview, not a full
distributed CSV export. Do not remove the row limit.

After a successful remote analysis, the launcher downloads the preview to a
new local `outputs/remote-<unique-id>/filtered_preview.csv` directory beside
the submitted script. In the default workspace this is beneath
`~/Big-Data/Spark`. Follow the printed `Downloaded preview:` path in JupyterLab.
Each download uses a new directory, while a remote rerun replaces the shared
remote preview. If retrieval fails after `Remote exit status: 0`, report the
retrieval error rather than automatically resubmitting the Spark job.

After obtaining a Spark session, the analysis attempts `spark.stop()` in a
`finally` block. Normal completion prints `Spark session stopped.`,
`Analysis completed successfully.` and `Remote exit status: 0`. Shared runtime
containers remain running. Check successful output download separately.

After a timeout, disconnection, interruption or cleanup warning, ask the
organiser to inspect the remote driver/application before retrying or allowing
another group member to submit. A closed terminal or SSH connection does not
prove remote termination. Do not stop shared containers or expose credentials
in error reports.

Participant validation and non-destructive stopping are not automated yet.
Publication, organiser-only tests and a successful SparkPi run do not alone
establish all-group readiness, data access, output retrieval, isolation or
cleanup. Do not continue to Step 2 until its separate launch path is approved.

## Step 2 — Spark through Livy

### Read, predict, submit and reflect

Complete Step 1 and resolve its cleanup first. Wait for **separate Step 2 organiser
approval**, then use matching updated copies of `02_spark_via_livy.ipynb`,
`02_spark_via_livy.py` and `spark_livy_access.py`. The notebook is Markdown-only;
do not execute its displayed Python snippets in a kernel.

In the prepared JupyterLab terminal, use `~/Big-Data/Spark`. Follow the notebook's
**five numbered activities**, using **read → predict → run → observe → record →
reflect**. Copy one command, wait for completion, record answers, and only then
continue. Do not paste batches.

| Activity | Command to copy individually |
|---|---|
| 1 — Load and inspect | `python3 02_spark_via_livy.py --activity 1` |
| 2 — Select columns | `python3 02_spark_via_livy.py --activity 2` |
| 3 — Filter rows | `python3 02_spark_via_livy.py --activity 3` |
| 4 — Count categories | `python3 02_spark_via_livy.py --activity 4` |
| 5 — Export and retrieve | `python3 02_spark_via_livy.py --activity 5` |

The no-option `python3 02_spark_via_livy.py` command remains an **optional
organiser-requested reference**, not an additional required submission. It runs
the original full analysis and preview export in one owned session.
**Guided participant execution remains unvalidated.**

### Prepared access and independent sessions

The terminal runs the HTTP client; the driver runs on the Livy side and executors
run in the assigned VM's worker. With neither Livy override supplied, the existing
helper uses `~/.ssh/spark-direct/login_key` and `known_hosts` for managed,
loopback-only SSH forwarding. It verifies the supplied CSV's SHA-256 on the driver
and one executor before analysis. No manual tunnel, exported settings or software
installation is needed.

Complete explicit organiser `LIVY_URL` and `LIVY_DATA_PATH` overrides remain
supported; partial overrides fail. That explicit path does not perform automatic
managed dataset verification and needs organiser validation. Participants must
not set overrides, reuse Step 1 callback settings, or guess addresses.
JupyterHub authentication does not itself secure Livy: do not expose the service,
disable TLS checks, replace host pins, or display or exchange group credentials.

Each activity command owns a **fresh Livy session** and repeats required input
preparation. Variables persist between its statements, not between commands.
Activity 5 recreates the filter rather than reusing activity 3's session.
**One active submission per group; take turns.** There is no client concurrency
lock, and separate session IDs do not prove concurrent capacity.

### Observe readiness, results and completion

Session creation and statement execution are asynchronous. The client uses the
returned IDs, waits for an idle session, then polls each statement's result.
Record the printed session ID, assigned service, Spark version/master, selected
activity output and process exit status. IDs are scoped to the assigned Livy
service; never assume zero or reuse another participant's ID.

Compare the schema, selected-record count, strict age filter and raw category
counts with Step 1 for the same snapshot. Reference results are in the notebook
and README; preview ordering need not match. These references and earlier
organiser tests are not proof of a successful new participant activity.

For normal completion, check both:

- `Owned-session removal confirmed; cluster containers remain running.`
- `Analysis completed successfully; temporary managed forwarding has closed.`

Immediately after the command, `echo $?` should report zero. In explicit-override
mode there is no temporary forwarding, although the existing final message still
mentions it. Activities 1–4 do **not** export a preview or print `Saved:`.

### Output and cleanup evidence

Only activity 5 or full analysis collects at most ten filtered rows on the
Livy-side driver, transfers bounded JSON over HTTP, and writes the participant-
local `outputs/02_filtered_preview.csv`. Check the printed `Saved:` path, the
`Age,Income,Family` header and at most ten data rows. An empty filter produces
only the header. This is not a full distributed CSV export; keep the row limit.

An exporting rerun replaces the Step 2 preview, not Step 1's unique downloads or
the source CSV. Retain a needed result before rerunning. A wrapper that runs in a
separate client container may require additional organiser-approved retrieval.
An older file is not evidence of current success. Report transfer/write failures
and cleanup status rather than automatically resubmitting.

After obtaining a valid ID, the client attempts deletion of **that owned session
only** in a `finally` block. It polls GET for that same service and ID until
**HTTP 404** before reporting removal. An accepted DELETE alone is insufficient.
HTTP 404 confirms session-resource disappearance, not independent verification
that all Spark applications or executors have terminated. Shared containers
remain running; organiser application/worker checks are separate.

The participant client retains its existing `{'kind': 'pyspark'}` creation
payload; this guided change adds no resource limits. The organiser runner's
explicit bounds and independent application/owned-client checks do not transfer
automatically to this launch path. Do not bypass organiser approval.

If creation times out without returning an ID, a session may still exist.
After lost responses, interruption, timeouts, errors or unconfirmed cleanup,
**stop** and report the activity, failing stage, session ID if available, assigned
service, exit status and relevant paths. Closing the terminal, notebook or
JupyterHub server does not guarantee remote deletion. Never guess an ID, delete
other sessions, stop shared containers, expose secrets, or retry while cleanup
is unresolved.

## Troubleshooting

Stop after an error and report the command, failing stage, error text, assigned service, relevant paths and any session/application ID. Do not repeatedly submit work while cleanup is uncertain.

| Problem | Participant action |
|---|---|
| Missing local CSV or script | Report the workspace/path and ask for a delivery check. |
| Missing configuration | Report the named setting; do not invent a value. |
| Missing PySpark, Java or other dependencies | Ask for a prepared-runtime check; do not install software. |
| Refused connection or timeout | Report the error; do not change ports or start services. |
| Remote data path unavailable | Ask the organiser to check driver/executor access. |
| Output permission or visibility issue | Report the printed path; do not change shared permissions. |
| HTTP, authentication or TLS error | Report it; do not disable security checks. |
| Interruption or cleanup warning | Ask for application/session inspection before retrying. |

## Completion checklist

- [ ] I read both Markdown-only guides in order.
- [ ] I used only organiser-approved submission commands.
- [ ] I explained the difference between direct submission and Livy submission.
- [ ] I checked the input, filtered and category counts.
- [ ] I located both bounded previews and understood overwrite behaviour.
- [ ] I checked cleanup and reported any uncertainty before retrying.

## References and historical material

Use `README.md`, the two Markdown-only notebook guides and these instructions for the managed workflow. The Python scripts are execution assets, not alternative notebook interfaces.

`docs/spark-DA.pdf` is conceptual/historical background. Its text-only review identified legacy examples and apparent code problems; do not copy its local/streaming setup into this workshop. Visual checks and slide revisions remain pending.

The original Docker tutorial is archived at `docs/archive/spark-standalone-docker-tutorial.md` in the source repository, outside the participant bundle. Its commands are not current participant instructions or managed provisioning.
