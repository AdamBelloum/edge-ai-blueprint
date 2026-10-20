# Operations and validation

This guide is for operators, testers, and maintainers validating the DIGITAfrica Edge-AI Blueprint after deployment or diagnosing a deployment issue.

It separates three levels of evidence:

1. **Infrastructure health** — k3s, Helm, ingress, and core workloads are available.
2. **Workspace readiness** — Silo workspaces have completed dependency installation and source checkout.
3. **Federated-learning execution** — a Flower server and intended clients completed a documented experiment.

A successful result at one level does not automatically prove success at the next level.

For deployment instructions, see [Infrastructure deployment](infrastructure-deployment.md). For the Flower application workflow, see [Federated-learning application](federated-learning-application.md).

---

## Operational conventions

The commands in this guide run from the Ansible control machine and use the Tier-1 server as the Kubernetes administration host.

- The default namespace is `digitafrica`.
- The k3s administrative kubeconfig on the server is `/etc/rancher/k3s/k3s.yaml`.
- `k3s kubectl` uses the k3s kubeconfig.
- Direct `helm` commands require `KUBECONFIG=/etc/rancher/k3s/k3s.yaml`.
- Silo Deployment names are `fl-client-silo-a` and `fl-client-silo-b`.

Set the inventory path to match the environment being tested. Examples below use:

```text
inventories/prod/hosts.ini
```

---

## 1. Infrastructure health validation

Run this after a Tier-1 deployment, before application execution, or when a platform issue is suspected.

```bash
ANSIBLE_STDOUT_CALLBACK=default ansible \
  -i inventories/prod/hosts.ini \
  tier1_server \
  -b \
  -m ansible.builtin.shell \
  -a '
    set -e
    export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

    echo "===== k3s nodes ====="
    k3s kubectl get nodes -o wide

    echo
    echo "===== JupyterHub Helm release ====="
    helm -n digitafrica status jhub

    echo
    echo "===== DIGITAfrica workloads ====="
    k3s kubectl -n digitafrica get deploy,sts,ds,po,svc,ingress -o wide

    echo
    echo "===== Recent namespace events ====="
    k3s kubectl -n digitafrica get events --sort-by=.lastTimestamp | tail -n 40
  '
```

### Expected result

- all intended k3s nodes report `Ready`;
- `helm -n digitafrica status jhub` reports a deployed release;
- required JupyterHub workloads are available;
- Silo pods are `Running` with no unexpected restart loop; and
- recent events do not show unresolved image-pull, scheduling, mount, or crash-loop errors.

### Public JupyterHub reachability

For an ingress deployment, test the public endpoint from an appropriate network location:

```bash
curl -k -I https://<public-host>/jupyter/
```

Use `-k` only where `tls_mode: selfsigned` is intentionally configured. For a trusted certificate, omit `-k` and investigate certificate failures.

A successful HTTP response confirms ingress reachability. It does not prove that a user can authenticate or spawn a notebook server.

---

## 2. JupyterHub functional validation

JupyterHub validation has two steps: the Hub route must be reachable, and a real user server must be able to spawn.

### Manual user-server and notebook-seed test

1. Open the configured JupyterHub URL, normally:

   ```text
   https://<public-host>/jupyter/
   ```

2. Authenticate using the configured authentication mode.
3. Start a user server.
4. Open JupyterLab.
5. Verify that the expected seeded `digitafrica` content is present in the user home directory.
6. Create a small test notebook or text file and confirm that it remains available after stopping and restarting the user server.

### Interpretation

| Result | Meaning |
|---|---|
| Route unavailable | Investigate Traefik, ingress, TLS, firewall rules, public URL configuration, and JupyterHub workload state |
| Login fails | Investigate OIDC configuration or the selected JupyterHub authenticator |
| Login succeeds but spawn fails | Inspect Hub and user-pod events/logs, PVC provisioning, image pull status, and resource limits |
| Spawn succeeds but seeds are absent | Inspect the notebook seed ConfigMap, rendered Helm values, and the user pod’s mounted volumes/init-container logs |
| File persists after restart | User PVC behaviour is working for the tested user |

