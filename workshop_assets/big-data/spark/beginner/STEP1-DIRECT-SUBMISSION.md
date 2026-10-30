# Participant Step 1 — direct Spark submission

> **Pilot status: participant execution is not yet validated.** The organiser
> menu and credential gate are integrated, but publication is not proof of
> participant access, successful execution, concurrent capacity or cleanup.
> Submit only when the organiser authorises your group's validation or exercise.

Use this guide for managed terminal access and operational safeguards, and
`01_spark_basics.ipynb` for the guided learning activities. The notebook remains
Markdown-only: read, predict, copy each activity command into the JupyterLab
terminal, inspect the output, then return to the notebook to record answers.
All analysis code is supplied in `01_spark_basics.py`.

Use matching updated copies of the notebook, payload and launcher. These files
supersede older Step 1 launch/setup instructions; do not mix the old full-run-only
walkthrough with the guided activity path. The new activity workflow requires
actual participant validation separately from offline source checks. Step 2 is
not enabled by this Stage 1 workflow and requires separate organiser approval.

## Where execution happens

Open a terminal in the assigned JupyterLab workspace:

```bash
cd ~/Big-Data/Spark
```

JupyterHub provides the terminal and SSH/SFTP transport. The Spark driver runs
in your assigned client container; executors run in that VM's Spark worker.
The Spark master stays on the private Docker network. This is a VM-local
one-worker teaching runtime, not a Spark cluster spanning the workshop VMs.

The organiser supplies a Python environment with Paramiko. Participants do not
install Java, PySpark or packages, manage Docker, configure ports, or substitute
local Spark. If `python3` cannot import Paramiko, stop and report the prepared
environment problem.

## Credentials and preparation

For a correctly prepared participant spawn, the managed credential hook uses:

- `~/.ssh/spark-direct/login_key`: your group's private login key.
- `~/.ssh/spark-direct/known_hosts`: the organiser-pinned SSH endpoint identity.

These are group credentials, not individual identities. Do not display, copy
into shared assets, commit, or exchange the private key with another group.
The launcher requires private-key permissions of 0600 or more restrictive.
Do not create an `.access` directory, transfer keys manually, guess an address,
or replace a host-key pin. Report missing credentials or permission errors.

The launcher derives the endpoint from the single pinned `[host]:port` record.
Host-key checking is mandatory; there is no auto-trust, SSH-agent or password
fallback. Advanced transport overrides exist but are not the beginner path.

The prepared client supplies the Spark environment and a dataset link at
`/home/workshop/work/data`. Participants do not create that link or export
`SPARK_MASTER_URL`, `SPARK_DATA_PATH` or `SPARK_DRIVER_HOST` in JupyterLab.

## Managed participant commands

**One active submission per group/assigned client. Take turns.** The launcher
does not enforce a concurrency lock. Group members share the remote script and
preview filenames; unique local download directories do not isolate remote
jobs. Do not submit `test` and `analyse` simultaneously.

### 1. Test the submission path

After organiser permission:

```bash
python3 spark_direct_submit.py test
```

The launcher prints the remote command, submits the bundled SparkPi example
using real `spark-submit`, streams output, and prints `Remote exit status:`.
The command selects the prepared master and client deployment mode, limits
executor cores to one, sets driver/executor memory to 512 MB each, and applies
a 120-second remote timeout. It is not a local-mode fallback.

Look for SparkPi output and `Remote exit status: 0`. This is a participant
submission check, not proof of bank-data access, isolation, capacity or complete
cleanup. The organiser must inspect application/worker evidence before making
an execution-readiness claim. After an error, stop rather than starting analysis.

### 2. Perform the guided bank-data activities

After the test finishes successfully and the organiser permits analysis, follow
`01_spark_basics.ipynb` in order. For each activity:

1. Read its purpose and supplied code explanation in the notebook.
2. Record your prediction before execution.
3. Copy only that activity's command into the prepared JupyterLab terminal.
4. Wait for completion and inspect the requested output.
5. Return to the notebook, record observations and answer the reflection questions.
6. Continue only when completion is confirmed and no cleanup uncertainty remains.

Run **one command at a time**, not all five as a pasted batch:

| Activity | Command to copy | Analysis task |
|---|---|---|
| 1 | `python3 spark_direct_submit.py analyse --activity 1` | Load CSV, inspect schema, count input |
| 2 | `python3 spark_direct_submit.py analyse --activity 2` | Select columns |
| 3 | `python3 spark_direct_submit.py analyse --activity 3` | Filter rows with Age > 30 |
| 4 | `python3 spark_direct_submit.py analyse --activity 4` | Count raw Personal Loan categories |
| 5 | `python3 spark_direct_submit.py analyse --activity 5` | Export and retrieve a bounded preview |

