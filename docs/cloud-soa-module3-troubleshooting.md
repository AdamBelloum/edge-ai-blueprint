# Module 3 — Storage and Service-Access Troubleshooting

## 1. Scope

Module 3 contains two practical parts:

| Part | Runtime | Persistence | NFS requirement |
|---|---|---|---|
| Part 3.1 — Containerization | Docker Compose | Docker volumes on the Docker host | No NFS required |
| Part 3.2 — Orchestration | Kubernetes | Supplied manifests request NFS-backed shared storage | Required by these manifests, not by Kubernetes itself |

This guide covers the NFS prerequisite for orchestration, two NFS-free alternatives, and service-access timeouts on ports **5000/5001**.

A successful Compose rehearsal does not establish Kubernetes readiness. The orchestration design remains a decision for discussion with the TAs.

## 2. Service-access timeouts on ports 5000 and 5001

### Symptom

Requests from outside the Docker host to the shortener on port **5000** or authentication service on port **5001** time out, despite the services working from the rehearsal host.

A timeout alone does not identify the cause. Possible causes include network routing, firewall restrictions, an incorrect address, or host-port binding. Do not report a specific firewall cause without evidence.

### Separate application readiness from network reachability

On the approved Docker host:

1. Inspect the services using the same Compose file and project name used for the rehearsal.
2. Check the actual published host ports; container ports and host ports need not match.
3. Test a known API endpoint locally on the host.
4. Inspect service logs if the local request fails.

For example, after substituting the actual rehearsal project and file:

```bash
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" ps
```

Then test the published host port with a short timeout. A request to `/` is a connectivity check only; a 404 response can still demonstrate that an HTTP server answered.

```bash
curl -i --connect-timeout 5 --max-time 10 http://127.0.0.1:5000/
curl -i --connect-timeout 5 --max-time 10 http://127.0.0.1:5001/
```

These commands assume host ports 5000/5001. Use the ports shown by Compose if different. Do not treat a connectivity response as a functional API-test pass.

### Workaround — SSH local port forwarding

If host-local access works but direct access from the client times out, forward two local ports through SSH to the approved Docker host. This avoids changing firewall rules or administrator-managed platform services.

Example for the recorded rehearsal host, **provided Compose publishes its services on host ports 5000/5001**:

```bash
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:15000:127.0.0.1:5000 \
  -L 127.0.0.1:15001:127.0.0.1:5001 \
  adam@ab-02.lab.uvalight.net
```

Run this in a separate terminal on the machine from which you will make the HTTP requests. Keep it running while testing.

- Shortener endpoint on that client: `http://127.0.0.1:15000`.
- Authentication endpoint on that client: `http://127.0.0.1:15001`.
- Remote targets: ports 5000/5001 on the Docker host.

Local ports 15000/15001 are illustrative choices to avoid common local conflicts; they are not a claim about the exact ports used in the earlier rehearsal. If occupied, choose other free local ports. Update API client base URLs accordingly.

From a second terminal on the same client:

```bash
curl -i --connect-timeout 5 --max-time 10 http://127.0.0.1:15000/
curl -i --connect-timeout 5 --max-time 10 http://127.0.0.1:15001/
```

Follow these connectivity checks with the known functional API requests. Keep credentials and tokens out of committed logs and reports.

**Where the tunnel starts matters:** if you run SSH on `fs2`, the forwarded ports exist on `fs2`, not automatically on your laptop. For a laptop browser or API client, start the tunnel on the laptop using an approved SSH route. Additional forwarding may be required if the Docker host is reachable only through a jump host.

Stop this foreground tunnel with `Ctrl+C`; this does not stop the Compose services.

### Tunnel troubleshooting

| Symptom | Check |
|---|---|
| SSH cannot connect | Verify the SSH host, approved route, and authentication. HTTP port forwarding cannot work without SSH connectivity. |
| Local bind/address-in-use error | Choose unused local ports and update client URLs. |
| SSH reports remote connection refused | Confirm the remote published port and that the service is listening. Forwarding setup can succeed before a remote connection is attempted. |
| Request still times out | Inspect SSH diagnostics and repeat the host-local request. A tunnel does not fix an unavailable remote service. |
| Browser/client fails while shell requests work | Confirm the client runs on the tunnel-starting machine and uses the forwarded URLs. Check whether the API client is incorrectly using a proxy. |

