# Spark participant instructions — managed workshop

> **Pilot status:** do not run either interface until the organiser confirms that
> the runtime, dataset access, cluster connection and driver networking are ready.
> These instructions describe the intended workflow, not a validated deployment.

## Responsibilities and preparation

The organiser provides the compatible Python/PySpark/Java environment, Spark
cluster, dataset and connection settings. Do not install dependencies, manage
Docker containers, change ports, guess settings or substitute local Spark.
You may inspect the files, run prepared exercises and save your own results.

Open the organiser-provided Spark workspace in JupyterLab. Confirm the CSV exists
under `data/`. Use the organiser-designated notebook kernel or terminal interpreter.
Selecting a notebook kernel does not select the terminal's Python. The administrator's
Ansible environment is not automatically the participant runtime.

Use one interface at a time. Stop its Spark session before switching, particularly
when fixed callback ports are configured. Both routes replace the same preview.

## Option A: guided notebook

1. Open `01-spark-beginner.ipynb` from the Spark workspace directory.
2. Select the organiser-prepared Python kernel.
3. Read the explanations and run cells in order using **Shift+Enter**.
4. Wait for each cell to finish before running dependent cells.
5. Find your preview under `outputs/` and run the final cleanup cell.

After an error, do not continue dependent cells. If a usable `spark` session exists,
run the final cleanup cell. After stopping Spark, restart the kernel and begin
again from the first cell if you want to repeat the exercises.

## Option B: terminal Python script

Open a JupyterLab terminal in the Spark workspace. Run the following only if the
organiser confirms that `python` selects the prepared interpreter; otherwise use
the exact interpreter command supplied by the organiser:

```bash
python data-analytics.py
```

The script resolves local paths relative to its own location and performs the
same analysis activities as the notebook. Once it obtains a Spark session, it
attempts to stop it after success or an analysis/export failure.

Successful completion prints the saved path and `Analysis completed successfully.`
An error and nonzero exit status mean the run did not complete successfully.

## Prepared connection

The organiser supplies `SPARK_MASTER_URL`, `SPARK_DATA_PATH` and `SPARK_DRIVER_HOST`,
plus optional `SPARK_DRIVER_PORT` and `SPARK_BLOCK_MANAGER_PORT` when required.
Workers/executors need to connect back to the driver; reaching the master alone
is insufficient. The local preview and distributed read must use the same supplied
dataset, even when their paths differ. Do not guess replacement values.

## Analysis and expected outcomes

Both routes preview up to five local records, connect to Spark, inspect the schema
and count the complete input. The supplied local CSV contains **5,000 records**.
They select `Age`, `Income` and `Family`, retain `Age > 30`, display up to ten matches
and count all matches. `Age == 30` is excluded. They also count the observed
`Personal Loan` categories. Matching/category counts are computed, not assumed.

Check field meanings, units and category definitions against the dataset source
and teaching material. This is descriptive analysis, not predictive modelling.
Neither interface cleans or modifies the input. Session creation alone does not
prove successful distributed processing or that every available worker ran tasks.

## Export and cleanup

`outputs/filtered_preview.csv` has the `Age`, `Income` and `Family` header and at
most ten data rows. An empty filtered result produces a header-only CSV.
Re-running either interface replaces it; rename or download earlier results first.
Rows are not explicitly ordered, so previews can differ between runs.

This bounded local collection is not a full export or Spark's distributed CSV
output directory. Do not remove the limit to collect an arbitrarily large dataset.
Shared worker input is not modified. Stopping your session releases application
resources; it does not stop the organiser's cluster containers.

## Troubleshooting

- **Missing local CSV:** check the workspace location; ask the organiser to verify delivery.
- **Missing configuration:** report the named settings; do not invent values.
- **Missing PySpark / Java startup error:** ask the organiser to check the kernel/interpreter.
- **Timeout or refused connection:** interrupt a blocked notebook cell and report the error;
  do not change ports or start containers.
- **Spark input path unavailable:** ask the organiser to check driver/executor dataset access.
- **Output permission error:** report the path and error; do not change shared permissions.

Report the interface, failing activity and error text. Do not continue after failure
or install software to work around it.

## References and historical material

Use `README.md`, the guided notebook and the documented Python script for the
managed workflow. `docs/spark-DA.pdf` is accompanying teaching material pending
its separate review; consult the organiser if it conflicts with this workflow.

The original Docker tutorial is archived in the source repository at
`docs/archive/spark-standalone-docker-tutorial.md`, outside the participant bundle.
Its commands are not current participant instructions or managed provisioning.
