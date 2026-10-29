# Troubleshooting Spark Direct Credentials and SSH Authentication

## 1. Purpose and scope

This runbook documents the troubleshooting of participant SSH access from a JupyterHub notebook pod to its assigned Spark client container in the DIGITAfrica Tier-2 workshop.

**Incident date:** 28 October 2026.

**Outcome:** Protected credentials were delivered to `group_01`; a stale Kubernetes NetworkPolicy destination was corrected; authenticated remote access and SparkPi execution then succeeded.

**Scope limitation:** These results validate `group_01` on `tier2-worker-1`. They do not establish readiness for other groups or successful execution of the bank-analysis workflow, which had not yet been tested in the recorded session.

## 2. Authentication and execution path

The participant launcher uses SSH/SFTP transport with an organiser-supplied private key and pinned server host key. It does not provide a replacement Spark submission API.

The tested path was:

```text
JupyterHub participant pod
  → spark_remote.py
  → SSH to worker public IP, TCP 2222
  → Docker port forwarding to Spark client container
  → Spark driver in the client container
  → Spark master and worker on the private Docker network
```

Two distinct credentials are involved:

| File | Purpose |
|---|---|
| `login_key` | Private client key used for SSH authentication |
| `known_hosts` | Pinned SSH server identity used for host-key verification |

The launcher defaults to:

```text
~/.ssh/spark-direct/login_key
~/.ssh/spark-direct/known_hosts
```

The launcher help states that the endpoint defaults to the single organiser-pinned `known_hosts` record, that host-key verification is mandatory, and that there is no auto-trust or password fallback.

**Important distinction:** Finding these files does not prove that SSH authentication succeeds. TCP connectivity, server host-key verification and client authentication must each succeed before a remote command can run.

## 3. Incident-specific resources

These values were observed during this incident. Re-discover them for a new cohort or deployment; pod names, pod IPs and Docker addresses can change.

| Resource | Observed value |
|---|---|
| Repository on control host | `/home/adam/edge-ai-blueprint` |
| Control host | `fs2` |
| Ansible inventory | `inventories/workshop/tier2/hosts.ini` |
| Kubernetes control-plane inventory alias | `tier2-server` |
| Worker inventory group | `tier2_agents` |
| Namespace | `digitafrica` |
| Participant | `group_01` |
| Participant pod | `jupyter-group-01---fb8bc378` |
| Notebook container | `notebook` |
| Launcher | `/home/jovyan/Big-Data/Spark/spark_remote.py` |
| Assigned worker alias | `tier2-worker-1` |
| Assigned Kubernetes node / worker FQDN | `ab-02.lab.uvalight.net` |
| SSH public endpoint | `145.100.135.172:2222` |
| Spark client container | `digitafrica-spark-spark-client-1` |
| Pilot NetworkPolicy | `spark-direct-group-01-pilot` |

The second worker, `tier2-worker-2`, resolved to `ab-03.lab.uvalight.net`.

## 4. Findings and resolution

### 4.1 Credential exports existed and were protected

Both workers had exported `login_key` and `known_hosts` files beneath:

```text
secrets/big-data-spark-direct/<worker-alias>/
```

The metadata check showed regular files, mode `0600`, ownership `1036:1036` and one hard link each. This established file presence and restricted permissions, not key validity or correct server identity.

The matching `tier2-worker-1` exports were delivered to the `group_01` workspace without generating new keys or displaying their contents.

### 4.2 Workspace ownership differed from the initial prediction, but remained safe

After delivery, the pod reported:

```text
directory | mode=2700 | owner=1000:100 | /home/jovyan/.ssh
directory | mode=2700 | owner=1000:100 | /home/jovyan/.ssh/spark-direct
regular file | mode=600 | owner=1000:100 | /home/jovyan/.ssh/spark-direct/login_key
regular file | mode=600 | owner=1000:100 | /home/jovyan/.ssh/spark-direct/known_hosts
```

`2700` includes the directory setgid bit. It does not grant group or other access. The inherited group ID `100` did not require correction: the files were owned by participant UID `1000` and accessible only to that owner.