### Evidence and limitation

Record the client host, Docker host, published ports, forwarded ports, access method, and actual request results. Label successful results **SSH-tunnel access**.

**Tunnel success does not prove direct external reachability of ports 5000/5001.** Direct access remains a separate acceptance item. The recorded Compose tunnel result must not be reported as Kubernetes service-access evidence.

### Kubernetes port distinction

The supplied Kubernetes Services use:

- Shortener: Service/container port 5000; NodePort **30080**.
- Authentication: Service/container port 5001; NodePort **30081**.

Direct Kubernetes NodePort access therefore targets a reachable node address on 30080/30081, not automatically 5000/5001. These fixed NodePorts must be checked for conflicts before deployment.

Once Kubernetes resources are deployed and healthy, an approved SSH tunnel or `kubectl port-forward` can provide a scoped access workaround. Such access still does not prove direct NodePort reachability. Kubernetes runtime access has not yet been validated in this rehearsal.

## 3. NFS problem: the supplied shared-storage configuration is not ready

The beginner orchestration PersistentVolume contains:

```yaml
nfs:
  path: /srv/nfs/websvc
  server: YOUR_NFS_SERVER_IP
```

The PersistentVolumeClaim requests `ReadWriteMany` (RWX), explicitly references `websvc-shared-pv`, and uses an empty `storageClassName`. It does not automatically use the default local-path provisioner.

**Declaring a PersistentVolume does not install an NFS server, create an export, or verify mount connectivity.** The export must exist and be accessible to eligible nodes.

### Recorded prerequisite evidence

The supplied cluster inspection showed:

- Three Ready k3s nodes: `ab-01`, `ab-02`, and `ab-03`.
- One storage class: `local-path`.
- Three existing bound volumes, all using `ReadWriteOnce` (RWO).
- No provisioned RWX PV in that inspection.
- Existing JupyterHub, identity, and other workshop resources to preserve.

Earlier validation notes reported no verified dedicated NFS endpoint. The latest Kubernetes listing does not prove whether an external NFS server exists, but it does not resolve the prerequisite.

**The original NFS-based Kubernetes runtime exercise remains deferred, not passed.**

## 4. Why orchestration needs a storage decision

The authentication service stores users in `users.json`; the shortener stores URL mappings in `urls.json`. Replicas expected to offer a common data view must access the intended shared data.

Independent pod-local files can produce inconsistent results across replicas. Node-local storage remains tied to one node rather than becoming shared across workers.

NFS provides cross-node file sharing. It does **not** protect JSON updates against concurrent writers, lost updates, or corruption.

- **RWO — ReadWriteOnce:** writable mounting from one node; multiple pods on that same node may use the volume.
- **RWX — ReadWriteMany:** writable mounting from multiple nodes, if supported by the backend.

Neither access mode supplies transactions or application-level locking.

## 5. Storage and deployment troubleshooting

Use the explicitly approved context and namespace for read-only inspection first. Do not apply template manifests unchanged to the shared cluster.

| Symptom | Likely cause and check |
|---|---|
| PVC stays `Pending` | Inspect PV/PVC events for missing named PV, capacity/access-mode mismatch, or storage selection mismatch. |
| Pod reports `FailedMount` | Verify NFS endpoint, export permissions, network access, and node-side NFS client support with the administrator. |
| Permission errors under `/app/data` | Check runtime UID/GID and directory permissions; do not default to broad writable permissions. |
| Missing Secret or ConfigMap | Verify `auth-keys` and `shortener-public-key` exist in the exercise namespace and contain the expected filenames, without displaying private keys. |
| `ImagePullBackOff` | Replace image placeholders; verify tags, credentials where required, and registry connectivity. |
| Replicas show different stored results | Verify mount paths and placement; separate storage inconsistency from concurrent application writes. |
| Service cannot be reached | Check ready backends, Service configuration, NodePorts, and the client route separately from storage. |

Use namespace-scoped `kubectl get pods,pvc,services` and `kubectl describe` for diagnosis. PersistentVolumes are cluster-scoped. Do not dump Secret contents into evidence.

## 6. Potential solution 1 — Single-worker Kubernetes with local-path storage

### Approach

Keep Kubernetes Deployments, Services, and replicas, but place **both services and all their replicas on one selected worker**. Replace the NFS PV/PVC pair with a dedicated RWO PVC provisioned by `local-path`.

