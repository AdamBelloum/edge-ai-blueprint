# Spark participant instructions — managed workshop

> **Pilot status:** organiser-controlled container tests have passed on both Tier-2 VMs, but participant execution is not yet validated. Read the guides now; submit work only after the organiser confirms your assigned runtime, launch command, data access, network path and output retrieval.

## Learning path

1. Read `README.md`.
2. Open `01_spark_basics.ipynb` and read the Step 1 guide.
3. Use the organiser-approved terminal submission path for `01_spark_basics.py`.
4. Check the results and cleanup before continuing.
5. Open `02_spark_via_livy.ipynb` and read the Step 2 guide.
6. Use the approved Step 2 terminal submission path and check its results and cleanup.

Both notebooks contain **Markdown cells only**. They serve as participant manuals. There are no code cells to execute, no required kernel selection and no notebook/script alternatives to choose between. The scripts perform the exercises described by the guides.

## Responsibilities and preparation

The organiser provides infrastructure, the approved execution environment, dataset access, connection settings, resource controls and result retrieval. Participants read the guides, use approved submission commands, inspect results and report problems.

Do not install dependencies, manage Docker, change ports, guess settings, substitute local Spark or use organiser-only test scripts as participant commands. JupyterHub login alone does not establish access to Spark or Livy.

Open the assigned Spark workspace in JupyterLab. Confirm that both guides, both scripts and `data/Bank_Personal_Loan_Modelling.csv` are present. Open a terminal when the organiser confirms execution readiness.

**The exact launch commands are not yet established by this documentation update.** Obtain them from the organiser. Do not assume that running a script with the terminal's default Python reproduces the validated container path.

Run one exercise at a time. After interruption or uncertain cleanup, ask the organiser to inspect the application/session before retrying.

## Step 1 — Direct Spark submission

### Read, submit and observe

Read `01_spark_basics.ipynb`, then use the exact Step 1 terminal command supplied by the organiser. It must run `01_spark_basics.py` in the prepared environment. The script performs all stages automatically; the notebook explains what to observe.

The application's driver runs in that submission environment, not in the Markdown notebook. Workers launch executors, and executors need to connect back to the driver. Reaching the master alone is insufficient.

Prepared settings include `SPARK_MASTER_URL`, `SPARK_DATA_PATH` and `SPARK_DRIVER_HOST`, with optional `SPARK_DRIVER_PORT` and `SPARK_BLOCK_MANAGER_PORT` when needed. Local preview and distributed read paths may differ but must identify the same supplied snapshot.

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

The script writes `outputs/filtered_preview.csv` relative to its own directory. It contains the `Age,Income,Family` header and at most ten rows. An empty result produces a header-only file. Rerunning replaces the preview; retain earlier results first if needed.

Use the printed `Saved:` path and approved output retrieval method. Container-local paths are not automatically visible in JupyterLab. This is a bounded preview, not a full distributed CSV export. Do not remove the row limit.

Once it obtains a Spark session, the script attempts `spark.stop()` in a `finally` block after success or an analysis error. Normal completion prints `Spark session stopped.` and `Analysis completed successfully.` Shared cluster containers remain running.

Cleanup may fail or be interrupted. A closed terminal is not proof of application termination. Follow any additional runner checks and report uncertainty before proceeding.

## Step 2 — Spark through Livy

### Read, submit and understand the new path

After Step 1 cleanup, read `02_spark_via_livy.ipynb`. Use the organiser's exact approved terminal command for the Step 2 analysis or bounded wrapper. The guide contains no imports or executable statements.

The prepared client sends requests over HTTP; the driver runs on the Livy side and executors run on Spark workers. The organiser supplies `LIVY_URL` and `LIVY_DATA_PATH`. Do not reuse Step 1 callback settings or guess addresses.

The current helper assumes approved access without additional API authentication. JupyterHub authentication does not itself secure Livy. Do not expose the service publicly or disable TLS verification.

### Observe session readiness and results

1. Preview the local CSV.
2. Create a PySpark session and wait until it is ready.
3. Submit the read, filter and grouped-count activities.
4. Retrieve output using returned session and statement IDs.
5. Transfer at most ten filtered rows to the local Step 2 preview.
6. Request deletion of this exercise's session.

Creation and execution are asynchronous. Helpers poll with bounded waits and report errors. Keep the printed session ID and assigned service for reporting; IDs are local to each Livy service. Do not assume zero or use another participant's session ID.

Compare the schema and counts with Step 1 for the same snapshot. Preview ordering need not match. Both organiser-controlled Tier-2 Livy tests returned the counts listed above.

### Output and cleanup limits

The script writes `outputs/02_filtered_preview.csv` relative to its own directory. Rerunning replaces this preview, not Step 1's output or the source CSV. Follow the approved result retrieval instructions.

The standalone script attempts session deletion in a `finally` block after obtaining an ID. `Session deletion requested; cluster containers remain running.` means a request was accepted, not that teardown has finished.

The tested organiser runner additionally applies explicit session resource limits and checks session disappearance, application inactivity and owned-client removal. The standalone script does not perform those same resource and teardown checks. Do not bypass the organiser-approved launch path.

If creation times out without returning an ID, an orphan session may exist. Ask the organiser to inspect it before retrying. Closing the terminal, notebook or JupyterHub server does not guarantee remote session deletion. Never delete other sessions or stop shared containers.

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