### Inspect JupyterHub logs and user pods

```bash
ANSIBLE_STDOUT_CALLBACK=default ansible \
  -i inventories/prod/hosts.ini \
  tier1_server \
  -b \
  -m ansible.builtin.shell \
  -a '
    set -e
    export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

    echo "===== JupyterHub pods ====="
    k3s kubectl -n digitafrica get pods -o wide

    echo
    echo "===== Hub logs ====="
    k3s kubectl -n digitafrica logs deployment/hub --tail=120 || true

    echo
    echo "===== PVCs ====="
    k3s kubectl -n digitafrica get pvc -o wide
  '
```

The Hub deployment name is expected to be `hub` for the JupyterHub release. If the chart configuration changes this naming, list pods first and use the actual deployment or pod name.

---

## 3. Silo workspace readiness validation

The Silo Deployments use a startup shell command to install packages and obtain source code. A Kubernetes rollout can report success before that command has completed because the Deployment has no bootstrap-aware readiness probe.

Therefore, validate both:

1. Kubernetes rollout; and
2. completion of the workspace bootstrap and Git checkout.

### Strict Silo bootstrap check

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
      echo "===== ${deployment}: Kubernetes rollout ====="
      k3s kubectl -n digitafrica rollout status "deployment/${deployment}" --timeout=5m

      echo "===== ${deployment}: waiting for bootstrap completion ====="
      completed=false
      for attempt in $(seq 1 30); do
        if k3s kubectl -n digitafrica logs "deployment/${deployment}" 2>&1 \
          | grep -Fq "workspace source is ready"; then
          completed=true
          break
        fi
        sleep 10
      done

      if [ "${completed}" != true ]; then
        echo "ERROR: ${deployment} did not complete bootstrap within five minutes."
        k3s kubectl -n digitafrica logs "deployment/${deployment}" --tail=80 || true
        exit 1
      fi

      pod=$(k3s kubectl -n digitafrica get pods \
        -l "app=${deployment}" \
        -o jsonpath="{.items[0].metadata.name}")

      echo "===== ${deployment}: workspace verification ====="
      k3s kubectl -n digitafrica exec "${pod}" -- sh -ec "
        command -v git
        test -d /home/jovyan/digitafrica/.git
        git -C /home/jovyan/digitafrica rev-parse HEAD
        echo Workspace source verified.
      "
    done
  '