This remains an orchestration exercise, not a replacement with Docker Compose.

### Required changes

1. Prepare separate rehearsal manifests; preserve the original NFS templates.
2. Use an approved isolated namespace and lab-owned resource names.
3. Define a dedicated PVC using `storageClassName: local-path` and `ReadWriteOnce`.
4. Remove the old static `volumeName: websvc-shared-pv` binding.
5. Constrain both Deployments to the selected worker using its actual hostname label.
6. Mount the same rehearsal PVC at `/app/data` in both services.
7. Create the authentication Secret and public-key ConfigMap in that namespace; keep private keys outside Git.
8. Verify images and available NodePorts or another approved access method.
9. Start with one replica per service, then scale at least one service to three for controlled observations.

Confirm actual PVC binding and pod placement. Run write tests sequentially.

### Validates

- Kubernetes deployments, rollouts, replicas, and Service routing.
- Sequential shared-data observations on one node.
- Persistence across pod replacement while the node and PVC remain available.
- Access through the method actually tested.

### Does not validate

- Cross-worker shared persistence or storage-node failure resilience.
- Safe concurrent JSON writes.
- Completion of the original NFS/RWX exercise unchanged.

**Suitable for a narrowly scoped NFS-free rehearsal**, if the TAs accept the single-worker limitation.

## 7. Potential solution 2 — Shared network-accessible database

### Approach

Replace JSON persistence with database operations, for example using PostgreSQL. Application replicas can run on different workers and access common data over the network without sharing JSON files.

### Required changes

1. Define schemas and uniqueness constraints for users and URL mappings.
2. Replace file operations with database reads and transactional writes.
3. Handle concurrent updates and conflicts explicitly.
4. Provide database connectivity and protected credentials.
5. Remove the application shared-data PVC mounts once unused; retain authentication key mounts.
6. Provide safe schema initialization/migrations for multiple replicas.
7. Update dependencies, images, tests, and beginner, intermediate and advanced instructions.
8. Test cross-worker placement, shared visibility, concurrent operations, and persistence separately.

**Do not reuse or modify Keycloak's database.** Use a separately approved lab database or independent endpoint.

A database still needs persistence. One database instance backed by local-path storage can avoid NFS while serving application pods across workers, but it remains dependent on its storage node. This is not database high availability.

### Benefits and limitations

- Enables cross-worker application replicas.
- Can provide correct concurrent persistence with appropriate transactions and constraints.
- Separates application replicas from stateful persistence.
- Requires application and curriculum changes, credential management, and additional lifecycle/testing work.
- Does not automatically establish production readiness.

**Suitable as a longer-term module improvement** if cross-worker replicas and transactional persistence are learning objectives.

## 8. Decision summary for the TAs

| Criterion | Single-worker local-path | Shared database |
|---|---|---|
| NFS required | No | No, if the chosen database deployment avoids it |
| Application persistence rewrite | No | Yes |
| Application replicas across workers | No, by design | Yes |
| Safe concurrent persistence | Not with current JSON files | Possible with correct transactions and constraints |
| Scope | Manifest adaptation and scoped testing | Application, deployment, and curriculum changes |

The third choice is to retain the original exercise and provide an approved NFS export. That preserves its shared-file approach but does not remove JSON concurrency limitations.

No storage redesign or platform changes are needed before the TA discussion. Choose the learning outcomes first, then validate the selected design.

## 9. Safety and closeout evidence

- Confirm the context, namespace, eligible nodes, and resource ownership before deployment.
- Preserve JupyterHub, Keycloak, existing storage, and other workshop services.
- Treat PVs and NodePorts as cluster-wide concerns.
- Keep secrets, private keys, generated data, and rehearsal credentials outside Git and bundles.
- Record image identifiers, placement, storage status, functional/persistence results, and actual service-access method.
- Keep Compose results separate from Kubernetes results.
- Label tunnel-based access explicitly; retain direct-access limitations.
- Clean up only lab-owned resources. Review reclaim policies before deleting PVCs: local-path volumes commonly use `Delete`.
- Keep persistence tests separate from destructive cleanup.

**Closeout:** the Compose rehearsal and Kubernetes prerequisite investigation can be recorded as completed testing activities. Kubernetes runtime validation remains deferred pending the TA decision and the selected runtime prerequisites. An alternative rehearsal must not be presented as a pass of the original NFS-based exercise.
