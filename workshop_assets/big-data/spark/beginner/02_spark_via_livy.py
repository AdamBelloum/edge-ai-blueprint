#!/usr/bin/env python3
"""Step 2 — guided bank-loan activities through pre-deployed Livy.

Read 02_spark_via_livy.ipynb, record predictions, then copy one authorised
activity command into the prepared JupyterLab terminal:
    python3 02_spark_via_livy.py --activity 1
Use activities 1 through 5 separately. Do not execute notebook snippets.
The no-option full analysis remains an optional organiser-requested reference.

Each command owns a new Livy session; variables do not survive between commands.
Only activity 5 or full analysis exports outputs/02_filtered_preview.csv.
An exporting rerun replaces that participant-local preview; retain it first
if needed. Activities 1–4 neither export nor establish freshness of old files.

With neither LIVY_URL nor LIVY_DATA_PATH supplied, the existing access helper
uses group credentials for temporary loopback-only SSH forwarding and verifies
CSV bytes on the driver and one executor. Complete explicit organiser settings
remain supported; partial overrides fail. Explicit paths remain organiser-
validated. Participants do not configure endpoints or install software.

The client does not install software, manage containers or create local Spark.
Session creation still uses the existing {'kind': 'pyspark'} payload; this change
adds no resource limits or runtime configuration. Step 2 needs separate organiser
approval. One active submission per group; no client concurrency lock exists.

Cleanup deletes only the returned owned session ID and polls for HTTP 404.
This confirms session-resource disappearance, not independent verification of
all Spark application/executor termination. Temporary forwarding closes on exit;
closing a terminal does not prove remote cleanup. Stop after errors or uncertain
completion and report the session ID and assigned service, never private keys.

Pilot status: guided participant execution, capacity and failure-path recovery
remain unvalidated. Source checks and organiser tests do not establish readiness.
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen, build_opener, ProxyHandler

HTTP_TIMEOUT = 15
WAIT_TIMEOUT = 120
POLL_INTERVAL = 2
PREVIEW_MARKER = "DIGITAFRICA_PREVIEW_JSON:"


def preview_local_dataset(dataset: Path, limit: int = 5) -> None:
    """Preview the supplied local CSV without contacting Livy or Spark."""
    if not dataset.is_file():
        raise FileNotFoundError(
            f"The local dataset is missing: {dataset}. Ask the organiser to "
            "check workspace preparation."
        )
    print("\n--- 1. Local dataset preview ---")
    with dataset.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("The supplied CSV does not contain a header row.")
        print("Columns:", ", ".join(reader.fieldnames))
        for index, row in enumerate(reader):
            if index >= limit:
                break
            print(row)


def read_connection_settings() -> dict:
    """Require explicit organiser settings; never guess a Livy or data address."""
    names = ("LIVY_URL", "LIVY_DATA_PATH")
    settings = {name: os.environ.get(name, "").strip() for name in names}
    missing = [name for name in names if not settings[name]]
    if missing:
        raise RuntimeError(
            "Workspace preparation is incomplete: missing " + ", ".join(missing)
            + ". Stop and ask the organiser; do not guess these settings."
        )
    url = urlsplit(settings["LIVY_URL"])
    if (url.scheme not in ("http", "https") or not url.hostname
            or url.username or url.password or url.query or url.fragment):
        raise ValueError("LIVY_URL must be an HTTP(S) base URL without credentials, query or fragment.")
    settings["LIVY_URL"] = settings["LIVY_URL"].rstrip("/")
    return settings


def livy_request(base_url: str, method: str, path: str, payload=None):
    """Make one bounded HTTP request using Python's standard library."""
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json", "Content-Type": "application/json",
               "X-Requested-By": "digitafrica-spark-exercise-2"}
    request = Request(base_url + path, data=body, headers=headers, method=method)
    # Loopback forwarding must never route through an HTTP proxy.
    open_url = (build_opener(ProxyHandler({})).open
                if urlsplit(base_url).hostname in ('127.0.0.1', 'localhost')
                else urlopen)
    with open_url(request, timeout=HTTP_TIMEOUT) as response:
        content = response.read()
    return json.loads(content) if content.strip() else {}