Do not change ownership solely because the group differs from an assumed `1000:1000`. Verify the actual participant UID and effective access.

### 4.3 The next failure was connectivity, not a demonstrated authentication error

The first remote environment check failed with:

```text
SSH/SFTP failed: [Errno None] Unable to connect to port 2222 on 145.100.135.172
```

This failure occurred before the SSH connection could progress to host-key verification or client authentication. It was not evidence of a wrong private key.

### 4.4 The SSH service worked locally on the worker

Docker showed the client running and publishing:

```text
145.100.135.172:2222->2222/tcp
```

The worker host had a listener on that address. A worker-local TCP probe returned:

```text
SSH-2.0-OpenSSH_8.2p1 Ubuntu-4ubuntu0.13
```

This confirmed that the endpoint served SSH locally. A Docker-published listener alone would not have established that fact.

### 4.5 The pilot NetworkPolicy had a stale post-DNAT destination

The Helm-managed `singleuser` policy allowed public IPv4 destinations but excluded private ranges, including `172.16.0.0/12`.

The additional pilot policy selected `group_01` and allowed TCP `2222` only to:

```text
172.25.0.2/32
```

The client now had these addresses:

```text
spark-access:  172.27.0.2
spark-private: 172.26.0.4
```

Docker's NAT rule confirmed the actual destination:

```text
-A DOCKER -d 145.100.135.172/32 ! -i br-3d8e6e69fbf1 -p tcp -m tcp --dport 2222 -j DNAT --to-destination 172.27.0.2:2222
```

NetworkPolicy allow rules are additive. The pilot policy did not override the general public-address allowance; it supplied a narrow allowance for the private translated destination. In this deployment, correcting that allowance resolved the failure, consistent with policy enforcement on the post-DNAT path. NAT and policy evaluation order should not be assumed identical across all networking implementations.

### 4.6 A narrow correction restored access

The pilot policy destination was changed from `172.25.0.2/32` to `172.27.0.2/32` using a guarded JSON patch. The participant selector and TCP port were left unchanged.

The launcher continued using the same pinned public SSH endpoint and credentials. No Spark restart or credential replacement was needed.

## 5. Diagnostic procedure

Run the following commands on `fs2` from the repository root with the prepared Ansible environment active. These examples use incident-specific names; verify them before reuse. Unless explicitly labelled as a modification, the checks are read-only, even when Ansible reports `changed: true` for a command task.

### Step 1 — Inspect credential metadata only

```bash
stat -c '%F | mode=%a | owner=%u:%g | links=%h | %n' \
  secrets/big-data-spark-direct/tier2-worker-{1,2}/{login_key,known_hosts}
```

Check for regular files, owner-only private-key permissions and ownership by the intended administrator. Do not print the private key or include it in diagnostic output.

### Step 2 — Confirm participant placement

```bash
ansible -v -i inventories/workshop/tier2/hosts.ini tier2-server \
  -b -m ansible.builtin.command \
  -a 'k3s kubectl -n digitafrica get pod jupyter-group-01---fb8bc378 -o wide'
```

Map the returned Kubernetes node hostname to inventory workers:

```bash
ansible -v -i inventories/workshop/tier2/hosts.ini tier2_agents \
  -m ansible.builtin.command \
  -a 'hostname -f'
```

In this session, `setup` with `filter=ansible_fqdn` succeeded but the configured callback suppressed the successful fact output, even at `-vv`. The direct hostname command displayed the values. Lack of displayed facts was not a fact-gathering failure.

Choose credentials using the confirmed assignment, not an assumed ordering of worker aliases. Placement mapping does not replace host-key verification.

### Step 3 — Inspect workspace credential metadata

```bash
ansible -v -i inventories/workshop/tier2/hosts.ini tier2-server \
  -b -m ansible.builtin.command \
  -a 'k3s kubectl -n digitafrica exec jupyter-group-01---fb8bc378 -c notebook -- stat -c "%F | mode=%a | owner=%u:%g | %n" /home/jovyan/.ssh /home/jovyan/.ssh/spark-direct /home/jovyan/.ssh/spark-direct/login_key /home/jovyan/.ssh/spark-direct/known_hosts'
```

