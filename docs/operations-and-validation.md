# Federated-learning application

This guide is for researchers and application developers using the DIGITAfrica Edge-AI Blueprint to prepare and run federated-learning experiments.

It describes the application boundary: a Flower server, independently operated Silo workspaces, experiment inputs, execution evidence, and reproducibility. It does not describe how to install k3s, JupyterHub, TLS, or OIDC; see [Infrastructure deployment](infrastructure-deployment.md) for platform administration.

## Scope and current automation boundary

The Tier-1 Ansible playbook prepares an execution environment for a federated-learning application:

- it prepares the server-side application source on the Tier-1 control-plane node;
- it deploys independent Silo A and Silo B Kubernetes workspaces on worker nodes; and
- each Silo bootstrap installs the required Python packages, installs Git, and checks out the configured tutorial/application source into `/home/jovyan/digitafrica`.

The deployment does **not** automatically:

- launch a Flower server;
- launch Flower clients;
- distribute private datasets;
- execute aggregation rounds;
- store experiment results in an experiment registry; or
- stop workloads after an experiment completes.

These are intentional application-level responsibilities. They must be performed under an experiment-specific workflow and recorded with the resulting evidence.

---

## Conceptual model

Federated learning trains a shared model without centrally pooling the underlying Silo datasets.

1. The Flower server defines the experiment and aggregation strategy.
2. Each Silo trains locally against data that remains under its own control.
3. Each Silo sends model updates and permitted metrics to the server.
4. The server aggregates the updates and coordinates subsequent rounds.
5. The experiment produces an agreed set of model artefacts, metrics, logs, and provenance records.

The technical deployment does not by itself establish legal, ethical, privacy, or governance permission to use any dataset. Those requirements remain the responsibility of the experiment owner and participating organisations.

---

## Application components

| Component | Current role | Managed by |
|---|---|---|
| Flower server source | Server-side application source prepared on the Tier-1 control-plane node | Tier-1 playbook prepares source; researcher starts the process |
| Silo A workspace | Kubernetes workspace for one independent client-side execution context | Tier-1 playbook deploys it; researcher runs the client workflow |
| Silo B workspace | Kubernetes workspace for a second independent client-side execution context | Tier-1 playbook deploys it; researcher runs the client workflow |
| Tutorial/application repository | Source material checked out in each Silo workspace | Silo bootstrap obtains it at container startup |
| JupyterHub | User-facing notebook environment on the same platform | Infrastructure administrator |

The Silo Deployments are separate Kubernetes workloads. They are not automatically the same thing as a user’s JupyterHub notebook server, and the current deployment does not automatically expose an interactive terminal for them through JupyterHub.

---

## Before running an experiment

### 1. Confirm platform readiness

Use [Operations and validation](operations-and-validation.md) to confirm:

- the k3s cluster is healthy;
- Silo A and Silo B Deployments are rolled out;
- each Silo completed its startup bootstrap; and
- the expected source revision is present in each Silo.

A pod being `Running` is not, on its own, sufficient evidence: a container can be Kubernetes-ready while its startup script is still installing dependencies. The workspace bootstrap check verifies the source directory and Git revision explicitly.

### 2. Identify the application source revision

Record the exact source revision used by every role before starting an experiment.

For the Silo workspaces, the application source is located at:

```text
/home/jovyan/digitafrica
```

The following command reports the checked-out revision for both deployed Silos:

```bash
ANSIBLE_STDOUT_CALLBACK=default ansible \
  -i inventories/prod/hosts.ini \
  tier1_server \
  -b \
  -m ansible.builtin.shell \
  -a '
    set -e
    export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

    for deployment in fl-client-silo-a fl-client-silo-b; do
      pod=$(k3s kubectl -n digitafrica get pods \
        -l "app=${deployment}" \
        -o jsonpath="{.items[0].metadata.name}")

      printf "%s: " "${deployment}"
      k3s kubectl -n digitafrica exec "${pod}" -- \
        git -C /home/jovyan/digitafrica rev-parse HEAD
    done
  '
```

The bootstrap currently follows the configured repository branch. Therefore, record the commit SHA for every experiment. For stronger reproducibility, change the bootstrap to check out a pinned release tag or commit SHA before using the environment for comparative or published results.

### 3. Establish the experiment contract

Before execution, make the following decisions explicit in an experiment configuration or record:

- server address and transport/security settings;
- Flower and Python dependency versions;
- client identifiers and participating Silos;
- dataset identity, version, provenance, and permitted use;
- local preprocessing and train/validation/test splits;
- model architecture and initial parameters;
- aggregation strategy and its parameters;
- number of rounds, local epochs, batch size, and optimizer settings;
- metrics to report and how they are interpreted;
- output locations for checkpoints, metrics, and logs; and
- failure, retry, and participant-dropout behaviour.

Do not assume that two Silo workspaces contain equivalent data or use the same preprocessing unless the experiment configuration explicitly establishes this.

---

## Running the application

### Server lifecycle

The Tier-1 deployment prepares the server-side source, including a convenient `server.py` link in the control-plane user’s home directory. The exact command-line arguments, address, port, strategy, and round count are properties of the application source and experiment configuration, not infrastructure defaults.

Before running an experiment, inspect the currently deployed server entry point and its supported arguments on the control-plane node:

