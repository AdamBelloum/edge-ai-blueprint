# DigitAfrica Edge-AI Blueprint

Ansible-based deployment of a two-tier Edge-AI infrastructure: a lightweight single-node tier (Tier-0) and a multi-node Kubernetes cluster (Tier-1) running JupyterHub.

---

## What changed in this iteration

- **Playbook split** — `site.yml` now uses `import_playbook` to call `tier0.yml` and `tier1.yml` independently. 
- **`expose_mode` replaces all k3s booleans** — both tiers now use a single `expose_mode: "ingress"|"nodeport"` string. Ingress places all services behind traefik, while nodeport uses the provided port Numbers for port forwarding
- **TLS for Tier-1** — new `tls_mode` variable with four options: `selfsigned`, `letsencrypt`, `provided`, `none`. Self-signed certificates are generated automatically (may produce a warning when visiting the jupyterhub with self-signed certs). You can select provided and provide the folder on the node where the certificates are added, or use let;s encrypt if the machine has a public IP with ports 80 and 443 open (you need to provide an email for registering the certificate with let's encrypt)
- **Notebook seeding via ConfigMap** — Example starting notebooks are injected into JupyterHub pods through a Kubernetes ConfigMap instead of a PVC volume. This removes the node pin existing in previous iterations. Now pods can be scheduled freely across any cluster node.
- **Configurable storage class** — `tier1.jupyterhub.storage_class` controls which StorageClass backs user PVCs. Default is `local-path`. Tested with the NFS server implementation for DigitAfrica. 
- **OIDC toggle** — `oidc.oidc_enabled: true|false` switches JupyterHub between Keycloak/OIDC and a local dummy authenticator with no redeploy of the cluster. Previous versions had a hard dependency on OIDC for Tier-1.
- **MLflow / Grafana enabled flags** — `tier1.mlflow.enabled` and `tier1.grafana_enabled` control whether those services are deployed. The services are not yet available, this is a placeholder for future developments. 

---

## What this deploys

### Tier-0 — single node, no Kubernetes

Runs directly on bare metal or a VM. Three sub-modes controlled by `tier0.k3s_mode`:

| `tier0.k3s_mode` | What gets deployed |
|---|---|
| `none` | Jupyter notebook as a Docker container + cAdvisor + Node Exporter |
| `single` | k3s single-node cluster + JupyterHub via Helm + optional model cache |
| `agent` | Joins this node to the Tier-1 cluster as a k3s agent |

### Tier-1 — multi-node Kubernetes cluster

Deploys a k3s cluster (one server node + any number of agents) and on top of it:

- **JupyterHub** (via Helm) — multi-user notebook environment with persistent home directories
- **Traefik Ingress** (built-in k3s) — routes all traffic through paths on port 80/443
- **Example notebooks** — pre-loaded into every user's home directory 

---

## Quick start

### 1. Prerequisites

On the control machine:

```bash
pip install ansible
ansible-galaxy collection install -r requirements.yml
```

SSH access to all target nodes is required (`ansible_ssh_pass` or key-based).

### 2. Inventory

Edit `inventories/prod/hosts.ini`:

```ini
### TIER 0 NODES ###
; [tier0]
; digitafrica-edge-node1 ansible_host=10.64.45.176 ansible_ssh_pass="REDACTED" ansible_become_pass="REDACTED"
; digitafrica-edge-node1 ansible_host=10.64.45.176 ansible_ssh_pass="REDACTED" ansible_become_pass="REDACTED"

### TIER 1 NODES ###
[tier1_server]
digitafrica-edge-node1 ansible_host=10.64.45.176 ansible_ssh_pass="REDACTED" ansible_become_pass="REDACTED"

[tier1_agents]
digitafrica-edge-node2 ansible_host=10.64.45.179 ansible_ssh_pass="REDACTED" ansible_become_pass="REDACTED"

[all:vars]
ansible_user=ubuntu
ansible_become=true
#ansible_ssh_common_args='-o ProxyJump=proxy@bastion1.theblueprintfactory.org'

```

Only populate the groups you actually use. If running Tier-0 only, leave `tier1_*` groups empty (or commented out), and vice versa.
The hostnames e.g. digitafrica-edge-node1 need to match the hostnames of the nodes on which the deployment takes place for Tier-1, otherwise the cluster creation will fail.

### 3. Configure variables

All options are included in `inventories/prod/group_vars/all.yml`. See the [Configuration reference](#configuration-reference) below.

At minimum set:
- `tier1.jupyterhub.jupyterhub_public_url` — server's IP or DNS name
- `tier0.k3s_mode` — `none`, `single`, or `agent`

### 4. Deploy

Full deployment (depending on which tier is active on the hosts.ini file):
```bash
ansible-playbook -i inventories/prod/hosts.ini playbooks/site.yml
```

Tier-0 only:
```bash
ansible-playbook -i inventories/prod/hosts.ini playbooks/tier0.yml
```

Tier-1 only:
```bash
ansible-playbook -i inventories/prod/hosts.ini playbooks/tier1.yml
```

### 5. Uninstall

```bash
ansible-playbook -i inventories/prod/hosts.ini playbooks/site.yml -e digitafrica_uninstall=true
```

---

## Configuration reference

### Tier-0

| Variable | Default | Description |
|---|---|---|
| `tier0.k3s_mode` | `none` | `none` = Docker-only \| `single` = k3s cluster \| `agent` = join Tier-1 |
| `tier0.expose_mode` | `ingress` | `ingress` = Traefik (only valid when `k3s_mode=single`) \| `nodeport` = raw ports |
| `tier0.notebook_port` | `8888` | Port the Jupyter container listens on |
| `tier0.jupyter_nodeport` | `30888` | NodePort used when `expose_mode=nodeport` |
| `tier0.modelcache_nodeport` | `30080` | NodePort for model cache when `expose_mode=nodeport` |
| `tier0.enable_modelcache` | `false` | Deploy the static model-cache service |
| `tier0.notebook_user` | `digitafrica` | Local Linux user that owns notebook files |
| `tier0.notebook_dir` | `/opt/digitafrica/notebooks` | Directory mounted into the Jupyter container |
| `tier0.notebook_password` | `digitafrica` | Plain-text password (also set the hash below) |
| `tier0.k3s_version` | `v1.30.4+k3s1` | k3s version to install (only when `k3s_mode=single`) |
| `tier0.k3s_agent_server_host` | — | Tier-1 server hostname to join (only when `k3s_mode=agent`) |
| `tier0.monitoring.node_exporter_port` | `9100` | Node Exporter port |
| `tier0.monitoring.cadvisor_port` | `8080` | cAdvisor port |

### Tier-1

| Variable | Default | Description |
|---|---|---|
| `tier1.expose_mode` | `ingress` | `ingress` = Traefik on port 80/443 \| `nodeport` = no Traefik, plain ports |
| `tier1.tls_mode` | `selfsigned` | `selfsigned` \| `letsencrypt` \| `provided` \| `none` — see [TLS](#tls) |
| `tier1.tls_cert_dir` | — | Local path to `tls.crt` + `tls.key` (only when `tls_mode=provided`) |
| `tier1.tls_acme_email` | — | Email for Let's Encrypt registration (only when `tls_mode=letsencrypt`) |
| `tier1.k3s_version` | `v1.30.4+k3s1` | k3s version |
| `tier1.k3s_server_host` | — | Hostname of the k3s server node |
| `tier1.k3s_cluster_cidr` | `10.42.0.0/16` | Pod CIDR |
| `tier1.k3s_service_cidr` | `10.43.0.0/16` | Service CIDR |
| `tier1.digitafrica_namespace` | `digitafrica` | Kubernetes namespace for all app resources |
| `tier1.jupyterhub.jupyterhub_public_url` | `https://<host>/jupyter` | **Must match node's IP or DNS name.** Used for the final access URL. |
| `tier1.jupyterhub.jupyter_nodeport` | `30888` | NodePort for JupyterHub when `expose_mode=nodeport` |
| `tier1.jupyterhub.storage_class` | `local-path` | StorageClass for user PVCs. Tested with the `nfs-client` and the NFS-Server implementation |
| `tier1.jupyterhub.jupyterhub_admin_users` | `["admin"]` | List of JupyterHub admin usernames |
| `tier1.mlflow.enabled` | `false` | Deploy MLflow experiment tracking |
| `tier1.mlflow.mlflow_port` | `5000` | MLflow listening port |
| `tier1.grafana_enabled` | `false` | Deploy Grafana dashboards |

### OIDC / Keycloak

| Variable | Default | Description |
|---|---|---|
| `oidc.oidc_enabled` | `false` | `true` = Keycloak/OIDC login \| `false` = local dummy authenticator |
| `oidc.oidc_issuer_url` | — | Keycloak realm URL, e.g. `https://auth.example.org/realms/myrealm` |
| `oidc.oidc_client_id` | — | Client ID registered in Keycloak |
| `oidc.oidc_client_secret` | — | Client secret from Keycloak |
| `oidc.oidc_scope` | `[openid, profile, email]` | OAuth scopes to request |
| `oidc.oidc_username_claim` | `preferred_username` | JWT claim used as the JupyterHub username |
| `oidc.oidc_tls_verify` | `false` | Set to `true` if your Keycloak cert is trusted |



---

## TLS

TLS is configured via `tier1.tls_mode` and only applies when `expose_mode: ingress`. 

### `selfsigned` (default)
Generates a certificate on the server. Stored as a Kubernetes TLS secret (`jhub-tls`). Browsers will show a warning — expected for self-signed certs.

```yaml
tier1:
  tls_mode: "selfsigned"
```

### `provided`
You supply `tls.crt` and `tls.key` in a local directory. Ansible copies them to the server and creates the secret.

```yaml
tier1:
  tls_mode: "provided"
  tls_cert_dir: "/path/to/your/certs"   # local path on the control machine
```

### `letsencrypt`
Installs `cert-manager` for Let's Encrypt ACME HTTP-01 challenge. Requires a real DNS name (not a raw IP) in `jupyterhub_public_url` and ports 80/443 publicly reachable.

```yaml
tier1:
  tls_mode: "letsencrypt"
  tls_acme_email: "admin@yourdomain.com"
  jupyterhub:
    jupyterhub_public_url: "https://yourdomain.com/jupyter"
```

### `none`
HTTP only. JupyterHub will show an HTTPS warning.

```yaml
tier1:
  tls_mode: "none"
  jupyterhub:
    jupyterhub_public_url: "http://10.64.45.176/jupyter"
```

---

## Networking

### Ingress mode (default)
Traefik (built into k3s) handles all traffic on ports 80 and 443. No NodePort assignments to manage. A redirect middleware ensures `/jupyter` (without trailing slash) redirects to `/jupyter/`.

| Service | Path |
|---|---|
| JupyterHub | `https://<host>/jupyter/` |
| Model cache (Tier-0) | `http://<host>/models/` |

### NodePort mode
Set `expose_mode: nodeport` in the relevant tier. Traefik is disabled; services are reachable on raw ports.

| Service | Port variable | Default |
|---|---|---|
| JupyterHub (Tier-0/1) | `jupyter_nodeport` | `30888` |
| Model cache (Tier-0) | `modelcache_nodeport` | `30080` |



## OIDC Authentication

JupyterHub delegates login to an external Identity Provider via OpenID Connect (OIDC). The flow:

1. User visits JupyterHub
2. JupyterHub redirects to Keycloak
3. User authenticates on Keycloak
4. Keycloak returns a token; JupyterHub validates it and creates a session

When `oidc.oidc_enabled: false`, JupyterHub falls back to a `dummy` authenticator — any username/password is accepted. Useful for local testing.

After enabling OIDC, register the callback URL in Keycloak under **Valid Redirect URIs**:
```
https://<your-host>/jupyter/hub/oauth_callback
```

---

## Related blueprints

| Blueprint | Purpose |
|---|---|
| [k3s-cluster](https://gitlab.inria.fr/digitafrica/blueprints/services/k3s-cluster.git) | Standalone k3s cluster without app layer |
| [nfs-server](https://gitlab.inria.fr/digitafrica/blueprints/services/nfs-server.git) | NFS server + provisioner for multi-node persistent storage |
| [jupyterhub-on-k3s](https://gitlab.inria.fr/digitafrica/blueprints/services/jupyterhub-on-k3s.git) | JupyterHub-only deployment on an existing cluster |
| [user-portal](https://gitlab.inria.fr/digitafrica/blueprints/services/user-portal.git) | Keycloak-based user portal for OIDC identity management |