If needed, verify the container identity separately:

```bash
ansible -v -i inventories/workshop/tier2/hosts.ini tier2-server \
  -b -m ansible.builtin.command \
  -a 'k3s kubectl -n digitafrica exec jupyter-group-01---fb8bc378 -c notebook -- id'
```

If credentials are absent, use the organiser's protected delivery mechanism. The incident used a root-only temporary staging directory on the control plane and transferred only the two required files into a newly created workspace directory. It refused to overwrite an existing `.ssh` directory and removed the staging directory afterward. That emergency delivery procedure is not an idempotent production provisioning design.

### Step 4 — Test authenticated access without submitting Spark

```bash
ansible -v -i inventories/workshop/tier2/hosts.ini tier2-server \
  -b -m ansible.builtin.command \
  -a 'k3s kubectl -n digitafrica exec jupyter-group-01---fb8bc378 -c notebook -- python /home/jovyan/Big-Data/Spark/spark_remote.py run -- printenv SPARK_HOME SPARK_MASTER_URL SPARK_DRIVER_HOST SPARK_DATA_PATH'
```

The successful incident output was:

```text
Remote command: cd /home/workshop/work && printenv SPARK_HOME SPARK_MASTER_URL SPARK_DRIVER_HOST SPARK_DATA_PATH
/opt/spark
spark://spark-master:7077
spark-client
/opt/spark-data/data/Bank_Personal_Loan_Modelling.csv
Remote exit status: 0
```

This confirms authenticated remote execution and the printed configuration. Printing a dataset path does not establish that the dataset exists or is readable by all required Spark processes.

If the launcher reports inability to connect, investigate transport first. Do not regenerate credentials in response to a TCP failure.

### Step 5 — Check containers and the published listener

```bash
ansible -v -i inventories/workshop/tier2/hosts.ini tier2-worker-1 \
  -b -m ansible.builtin.shell \
  -a 'set -eu; printf "\n--- Spark project containers ---\n"; docker ps -a --filter label=com.docker.compose.project=digitafrica-spark; printf "\n--- TCP port 2222 listener ---\n"; ss -ltn "sport = :2222"'
```

Verify that the client is running and that the published address and port match the pinned endpoint.

### Step 6 — Read the worker-local SSH banner

```bash
ansible -v -i inventories/workshop/tier2/hosts.ini tier2-worker-1 \
  -b -m ansible.builtin.command \
  -a 'python3 -c "import socket; s=socket.create_connection((\"145.100.135.172\", 2222), timeout=5); s.settimeout(5); print(\"SSH banner:\", repr(s.recv(256))); s.close()"'
```

A banner proves that the worker-local TCP endpoint serves SSH. It does not authenticate the server or the client and does not alter trust. If this succeeds but pod access fails, investigate the pod-to-endpoint network path.

### Step 7 — Inspect NetworkPolicy rules

```bash
ansible -v -i inventories/workshop/tier2/hosts.ini tier2-server \
  -b -m ansible.builtin.command \
  -a 'k3s kubectl -n digitafrica get networkpolicies -o yaml'
```

Check:

- Which selectors match the participant pod.
- The union of allowed egress rules.
- Whether a private translated address is excluded from the general allowance.
- Whether any participant-specific allowance refers to an obsolete container address.

Do not infer the complete firewall state from NetworkPolicy YAML alone.

### Step 8 — Inspect client addresses without exposing its environment

```bash
ansible -v -i inventories/workshop/tier2/hosts.ini tier2-worker-1 \
  -b -m ansible.builtin.shell \
  -a 'docker inspect digitafrica-spark-spark-client-1 | python3 -c "import json,sys; r=json.load(sys.stdin)[0]; print(json.dumps(r[\"NetworkSettings\"][\"Networks\"], indent=2))"'
```

The filtering prints only network details. Avoid pasting complete `docker inspect` output, which may include sensitive environment configuration.

### Step 9 — Confirm the actual DNAT destination

