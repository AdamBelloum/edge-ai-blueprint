# Big Data — Spark participant workspace

> **Pilot status — not yet ready for participant execution.** The organiser must validate the Python runtime, Spark connection, dataset access and worker-to-driver networking before either interface is used. Neither interface is a workaround for incomplete preparation.

## Start here

Choose your preferred interface:

- **Notebook:** open `01-spark-beginner.ipynb` in JupyterLab, select the prepared Python kernel, and run the cells in order.
- **Python script:** run `python data-analytics.py` in a terminal using the organiser-prepared Python interpreter. The terminal's default Python may differ from the notebook kernel.

Both routes perform the same analysis activities and export `outputs/filtered_preview.csv`. Re-running either replaces that file.

Do not install Spark, Java or Python packages, or manage Docker containers.
The organiser prepares the runtime and your group's Spark cluster.

## Included files

- `01-spark-beginner.ipynb`: guided bank-loan analysis.
- `data-analytics.py`: documented terminal-based alternative to the notebook, using the same prepared Spark connection and analysis steps.
- `data/Bank_Personal_Loan_Modelling.csv`: the included input dataset.
- `docs/spark-DA.pdf`: teaching material.
- `participants-instructions.md`: managed-workshop guide for both participant interfaces.
- `outputs/`: created by either interface for your own exported results.

The organiser provisions Spark separately using the managed runtime configuration. The legacy `docker-compose.yml` is not delivered to participant workspaces and is not used for managed provisioning.

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
file delivery, group connection settings and end-to-end execution of both interfaces still need
integration and validation before this workspace is ready for participants.