```

### Acceptance evidence

The check passes only when both Silo Deployments:

- complete Kubernetes rollout;
- emit `workspace source is ready` in their current container logs;
- have an executable `git` command;
- contain `/home/jovyan/digitafrica/.git`; and
- return a Git commit SHA.

During the validated deployment, both Silos reported commit `8879982`. This is an observation for that deployment only; always collect the actual commit SHA for a new deployment or experiment.

---

## 4. Federated-learning execution validation

Infrastructure and workspace tests do not show that a Flower experiment has run.

For an experiment-level acceptance test, record evidence of all of the following:

1. the exact server command and application source revision;
2. the exact client command and source revision for every participating Silo;
3. server startup without an unhandled error;
4. registration of every intended client;
5. completion of the planned number of rounds, or documented deviations;
6. expected metrics and model/checkpoint outputs; and
7. retention location for logs and output artefacts.

The experiment owner should define the application-specific pass conditions. Examples include a minimum number of connected clients, an expected number of completed rounds, a finite loss value, or production of an expected checkpoint. Do not set generic numerical thresholds without understanding the dataset and model.

See [Federated-learning application](federated-learning-application.md) for the experiment lifecycle and reproducibility record.

---

## Troubleshooting

### Ansible cannot connect to a node

Check:

- inventory host address, user, and SSH settings;
- VPN, bastion, firewall, and routing requirements;
- availability of privilege escalation; and
- the node’s network reachability from the control machine.

Use a narrow connectivity test:

```bash
ansible -i inventories/prod/hosts.ini all -m ping
```

### k3s agent is missing or `NotReady`

Check the control-plane node list and then inspect the affected node’s k3s-agent service through the relevant inventory host. Confirm that the agent is configured to join the intended server and that network rules permit required k3s traffic.

Do not use `--limit tier1_server` to repair or add agents; run the full Tier-1 playbook when agent reconciliation is required.

### Helm reports a schema validation failure

A values key is in an unsupported location or has an unsupported type for the chart version in use.

1. Read the exact JSON-schema error.
2. Inspect the chart version and its values schema.
3. Correct the source template, not only the generated file on the server.
4. run Ansible syntax and whitespace checks;
5. rerun the targeted Tier-1 reconciliation.

For JupyterHub, settings that are dynamically consumed when a user server is spawned may not appear in the static output of `helm get manifest`. Chart schema validation is the authoritative check for accepted values placement.

### JupyterHub route works but a user server does not spawn

Typical causes include:

- image pull failure;
- insufficient cluster capacity;
- failing init container;
- StorageClass or PVC provisioning issue;
- incorrectly configured mounted volume; or
- an authentication or authorization issue.

Inspect the user pod, events, PVCs, and Hub logs. Do not assume that the Hub route alone proves user-server functionality.

### Silo pod is `Running` but source is absent

A `Running` pod may still be executing package installation or Git checkout. First use the strict workspace bootstrap check.

If the bootstrap completion message does not appear, inspect the current logs:

```bash
ANSIBLE_STDOUT_CALLBACK=default ansible \
  -i inventories/prod/hosts.ini \
  tier1_server \
  -b \
  -m ansible.builtin.shell \
  -a '
    export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
    k3s kubectl -n digitafrica logs deployment/fl-client-silo-a --tail=120
    k3s kubectl -n digitafrica logs deployment/fl-client-silo-b --tail=120
  '
```

Common root causes are a missing package, DNS or outbound network failure, failed Git authentication for a private repository, an incorrect repository URL, or a source checkout conflict.

### Silo bootstrap reports `git: not found`

The workspace image is intentionally minimal and requires Git to be installed before cloning source. Ensure the manifest bootstrap performs package installation before invoking `git clone`, then reapply the manifest through the Tier-1 playbook.

### A Flower client cannot reach the server

This is an experiment/application issue rather than evidence that k3s deployment failed. Check:

- the server address and listening interface;
- server process state and logs;
- client command-line configuration;
- network policy, firewall, or routing constraints;
- TLS and authentication settings, where used; and
- compatibility of the server and client Flower versions.

---

## Reconciliation after a source change

After changing an infrastructure template or Silo manifest, run source checks before changing the live cluster:

```bash
ansible-playbook \
  -i inventories/prod/hosts.ini \
  playbooks/tier1.yml \
  --syntax-check

git diff --check
```

Then reconcile the control-plane deployment when only server-side application resources or Helm values changed:

```bash
ansible-playbook \
  -i inventories/prod/hosts.ini \
  playbooks/tier1.yml \
  --limit tier1_server \
  -e digitafrica_uninstall=false
```

Finally, repeat the relevant infrastructure, JupyterHub, and Silo validation sections in this guide.

---

## Acceptance summary

| Level | Pass condition | Evidence |
|---|---|---|
| Infrastructure | Nodes, Helm release, and required workloads are healthy | `kubectl`, Helm status, events, ingress check |
| JupyterHub | A real user can authenticate, spawn, access seeded content, and retain a test file | Manual browser test plus pod/PVC evidence |
| Silo workspaces | Both Silos complete bootstrap and expose a known source revision | Rollout, logs, Git and source-directory checks |
| Federated-learning experiment | Intended server and clients complete the documented run | Server/client logs, round evidence, metrics, artefacts, configuration record |

## Related documentation

- [Project overview](../README.md)
- [Infrastructure deployment](infrastructure-deployment.md)
- [Federated-learning application](federated-learning-application.md)
- [Architecture](architecture.md)
