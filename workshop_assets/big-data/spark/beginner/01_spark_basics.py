"""Run the Spark beginner workshop without opening the Jupyter notebook.

Role
----
This is the terminal-based alternative to ``01_spark_basics.ipynb``.
It follows the same activities: preview the local CSV, connect to the prepared
Spark cluster, inspect the schema, filter records, count loan-outcome categories,
and export a small preview. It is not a Docker deployment or installation tool.

Prerequisites and usage
-----------------------
The organiser must first validate the compatible Python/PySpark/Java environment,
cluster connection and worker-to-driver networking. In a participant terminal,
run this script using that prepared Python interpreter::

    python 01_spark_basics.py

Here, ``python`` must refer to the organiser-prepared interpreter, not an
arbitrary system Python or the administrator's Ansible virtual environment.
Selecting a notebook kernel does not necessarily select the terminal interpreter.
Do not install packages, start Docker containers or invent connection settings.
The script is an alternative entry point, not a workaround for an unready runtime.

The organiser supplies these environment variables:

* SPARK_MASTER_URL: Spark master URL for the assigned workshop cluster.
* SPARK_DATA_PATH: CSV path accessible to the Spark driver and executors.
* SPARK_DRIVER_HOST: notebook/terminal driver address reachable from the workers.
* SPARK_DRIVER_PORT: optional fixed driver port required by the network setup.
* SPARK_BLOCK_MANAGER_PORT: optional fixed block-manager port.

Input and output
----------------
The local preview reads ``data/Bank_Personal_Loan_Modelling.csv`` relative to this
script. Spark reads SPARK_DATA_PATH, which must refer to the same supplied dataset
in the prepared execution environment. The supplied dataset has 5,000 records;
column meanings, units and category coding must be checked against its source.
The script retains the source values and does not clean or repair the dataset.

The output is ``outputs/filtered_preview.csv`` beside this script. At most ten
filtered rows are collected to the driver and written as a single local CSV.
Re-running replaces that file, including any preview previously exported by the
notebook. Without an explicit ordering, the selected rows need not be identical
between runs. This bounded preview is not a full distributed result export.

The Spark session is stopped after the analysis, including if an analysis or
export step fails. Successful completion prints the output path. If preparation
or execution fails, stop and share the error with the organiser.
"""

import csv
import os
from pathlib import Path
import sys


REQUIRED_SETTINGS = (
    "SPARK_MASTER_URL",
    "SPARK_DATA_PATH",
    "SPARK_DRIVER_HOST",
)
OPTIONAL_SETTINGS = (
    "SPARK_DRIVER_PORT",
    "SPARK_BLOCK_MANAGER_PORT",
)


def preview_local_dataset(dataset: Path, limit: int = 5) -> None:
    """Print column names and a bounded preview without starting Spark.

    Args:
        dataset: Local CSV supplied in the participant workspace.
        limit: Maximum number of data records to display; defaults to five.

    Raises:
        FileNotFoundError: The expected local CSV is absent.
        ValueError: The CSV does not provide a header row.
    """
    if not dataset.is_file():
        raise FileNotFoundError(
            "The local dataset is missing: {}. Ask the organiser to check "
            "workspace preparation.".format(dataset)
        )

    print("\n--- 1. Local dataset preview ---")
    # utf-8-sig accepts UTF-8 files with or without a byte-order mark.
    # newline='' lets the CSV reader handle the source line endings.
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
    """Read the organiser-provided Spark configuration without inventing defaults.

    Returns:
        A dictionary containing required settings and nonempty optional ports.

    Raises:
        RuntimeError: One or more required settings are missing or empty.
    """
    settings = {
        name: os.environ.get(name, "").strip()
        for name in REQUIRED_SETTINGS + OPTIONAL_SETTINGS
    }
    missing = [name for name in REQUIRED_SETTINGS if not settings[name]]
    if missing:
        raise RuntimeError(
            "Workspace preparation is incomplete: missing {}. Stop and ask "
            "the organiser; do not guess these settings.".format(", ".join(missing))
        )
    return {name: value for name, value in settings.items() if value}


