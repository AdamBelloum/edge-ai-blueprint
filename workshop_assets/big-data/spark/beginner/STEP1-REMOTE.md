# Participant Step 1: real spark-submit from the assigned client

This is an opt-in pilot supplement. It supersedes the old unvalidated Step 1
launch instructions, not the analysis guide. Step 2 participant execution is
not implemented by this increment. Do not use organiser test commands as a
participant interface.

The JupyterHub pod is a terminal/transport only. The Spark driver runs in the
client container; executors run in the assigned VM's Spark worker. The Spark
master stays on the private Docker network. No Java/PySpark installation in
JupyterHub and no access to the Docker daemon is needed.

## Organiser preparation

1. Keep the existing prepare/publish workflow. Install the patch before
   publishing so the existing asset delivery includes this launcher and guide.
2. Configure `big_data_spark_client_bind_ip` separately for each selected VM
   using its participant-reachable IPv4 address. This must be an address owned
   by that VM; do not choose a public-facing interface or wildcard address.
   SSH is key-authenticated, but the client has outbound network access.
3. Run `participant-direct-runtime.sh prepare`. It stages one worker plus Livy
   configuration, builds ONLY the client image, and creates protected SSH keys.
   It starts nothing. It refuses to restage an active Big Data project.
4. Run `participant-direct-runtime.sh start`. It starts master, worker and
   client, never Livy. VM-local SSH readiness is not participant readiness.
5. Give each group ONLY its own `login_key` and `known_hosts` exports from
   ignored `secrets/big-data-spark-direct/<inventory-host>/`, using a protected
   transfer. Place them in that group's JupyterLab workspace `.access/` folder,
   with directory mode 0700 and private-key mode 0600. These are group-level
   credentials, not per-person identities. Do not put them in shared assets.
6. Supply the group's host address. Validate an actual participant login and
   Spark job before announcing readiness. No key material belongs in Git.

This first increment has standalone organiser actions; the existing menu and
private Livy pilot are unchanged. Do not invoke its old prepare/build/start
sequence against this participant-enabled Compose configuration: the old
private-pilot validation intentionally rejects the extra client service.
Reset integration is deferred; the current reset may reject these new assets.
Do not switch workshops or advertise complete cleanup until reset is updated.

## Participant setup

Run in `~/Big-Data/Spark` after receiving your group's credentials:

```bash
mkdir -p .access
chmod 700 .access
chmod 600 .access/login_key .access/known_hosts
# Use the organiser-prepared Python environment; do not install packages here.
export SPARK_CLIENT_HOST='<organiser-supplied-address>'
```

The organiser supplies the Python environment with Paramiko available.
Missing dependencies are an organiser preparation issue, not a participant
installation task.

Set a convenience transport function (the submitted command remains visible):

```bash
remote() {
  python spark_remote.py --host "$SPARK_CLIENT_HOST" --port 2222     --key .access/login_key --known-hosts .access/known_hosts "$@"
}
remote run -- /opt/spark/bin/spark-submit --version
remote put 01_spark_basics.py
```

The legacy script has a local preview path beneath `data/`. Create a link to
exactly the read-only dataset snapshot that the executors also read:

```bash
remote run -- ln -sfn /opt/spark-data/data data
```

## Submit a distributed application

```bash
remote run -- env   SPARK_MASTER_URL=spark://spark-master:7077   SPARK_DATA_PATH=/opt/spark-data/data/Bank_Personal_Loan_Modelling.csv   SPARK_DRIVER_HOST=spark-client   SPARK_DRIVER_PORT=39001   SPARK_BLOCK_MANAGER_PORT=39002   /opt/spark/bin/spark-submit   --master spark://spark-master:7077   --deploy-mode client   --driver-memory 512m   --executor-memory 512m   --total-executor-cores 1   --conf spark.driver.host=spark-client   --conf spark.driver.bindAddress=0.0.0.0   --conf spark.driver.port=39001   --conf spark.blockManager.port=39002   01_spark_basics.py
```

Explain the command before submission: master selection, client deployment
mode, driver/executor memory, executor cores, and executor-to-driver callback
address. The fixed ports and group client mean **one active submission per VM**.
Participants within a group take turns; this is not multi-tenant isolation.

Expected checks for the supplied snapshot: 5,000 input records, 4,376 records
with Age > 30, and Personal Loan counts 4,520 (code 0) and 480 (code 1).
Confirm actual executor execution in the organiser's worker/application evidence;
a successful `--version` check or local-mode result is insufficient.

```bash
remote get outputs/filtered_preview.csv filtered_preview.csv
```

Rerunning replaces the same preview. Do not submit concurrently. After an
interruption, do not assume the remote driver was killed or cleaned up: ask the
organiser to inspect it. The launcher closes its SSH connection but is not a
remote process supervision system.

## Remaining sprint work

- Integrate the explicit Step 1 and Step 2 actions into the Big Data menu.
- Build/validate Livy through the participant-specific path without weakening
  the private-pilot checks.
- Provide authenticated/restricted participant REST access and examples.
- Implement stop-client/start-Livy and resource-validated keep-client mode.
- Verify actual participant jobs on both selected Tier-2 VMs.
- Reset and credential lifecycle are a separate sprint, as requested.