def response_id(response: dict) -> int:
    """Use the ID returned by Livy rather than assuming session/statement zero."""
    identifier = response.get("id")
    if type(identifier) is not int or identifier < 0:
        raise RuntimeError("Livy did not return a valid resource ID.")
    return identifier


def wait_for_session(base_url: str, session_id: int) -> None:
    """Wait for an idle session; report failures and bounded-wait expiry."""
    deadline = time.monotonic() + WAIT_TIMEOUT
    while time.monotonic() < deadline:
        session = livy_request(base_url, "GET", f"/sessions/{session_id}")
        state = session.get("state")
        if state == "idle":
            return
        if state in ("error", "dead", "killed", "shutting_down", "success"):
            raise RuntimeError(f"Livy session {session_id} is not usable: {state}.")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Livy session {session_id} did not become idle within {WAIT_TIMEOUT} seconds.")


def run_statement(base_url: str, session_id: int, code: str) -> str:
    """Submit remote code, poll its returned ID, and return plain-text output."""
    path = f"/sessions/{session_id}/statements"
    statement_id = response_id(livy_request(base_url, "POST", path, {"code": code}))
    deadline = time.monotonic() + WAIT_TIMEOUT
    while time.monotonic() < deadline:
        statement = livy_request(base_url, "GET", f"{path}/{statement_id}")
        state = statement.get("state")
        if state == "available":
            output = statement.get("output") or {}
            if output.get("status") != "ok":
                raise RuntimeError(
                    "Remote Spark statement failed: "
                    + str(output.get("ename", "unknown error")) + ": "
                    + str(output.get("evalue", "no error detail"))
                )
            return output.get("data", {}).get("text/plain", "")
        if state in ("error", "cancelled", "cancelling"):
            raise RuntimeError(f"Livy statement {statement_id} ended in state {state}.")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Livy statement {statement_id} exceeded {WAIT_TIMEOUT} seconds.")


def _full_analysis_steps(data_path: str):
    """Exercise 1's read, filter and aggregation, executed in the Livy session."""
    return (
        ("3. Read CSV and inspect schema", f"""
df = (spark.read.format('csv')
      .option('header', 'true')
      .option('inferSchema', 'true')
      .load({data_path!r}))
df.printSchema()
df.show(5)
print('Number of records:', df.count())
"""),
        ("4. Filter records where Age > 30", """
result_df = df.select('Age', 'Income', 'Family').filter(df.Age > 30)
result_df.show(10)
print('Matching records:', result_df.count())
"""),
        ("5. Count Personal Loan categories", """
df.groupBy('Personal Loan').count().orderBy('Personal Loan').show()
"""),
    )


def analysis_steps(data_path: str, activity=None):
    """Return the original full sequence or one activity with required input.

    Activities are independent submissions. Statement variables persist only
    inside the session owned by the current command. Only exporting commands
    subsequently call export_preview(). No connection or Spark execution occurs
    while constructing these statement strings.
    """
    if activity is not None and (type(activity) is not int or activity not in range(1, 6)):
        raise ValueError("Activity must be an integer from 1 to 5.")
    full = _full_analysis_steps(data_path)
    if activity is None:
        return full
    if activity == 1:
        return (full[0],)
    load_code = f"""
df = (spark.read.format('csv')
      .option('header', 'true')
      .option('inferSchema', 'true')
      .load({data_path!r}))
"""
    if activity == 2:
        heading = "Select Age, Income and Family"
        code = """
selected_df = df.select('Age', 'Income', 'Family')
selected_df.show(10)
print('Selected columns:', ', '.join(selected_df.columns))
print('Records after column selection:', selected_df.count())
"""
    elif activity == 3:
        heading, code = full[1]
    elif activity == 4:
        heading, code = full[2]
    else:
        heading = "Prepare the age-filtered bounded preview"
        code = "result_df = df.select('Age', 'Income', 'Family').filter(df.Age > 30)\n"
    return ((f"Load required input for activity {activity}", load_code), (heading, code))


