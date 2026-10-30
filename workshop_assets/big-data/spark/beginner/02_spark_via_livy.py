#!/usr/bin/env python3
"""Exercise 2 — bank-loan analysis through pre-deployed Livy.

This is the terminal alternative to 02_spark_via_livy.ipynb, NOT an additional
exercise or an advanced solution. Choose either interface. Complete Exercise 1
first and stop its Spark session before proceeding.

Use the organiser-prepared interpreter:
    python 02_spark_via_livy.py

With neither LIVY_URL nor LIVY_DATA_PATH set, the shipped access helper uses
managed SSH credentials to open temporary loopback-only Livy forwarding.
It verifies the supplied CSV bytes on the driver and an executor before
analysis. No manual tunnel, Livy variables or software installation is needed.

Complete explicit organiser LIVY_URL and LIVY_DATA_PATH overrides remain
supported. Partial overrides fail; explicit paths remain organiser-validated.

This client creates/deletes its own Livy session, not infrastructure. It does
not install software, start containers or create a local SparkSession. Livy
must already be configured for the assigned Spark cluster. This simple client
assumes organiser-approved network access without additional API authentication;
do not expose an unauthenticated Livy service publicly.

Pilot status: this new client requires live validation against the deployed
Livy service. Exercise 1's validation is not evidence that Exercise 2 works.
"""

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


def analysis_steps(data_path: str):
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


def main() -> None:
    """Run the existing analysis with scoped access and owned-session cleanup."""
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
            for heading, code in analysis_steps(data_path):
                print(f'\n--- {heading} ---')
                print(run_statement(base_url, session_id, code))
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
    try:
        main()
    except KeyboardInterrupt:
        print("\nAnalysis interrupted. Report connection or cleanup problems to the organiser.",
              file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(f"\nERROR: {type(error).__name__}: {error}", file=sys.stderr)
        print("Stop and share this error with the organiser. Do not install software "
              "or manage containers yourself.", file=sys.stderr)
        raise SystemExit(1)