```bash
ansible -v -i inventories/workshop/tier2/hosts.ini tier2-worker-1 \
  -b -m ansible.builtin.shell \
  -a 'iptables -t nat -S DOCKER | grep -E -- "2222|145\.100\.135\.172"'
```

Use the actual `--to-destination` address and port rather than guessing from network names. If this command finds no matching rule or the chain is unavailable, inspect the deployment's actual Docker/firewall backend; do not assume a missing service from this check alone.

## 6. Incident-specific policy repair

**This step modifies live cluster state.** Recheck the policy selector, current destination and actual DNAT rule before applying it to any deployment. The addresses below are not permanent configuration values.

The recorded guarded patch was:

```bash
ansible -v -i inventories/workshop/tier2/hosts.ini tier2-server \
  -b -m ansible.builtin.command \
  -a 'k3s kubectl -n digitafrica patch networkpolicy spark-direct-group-01-pilot --type=json --patch "[{\"op\":\"test\",\"path\":\"/spec/egress/0/to/0/ipBlock/cidr\",\"value\":\"172.25.0.2/32\"},{\"op\":\"replace\",\"path\":\"/spec/egress/0/to/0/ipBlock/cidr\",\"value\":\"172.27.0.2/32\"}]"'
```

The `test` operation prevents replacement if the expected old value has changed. The patch leaves the participant selector and port unchanged and replaces rather than retains the obsolete destination.

It does **not** restrict the participant's total egress to this one endpoint: the existing Helm-managed allowances remain additive.

After patching, repeat Step 4. In the incident, that check returned `Remote exit status: 0`.

If the correction does not restore access, inspect the remaining network path rather than broadening the allowance automatically. Restore the previous rule only if rollback is operationally appropriate; the previous address is known to be stale here.

**Persistence warning:** A live JSON patch does not update the repository manifest or the existing `kubectl.kubernetes.io/last-applied-configuration` annotation. Reapplying an old manifest can restore the stale address. Reconcile the source-controlled preparation logic after validating the repair.

## 7. Validate Spark execution separately

A successful SSH command is not sufficient evidence of distributed Spark execution.

Inspect the prepared launcher's supported interface if it differs from the incident baseline:

```bash
ansible -v -i inventories/workshop/tier2/hosts.ini tier2-server \
  -b -m ansible.builtin.command \
  -a 'k3s kubectl -n digitafrica exec jupyter-group-01---fb8bc378 -c notebook -- python /home/jovyan/Big-Data/Spark/spark_remote.py --help'
```

The recorded launcher supported `put`, `get`, `run`, `test` and `analyse`.

### SparkPi smoke test — submits a job

```bash
ansible -v -i inventories/workshop/tier2/hosts.ini tier2-server \
  -b -m ansible.builtin.command \
  -a 'k3s kubectl -n digitafrica exec jupyter-group-01---fb8bc378 -c notebook -- python /home/jovyan/Big-Data/Spark/spark_remote.py test'
```

The incident evidence included:

| Check | Observed result |
|---|---|
| Runtime | Spark `3.5.3`, Java `11.0.24` |
| Cluster connection | `spark://spark-master:7077` |
| Application ID | `app-20261028143102-0001` |
| Executor placement | `spark-worker-1` |
| Executor resources | One core, 512 MiB memory |
| Task completion | Both SparkPi tasks completed on the worker |
| Result | `Pi is roughly 3.1462357311786557` |
| Exit | Remote status `0`; SparkContext stopped successfully |

The native-Hadoop library warning was non-fatal in this test. Spark wrote normal informational logs to stderr; the presence of stderr alone did not indicate failure.

This was one remote executor in the assigned VM's Spark deployment. It does not demonstrate Spark execution spanning both Tier-2 VMs.

### Bank analysis — subsequent validation, not yet recorded

```bash
ansible -v -i inventories/workshop/tier2/hosts.ini tier2-server \
  -b -m ansible.builtin.command \
  -a 'k3s kubectl -n digitafrica exec jupyter-group-01---fb8bc378 -c notebook -- python /home/jovyan/Big-Data/Spark/spark_remote.py analyse'
```

This invokes the existing bank-analysis workflow. Its outcome was not available in the recorded troubleshooting session.