def export_preview(base_url: str, session_id: int, output_dir: Path) -> Path:
    """Transfer at most ten rows as JSON and write a participant-local CSV.

    Unlike Exercise 1, collection happens at the Livy-side driver. The bounded
    result travels back over HTTP. No shared worker file is written or changed.
    """
    code = "import json\nprint(" + repr(PREVIEW_MARKER) + " + json.dumps({" \
        "'columns': result_df.columns, " \
        "'rows': [list(row) for row in result_df.limit(10).collect()]}))"
    text = run_statement(base_url, session_id, code)
    lines = [line for line in text.splitlines() if line.startswith(PREVIEW_MARKER)]
    if len(lines) != 1:
        raise RuntimeError("Livy did not return exactly one bounded preview payload.")
    preview = json.loads(lines[0][len(PREVIEW_MARKER):])
    columns, rows = preview["columns"], preview["rows"]
    if columns != ["Age", "Income", "Family"] or len(rows) > 10:
        raise ValueError("The returned preview does not match the expected columns or row limit.")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ValueError("The returned preview contains an invalid row.")
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "02_filtered_preview.csv"
    with output_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)
    return output_file


def main(activity=None) -> None:
    """Run the existing analysis with scoped access and owned-session cleanup."""
    if activity is not None and (type(activity) is not int or activity not in range(1, 6)):
        raise ValueError('Activity must be an integer from 1 to 5.')
    if activity is not None:
        print(f'Guided Livy activity: {activity}')
    from spark_livy_access import managed_connection, verify_dataset, delete_owned_session
    workspace = Path(__file__).resolve().parent
    local_csv = workspace / 'data' / 'Bank_Personal_Loan_Modelling.csv'
    preview_local_dataset(local_csv)
    with managed_connection(read_connection_settings) as settings:
        base_url = settings['LIVY_URL']
        print("\n--- 2. Connect through the prepared Livy service ---")
        session_id = response_id(livy_request(base_url, 'POST', '/sessions', {'kind': 'pyspark'}))
        print('Created Livy session:', session_id)
        analysis_error = None
        try:
            print('Waiting for the Livy PySpark session...')
            wait_for_session(base_url, session_id)
            print(run_statement(base_url, session_id,
                                "print('Spark version:', spark.version)\n"
                                "print('Spark master:', spark.sparkContext.master)"))
            data_path = settings['LIVY_DATA_PATH']
            if settings['VERIFY_DATASET']:
                data_path = verify_dataset(run_statement, base_url, session_id, data_path, local_csv)
            for heading, code in analysis_steps(data_path, activity=activity):
                print(f'\n--- {heading} ---')
                print(run_statement(base_url, session_id, code))
            if activity in (None, 5):
                print('\n--- 6. Export a small local preview ---')
                print('Saved:', export_preview(base_url, session_id, workspace / 'outputs'))
        except BaseException as error:
            analysis_error = error
            raise
        finally:
            print("\n--- 7. Delete this exercise's Livy session ---")
            try:
                delete_owned_session(livy_request, base_url, session_id)
                print('Owned-session removal confirmed; cluster containers remain running.')
            except Exception as error:
                print(f'WARNING: Cleanup of owned session {session_id} is unconfirmed: {error}. '
                      'Report the assigned service and this session ID to the organiser.', file=sys.stderr)
                if analysis_error is None:
                    raise
    print('Analysis completed successfully; temporary managed forwarding has closed.')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activity", type=int, choices=range(1, 6),
                        help="Run one guided activity; omit for full analysis.")
    args = parser.parse_args()
    try:
        main(activity=args.activity)
    except KeyboardInterrupt:
        print("\nAnalysis interrupted. Report connection or cleanup problems to the organiser.",
              file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"\nERROR: {type(error).__name__}: {error}", file=sys.stderr)
        print("Stop and share this error with the organiser. Do not install software "
              "or manage containers yourself.", file=sys.stderr)
        raise SystemExit(1)