def create_spark_session(settings: dict):
    """Connect the script's driver to the prepared Spark cluster.

    Args:
        settings: Configuration returned by read_connection_settings().

    Returns:
        A SparkSession connected using the organiser-provided master URL.

    Raises:
        RuntimeError: PySpark is unavailable in the selected interpreter.
        Exception: Spark startup or connection errors propagate to the caller.

    The driver runs where this script runs; executors run on Spark workers.
    Workers must connect back to the advertised driver address. Binding to all
    local interfaces does not by itself make the driver reachable or secure;
    routing, port access and network isolation are organiser responsibilities.
    """
    # Import only after checking the prepared connection settings. No packages
    # are installed by this script, and there is no local-mode fallback.
    try:
        from pyspark.sql import SparkSession
    except ImportError as error:
        raise RuntimeError(
            "PySpark is unavailable in this Python environment. Use the "
            "organiser-prepared interpreter; do not install packages yourself."
        ) from error

    builder = (
        SparkSession.builder
        .appName("BankLoanAnalysis")
        .master(settings["SPARK_MASTER_URL"])
        .config("spark.driver.host", settings["SPARK_DRIVER_HOST"])
        .config("spark.driver.bindAddress", "0.0.0.0")
    )
    # Use fixed callback ports only when the organiser has supplied them.
    for spark_setting, environment_name in (
        ("spark.driver.port", "SPARK_DRIVER_PORT"),
        ("spark.blockManager.port", "SPARK_BLOCK_MANAGER_PORT"),
    ):
        if environment_name in settings:
            builder = builder.config(spark_setting, settings[environment_name])

    return builder.getOrCreate()


def export_preview(result_df, output_dir: Path) -> Path:
    """Collect at most ten filtered rows and write one local preview CSV.

    Args:
        result_df: Spark DataFrame containing Age, Income and Family.
        output_dir: Participant-owned local directory for exported results.

    Returns:
        Path of the CSV written, including its header row.

    The existing filtered_preview.csv is replaced. This deliberately matches
    the notebook and differs from Spark's distributed CSV writer, which creates
    an output directory with part files. No shared worker directory is modified.
    """
    # Collect the bounded result before opening the output file, so a failed
    # Spark action does not truncate an existing preview.
    rows = result_df.limit(10).collect()
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / "filtered_preview.csv"

    with output_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(result_df.columns)
        for row in rows:
            writer.writerow(tuple(row))

    return output_file


def analyse_dataset(spark, settings: dict, workspace: Path) -> Path:
    """Perform the notebook's Spark analysis and export its bounded preview.

    Args:
        spark: Prepared SparkSession.
        settings: Organiser-provided connection and dataset settings.
        workspace: Local directory containing this script and outputs/.

    Returns:
        Path to the exported local filtered preview.

    Processing errors propagate to main(), which stops the Spark session.
    Counts are computed from the actual input; no outcome totals are assumed.
    """
    print("\n--- 3. Read CSV and inspect schema ---")
    # header uses the CSV column names; inferSchema infers their Spark types.
    # The distributed read uses the prepared path, not the local preview path.
    df = (
        spark.read.format("csv")
        .option("header", "true")
        .option("inferSchema", "true")
        .load(settings["SPARK_DATA_PATH"])
    )
    df.printSchema()
    df.show(5)
    print("Number of records:", df.count())

    print("\n--- 4. Filter records where Age > 30 ---")
    # select/filter build a lazy execution plan. show/count trigger Spark jobs.
    # Age == 30 is excluded: the condition is strictly greater than 30.
    result_df = df.select("Age", "Income", "Family").filter(df.Age > 30)
    result_df.show(10)
    print("Matching records:", result_df.count())

    print("\n--- 5. Count Personal Loan categories ---")
    # Display the source category codes. Consult the dataset documentation for
    # their meaning; this exercise is aggregation, not predictive modelling.
    df.groupBy("Personal Loan").count().orderBy("Personal Loan").show()

    print("\n--- 6. Export a small local preview ---")
    return export_preview(result_df, workspace / "outputs")


def main() -> None:
    """Run the complete terminal alternative and release its Spark session.

    Workspace paths are resolved relative to this script, so running it from
    another working directory does not change the local input/output locations.
    Once a SparkSession has been obtained, finally attempts to stop it whether
    analysis succeeds or fails. Startup failures are reported without claiming
    that a usable session was created.
    """
    workspace = Path(__file__).resolve().parent
    dataset = workspace / "data" / "Bank_Personal_Loan_Modelling.csv"
    preview_local_dataset(dataset)
    settings = read_connection_settings()

    print("\n--- 2. Connect to the prepared Spark cluster ---")
    spark = create_spark_session(settings)
    try:
        print("Spark version:", spark.version)
        print("Spark master:", spark.sparkContext.master)
        output_file = analyse_dataset(spark, settings, workspace)
        print("Saved:", output_file)
    finally:
        print("\n--- 7. Stop the Spark session ---")
        spark.stop()
        print("Spark session stopped.")

    print("Analysis completed successfully.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAnalysis interrupted. Report any connection problems to the organiser.",
              file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print("\nERROR: {}: {}".format(type(error).__name__, error), file=sys.stderr)
        print("Stop and share this error with the organiser. Do not install software "
              "or manage Docker containers yourself.", file=sys.stderr)
        raise SystemExit(1)