## 8. Failure classification and safe responses

The rows describing host-key and authentication failures below are general diagnostic guidance, not additional failures observed in this incident.

| Symptom | Likely failing layer | Safe next action |
|---|---|---|
| Key or `known_hosts` file absent/unreadable | Local credential provisioning | Verify metadata, participant UID and protected delivery |
| `Unable to connect to port 2222` | TCP connectivity | Check published endpoint, service banner, policy and forwarding |
| Unknown or mismatched server host key | Server identity verification | Stop and verify the organiser-approved server identity; do not auto-trust |
| Authentication rejected after SSH connection | Client authentication | Verify the assigned key and server-side authorised-key configuration without exposing private material |
| Remote command works but environment is missing | Prepared remote configuration | Inspect only required variables and organiser configuration |
| SSH succeeds but Spark master/executor fails | Spark networking or runtime | Inspect Spark logs, private-network connectivity and resource configuration |
| SparkPi succeeds but analysis fails | Application, data or Python runtime | Inspect the analysis traceback, data access and prepared dependencies |

Do not use password fallback, disable host-key checking, grant broad private-subnet access, or reset a running cluster merely to bypass an unexplained failure.

SSH authentication and Spark's own authentication are separate mechanisms. The SparkPi logs reported Spark authentication and UI ACLs disabled. This incident's successful SSH authentication does not mean Spark RPC or UI access is authenticated. Any broader security assessment must verify private-network isolation and UI exposure separately.

## 9. Required organiser-workflow improvements

The manual repair should be replaced with modular, inventory-driven preparation logic, separate from base infrastructure deployment.

1. **Resolve assignments explicitly.** Map participant groups to actual Kubernetes worker hostnames and inventory aliases. Reject ambiguous or inconsistent mappings.
2. **Deliver only the matching credentials.** Preserve owner-only access, do not overwrite unrelated SSH files, and make repeat preparation safe and idempotent.
3. **Preserve existing identities.** Do not regenerate keys or host pins during routine preparation without an explicit rotation procedure.
4. **Discover current forwarding destinations.** Read the actual published-port target and reconcile narrow group-specific allowances after the client network is prepared. Do not hard-code ephemeral Docker IPs.
5. **Remove obsolete allowances safely.** A previous container address may later belong to another container. Keep the policy scoped to the intended participant and service port.
6. **Reconcile after lifecycle changes.** Container recreation or network changes must trigger destination discovery and policy updates. Participant pod placement changes must be checked against the intended group assignment.
7. **Keep secrets outside Git.** Retain generated private keys beneath ignored local `secrets/` storage or an approved protected secret store. Use Ansible `no_log: true` for secret-bearing tasks and avoid secret-bearing diffs, arguments and evidence exports.
8. **Use tier-aware shared logic.** Parameterise inventory and placement handling; preserve Tier-1 behaviour through regression testing.
9. **Separate readiness gates.** Validate credential metadata, authenticated SSH configuration and SparkPi before claiming application readiness.
10. **Record non-secret evidence.** Capture group assignment, endpoint, policy destination, permissions and test statuses without exporting credentials.

## 10. Closure checklist

- [x] Protected exports present for both worker aliases.
- [x] `group_01` pod placement mapped to `tier2-worker-1`.
- [x] Matching credentials delivered with owner-only access.
- [x] Worker-local SSH endpoint confirmed with a public banner.
- [x] Actual Docker DNAT destination verified.
- [x] Stale participant-specific policy destination corrected.
- [x] Authenticated remote environment check passed.
- [x] SparkPi ran on the remote worker and exited successfully.
- [ ] Bank-analysis workflow validated.
- [ ] Credential delivery integrated into idempotent organiser preparation.
- [ ] Discovery-based policy reconciliation integrated into preparation.
- [ ] Fresh preparation and container-recreation scenarios tested.
- [ ] Other groups and Tier-1 regression behaviour validated.

## Evidence basis

This document is based on the supplied Ansible, Kubernetes, Docker, launcher and Spark outputs from the troubleshooting session. Recommendations for persistent automation are proposed follow-up work, not claims that those features have already been implemented.
