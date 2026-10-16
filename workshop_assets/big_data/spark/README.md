# Big Data — Spark participant workspace

## Start here

1. Open `01-spark-beginner.ipynb` in JupyterLab.
2. Select the prepared Python kernel and run the cells in order.
3. Find your exported preview under `outputs/`.

Do not install Spark, Java or Python packages, or manage Docker containers.
The organiser prepares the runtime and your group's Spark cluster.

## Included files

- `01-spark-beginner.ipynb`: guided bank-loan analysis.
- `data-analytics.py`: the original container-based analysis, with corrected data and output paths.
- `data/Bank_Personal_Loan_Modelling.csv`: the included input dataset.
- `docs/spark-DA.pdf`: teaching material.
- `participants-instructions.md`: the original standalone Docker tutorial, retained for reference.
- `outputs/`: created by the notebook for your own results.

The source bundle also retains `docker-compose.yml` for organiser provisioning.
It is not a participant setup requirement.

## Prepared connection

Workspace preparation must provide a compatible PySpark/Java runtime and these settings:

- `SPARK_MASTER_URL`: your group's Spark master address.
- `SPARK_DATA_PATH`: the CSV path accessible to the driver and workers.
- `SPARK_DRIVER_HOST`: the notebook driver address reachable from Spark workers.
- `SPARK_DRIVER_PORT` and `SPARK_BLOCK_MANAGER_PORT`, when fixed ports are required.

If the notebook reports missing configuration, missing dependencies or connection errors,
report the error to the organiser. Do not work around it by installing software yourself.

## Integration status

These are participant assets, not proof of a working deployment. Runtime preparation,
file delivery, group connection settings and end-to-end notebook execution still need
integration and validation before this workspace is ready for participants.