```bash
ANSIBLE_STDOUT_CALLBACK=default ansible \
  -i inventories/prod/hosts.ini \
  tier1_server \
  -b \
  -m ansible.builtin.shell \
  -a '
    set -e
    echo "===== Server entry point ====="
    ls -l ~/server.py
    python3 ~/server.py --help
  '
```

If the server entry point does not provide `--help`, inspect the source and document the exact invocation in the experiment record. Do not publish generic server commands in this guide until they are verified against the application implementation.

### Silo client lifecycle

A Silo client must be started inside its own workspace using the client entry point and experiment configuration provided by the application source.

To open a non-interactive inspection shell command in Silo A or Silo B, use the corresponding Deployment name:

```bash
ANSIBLE_STDOUT_CALLBACK=default ansible \
  -i inventories/prod/hosts.ini \
  tier1_server \
  -b \
  -m ansible.builtin.shell \
  -a '
    set -e
    export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

    deployment=fl-client-silo-a
    pod=$(k3s kubectl -n digitafrica get pods \
      -l "app=${deployment}" \
      -o jsonpath="{.items[0].metadata.name}")

    k3s kubectl -n digitafrica exec -it "${pod}" -- \
      sh -lc "cd /home/jovyan/digitafrica && pwd && find . -maxdepth 2 -type f | sort | head -n 80"
  '
```

Replace `fl-client-silo-a` with `fl-client-silo-b` for Silo B. The command is for source inspection; start client processes only with an experiment-specific invocation that has been reviewed against the current code.

### Recommended execution sequence

1. Record platform state and source revisions.
2. Prepare or mount each Silo’s approved local dataset according to its data-governance requirements.
3. Start the Flower server with the documented experiment configuration.
4. Start one client process in each participating Silo workspace.
5. Confirm that each intended client registers with the server.
6. Run the planned number of rounds.
7. Capture server logs, client logs, final metrics, and model/checkpoint artefacts.
8. Stop application processes deliberately and retain the experiment record.

If a client fails, do not silently substitute another Silo or dataset. Record the participant change and assess whether the experiment remains comparable to the original plan.

---

## Data handling and privacy

Federated learning reduces the need to centralise raw training data, but it does not remove all privacy or security risks.

At minimum:

- keep each Silo dataset in its approved local storage location;
- do not place raw Silo data in the shared application repository;
- do not include credentials, access tokens, private keys, or personal data in notebooks, logs, or Git commits;
- assess whether model updates or reported metrics could reveal sensitive information;
- use authenticated and protected network communication for non-demonstration deployments; and
- apply the data-management, ethical-review, and institutional requirements applicable to the participating organisations.

For sensitive or regulated data, involve the relevant data steward, security contact, and ethics or legal process before running an experiment.

---

## Reproducibility record

For every experiment, retain a compact but complete record containing:

| Item | Evidence to retain |
|---|---|
| Experiment identifier | Unique name or identifier |
| Date and operators | Start/end timestamps and responsible persons or roles |
| Platform version | Blueprint revision and deployment configuration used |
| Server source | Repository URL, branch/tag, and commit SHA |
| Silo source | Repository URL, branch/tag, and commit SHA for each Silo |
| Runtime dependencies | Python, Flower, and relevant package versions |
| Data provenance | Dataset identifier, version, ownership, approvals, and local split description |
| Experiment configuration | Model, strategy, hyperparameters, number of rounds, and client set |
| Execution evidence | Server and client logs, registration evidence, and failure/retry events |
| Outputs | Metrics, model/checkpoint locations, and integrity information |
| Interpretation | Main result, limitations, and comparability with other runs |

The previously validated Silo deployment showed both Silo workspaces at commit `8879982`. Treat that only as an observed deployment result, not as a permanent application version. Re-check and record the actual revision before every new experiment.

---

## Definition of success

### Platform and workspace deployment success

The infrastructure deployment is successful when:

- the Tier-1 cluster is healthy;
- JupyterHub is reachable according to the configured exposure mode;
- Silo A and Silo B Deployments roll out successfully;
- each Silo has the required runtime dependencies; and
- the expected source is present and identifiable by Git revision.

### Federated-learning experiment success

A federated-learning experiment is successful only when:

- the intended Flower server is running with the recorded configuration;
- the intended Silo clients connect successfully;
- the planned training rounds complete or deviations are documented;
- expected metrics and artefacts are captured; and
- the result can be associated with a complete reproducibility record.

Do not conflate a successful Kubernetes rollout with a successful federated-learning experiment.

---

## Current limitations and recommended improvements

- **Source pinning:** bootstrap follows a repository branch. Pin an immutable tag or commit for reproducible experiments.
- **Runtime image:** dependencies are installed when a Silo starts. Use a versioned custom image containing Git and pinned Python dependencies to reduce startup time and package drift.
- **Readiness:** Kubernetes readiness does not yet prove that source checkout and dependency installation are complete. Use an init container or a readiness probe based on a bootstrap-complete marker.
- **Experiment automation:** introduce a reviewed launcher or workflow that starts the server and clients, captures evidence, and stops cleanly after a run.
- **Results management:** define an approved persistent location and retention policy for models, metrics, and logs.

## Related documentation

- [Project overview](../README.md)
- [Infrastructure deployment](infrastructure-deployment.md)
- [Operations and validation](operations-and-validation.md)
- [Architecture](architecture.md)