Activity numbers identify learning tasks, not notebook cell positions. The
launcher validates the number before connecting or uploading, uploads the
supplied analysis file, passes the activity argument to real remote
`spark-submit`, and streams output. Do not run `01_spark_basics.py` directly
in JupyterLab or execute its displayed code snippets in a notebook kernel.

Each activity is an independent application. It previews the CSV locally in the
remote client, uses the prepared settings, creates a Spark session, loads its
required data, performs the selected analysis, and attempts the existing session
cleanup. DataFrames and live sessions do not persist between commands. Activity 5
recreates the age filter; it does not rely on a surviving activity 3 session.
Schema inference can itself require processing during input preparation.

Submission settings are unchanged: one executor core, 512 MB driver/executor
memory each, client deployment mode, and a 300-second remote timeout.
Check `Spark session stopped.`, `Analysis completed successfully.` and
`Remote exit status: 0` for each successful activity. These messages do not prove
cleanup after interruption. After an error or uncertain completion, stop and
request organiser inspection before retrying.

**Activities 1–4 do not write or download a preview.** An old remote or local
preview is not evidence of their success. Activity 5 writes a bounded preview;
check its download separately as described below.

The existing full-analysis command remains available, but it is not an extra
required submission in the guided exercise. Use it only if the organiser requests:

```bash
python3 spark_direct_submit.py analyse
```

It performs the original complete analysis and downloads the bounded preview.

<details>
<summary>Supplied-snapshot reference checks — consult after recording your observations</summary>

| Check | Expected result |
|---|---:|
| Input records (activity 1) | 5,000 |
| Records after column selection (activity 2) | 5,000 |
| Records with Age > 30 (activity 3) | 4,376 |
| Personal Loan raw code 0 (activity 4) | 4,520 |
| Personal Loan raw code 1 (activity 4) | 480 |

These are checks for the supplied snapshot, not proof of a successful participant
run. Report differences rather than editing the input to match. Preview ordering
may differ. Consult the README for the snapshot fingerprint, negative `Experience`
values and unresolved provenance, field definitions and redistribution permissions.
Do not modify the source data or infer category meanings from these counts.

</details>

### 3. Locate the downloaded preview

After successful activity 5 or full analysis, the launcher downloads the
bounded preview and prints `Downloaded preview:` with its local path. Activities
1–4 skip this retrieval entirely:

```text
outputs/remote-<unique-id>/filtered_preview.csv
```

For the default analysis script, this directory is inside `~/Big-Data/Spark`.
The CSV contains the `Age,Income,Family` header and at most ten rows. An empty
filter result produces a header-only file. This is not a full distributed CSV
export; do not remove the row limit.

Each download gets a new local directory. On the remote client, rerunning
analysis replaces `outputs/filtered_preview.csv`. If downloading fails after
`Remote exit status: 0`, report the retrieval failure; do not automatically
resubmit the Spark job or assume an existing remote preview belongs to your run.

## Completion, interruption and reporting

Each analysis activity, or the full analysis, attempts `spark.stop()` and
normally prints `Spark session stopped.`, `Analysis completed successfully.` and
`Remote exit status: 0`. Shared runtime containers remain running. Successful
download is a separate output check for activity 5 or full analysis only.

A timeout, SSH disconnection, closed terminal or Ctrl-C does not prove remote
termination. The launcher is not a remote process-supervision system. Stop and
ask the organiser to inspect the driver/application before retrying or allowing
another group member to submit. Never stop shared containers yourself.

Report the command, failing stage, error text, remote exit status, application
ID when available, and printed output path. **Do not report private-key content
or credential payloads.** For missing keys, host-key mismatch, missing Paramiko,
dataset errors or connection failures, request organiser inspection; do not
weaken security checks or invent configuration.

## Organiser sequence and remaining limits

Use Big Data / Spark → Stage 1 — direct submission workflow:

1. Check selected context and participant cohort.
2. Prepare the direct runtime and protected credential exports.
3. Start the direct runtime and apply its managed network policies.
4. Review the credential plan, confirm, and stage group-bound credentials.
5. Publish Step 1 after fresh credential verification and confirmation.
6. Validate actual participant login, SparkPi, bank analysis, output retrieval
   and cleanup for each group before announcing readiness.

The preparation helper requires a participant-reachable IPv4 bind address
owned by each selected VM. Configure it through the approved inventory or
protected extra-vars mechanism; participants must not choose the address.

The menu's participant-validation action is not automated yet. Organiser-only
tests, credential verification and publication do not replace participant
validation. Check a fresh/restarted participant server as appropriate: repository
updates do not refresh running servers, and asset delivery preserves existing
participant files. Review outdated delivered copies explicitly; do not blindly
overwrite participant edits.

Non-destructive stopping and full reset/credential lifecycle remain separate
work. Runtime teardown is destructive cleanup, not a normal stop or proof of a
complete workshop reset. Do not switch workshops while cleanup is unresolved.
Do not run legacy private-Livy preparation/startup against the participant-enabled
configuration; Stage 2 requires its own verified integration.
