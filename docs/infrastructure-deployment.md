# Infrastructure deployment

This guide is for platform administrators who deploy and maintain the DIGITAfrica Edge-AI infrastructure. It covers Ansible, Tier-0, Tier-1, k3s, JupyterHub, networking, storage, TLS, and authentication.

For running a Flower-based experiment after the platform is available, see [Federated-learning application](federated-learning-application.md). For acceptance checks and troubleshooting, see [Operations and validation](operations-and-validation.md).

## Scope

The infrastructure layer provides:

- Ansible-managed deployment to Tier-0 and/or Tier-1 nodes;
- k3s server and agent lifecycle for Tier-1;
- JupyterHub deployment through Helm;
- Traefik ingress or NodePort service exposure;
- JupyterHub user storage and example-notebook seeding;
- TLS configuration; and
- optional Keycloak/OIDC authentication.

The Tier-1 playbook also prepares the federated-learning application environment, but infrastructure deployment does not automatically execute an experiment.

---

## Prerequisites

### Control machine

Install Ansible and the required collections:

```bash
pip install ansible
ansible-galaxy collection install -r requirements.yml
```

The control machine must be able to connect by SSH to all target nodes. Use SSH keys where possible. If passwords or sensitive connection values are unavoidable, place them in Ansible Vault or an untracked secret variables file rather than a committed inventory.

### Target nodes

The roles install their own required operating-system and Kubernetes components. Before deployment, ensure that:

- each node has a supported Linux installation and network access suitable for package and image downloads;
- the control machine can reach every target through SSH;
- Tier-1 server and agent nodes can communicate on the network required by k3s;
- the public IP address or DNS name is known if ingress will be exposed externally; and
- persistent-storage requirements are understood before deploying user workloads.

---

## Inventory

Configure `inventories/prod/hosts.ini` for the topology being deployed.

```ini
### TIER 0 NODES ###
; [tier0]
; digitafrica-edge-node0 ansible_host=10.64.45.176

### TIER 1 NODES ###
[tier1_server]
digitafrica-edge-node1 ansible_host=10.64.45.176

[tier1_agents]
digitafrica-edge-node2 ansible_host=10.64.45.179

[all:vars]
ansible_user=ubuntu
ansible_become=true
# ansible_ssh_common_args='-o ProxyJump=proxy@bastion.example.org'
```

Only populate the groups relevant to the deployment:

- for Tier-0 only, leave `tier1_server` and `tier1_agents` empty or commented out;
- for Tier-1 only, no Tier-0 hosts are required;
- Tier-1 requires exactly one server host and may have one or more agents.

The inventory aliases, node hostnames, and Tier-1 configuration must be consistent. A k3s node may display its operating-system hostname rather than its Ansible inventory alias.

---

## Deployment modes

### Tier-0

`tier0.k3s_mode` determines how a Tier-0 node is used.

| `tier0.k3s_mode` | Result |
|---|---|
| `none` | Docker-based Jupyter notebook, cAdvisor, and Node Exporter |
| `single` | Single-node k3s cluster, JupyterHub through Helm, and optional model cache |
| `agent` | k3s agent joining the Tier-1 cluster |

### Tier-1

Tier-1 is a multi-node k3s deployment:

- one node in `[tier1_server]` provides the k3s server/control plane;
- nodes in `[tier1_agents]` join as k3s agents;
- application resources are deployed into `tier1.digitafrica_namespace`, normally `digitafrica`.

The principal Tier-1 infrastructure components are:

- k3s;
- Traefik, when ingress mode is selected;
- JupyterHub through Helm;
- Kubernetes storage for JupyterHub user homes;
- the JupyterHub TLS secret and ingress; and
- optional OIDC integration.

---

## Configure variables

The main configuration is in:

```text
inventories/prod/group_vars/all.yml
```

Set environment-specific values before deployment, in particular:

- public JupyterHub URL;
- Tier-0 and Tier-1 exposure modes;
- Tier-1 server hostname and cluster network ranges;
- storage class;
- TLS mode and associated certificate or ACME settings; and
- OIDC settings when external authentication is enabled.

### Tier-0 reference

| Variable | Default | Description |
|---|---|---|
| `tier0.k3s_mode` | `none` | `none` = Docker only; `single` = standalone k3s; `agent` = join Tier-1 |
| `tier0.expose_mode` | `ingress` | `ingress` = Traefik; `nodeport` = raw ports |
| `tier0.notebook_port` | `8888` | Jupyter container port |
| `tier0.jupyter_nodeport` | `30888` | Jupyter NodePort when using `nodeport` |
| `tier0.modelcache_nodeport` | `30080` | Model-cache NodePort when using `nodeport` |
| `tier0.enable_modelcache` | `false` | Deploy the static model-cache service |
| `tier0.notebook_user` | `digitafrica` | Local Linux user owning notebook files |
| `tier0.notebook_dir` | `/opt/digitafrica/notebooks` | Directory mounted into the notebook container |
| `tier0.notebook_password` | `digitafrica` | Plain-text password; configure an appropriate hash as well |
| `tier0.k3s_version` | `v1.30.4+k3s1` | k3s version for `k3s_mode=single` |
| `tier0.k3s_agent_server_host` | — | Tier-1 server hostname for `k3s_mode=agent` |
| `tier0.monitoring.node_exporter_port` | `9100` | Node Exporter port |
| `tier0.monitoring.cadvisor_port` | `8080` | cAdvisor port |

### Tier-1 reference

| Variable | Default | Description |
|---|---|---|
| `tier1.expose_mode` | `ingress` | `ingress` = Traefik on ports 80/443; `nodeport` = direct service ports |
| `tier1.tls_mode` | `selfsigned` | `selfsigned`, `letsencrypt`, `provided`, or `none` |
| `tier1.tls_cert_dir` | — | Control-machine path containing `tls.crt` and `tls.key`, used with `provided` |
| `tier1.tls_acme_email` | — | Email address for Let’s Encrypt registration |
| `tier1.k3s_version` | `v1.30.4+k3s1` | k3s version |
| `tier1.k3s_server_host` | — | k3s server hostname |
| `tier1.k3s_cluster_cidr` | `10.42.0.0/16` | Pod CIDR |
| `tier1.k3s_service_cidr` | `10.43.0.0/16` | Service CIDR |
| `tier1.digitafrica_namespace` | `digitafrica` | Namespace for application resources |
| `tier1.jupyterhub.jupyterhub_public_url` | `https://<host>/jupyter` | Public JupyterHub URL; must match the public IP address or DNS name |
| `tier1.jupyterhub.jupyter_nodeport` | `30888` | JupyterHub NodePort in NodePort mode |
| `tier1.jupyterhub.storage_class` | `local-path` | StorageClass for JupyterHub user PVCs |
| `tier1.jupyterhub.jupyterhub_admin_users` | `["admin"]` | JupyterHub administrator usernames |
| `tier1.mlflow.enabled` | `false` | Enable MLflow deployment |
| `tier1.mlflow.mlflow_port` | `5000` | MLflow listening port |
| `tier1.grafana_enabled` | `false` | Enable Grafana deployment |

MLflow and Grafana flags are reserved for future service implementation where applicable; do not treat an enabled flag alone as evidence that a production service is operational.

### OIDC / Keycloak reference

| Variable | Default | Description |
|---|---|---|
| `oidc.oidc_enabled` | `false` | `true` = Keycloak/OIDC login; `false` = dummy authenticator |
| `oidc.oidc_issuer_url` | — | Keycloak realm URL |
| `oidc.oidc_client_id` | — | Keycloak client ID |
| `oidc.oidc_client_secret` | — | Keycloak client secret |
| `oidc.oidc_scope` | `[openid, profile, email]` | OAuth scopes to request |
| `oidc.oidc_username_claim` | `preferred_username` | JWT claim used as the JupyterHub username |
| `oidc.oidc_tls_verify` | `true` | Keep certificate verification enabled; set to `false` only for a controlled self-signed test deployment |

### Workshop-organiser OIDC preparation

The platform deploys JupyterHub and may provide Keycloak, but the workshop organiser creates the JupyterHub OIDC client during workshop preparation.

- Enable the Authorization Code / Standard Flow.
- Register `https://<jupyterhub-public-host>/jupyter/hub/oauth_callback` as the redirect URI.
- Record the realm issuer URL, client ID, and, for a confidential client, client secret.
- In the setup wizard, choose Advanced deployment, enable OIDC, and enter these values.

The generated inventory is under `inventories/workshop/`, which is ignored by Git. Do not commit organiser-supplied OIDC settings or client secrets. Keep `oidc_tls_verify: true` when the JupyterHub environment trusts the Keycloak certificate chain.

---

## Deploy

Deploy all configured tiers:

```bash
ansible-playbook -i inventories/prod/hosts.ini playbooks/site.yml
```

Deploy Tier-0 only:

```bash
ansible-playbook -i inventories/prod/hosts.ini playbooks/tier0.yml
```

Deploy Tier-1 only:

```bash
ansible-playbook -i inventories/prod/hosts.ini playbooks/tier1.yml
```

To reconcile the Tier-1 server-side resources after changing Tier-1 application or Helm values, without running the agent plays:

```bash
ansible-playbook \
  -i inventories/prod/hosts.ini \
  playbooks/tier1.yml \
  --limit tier1_server \
  -e digitafrica_uninstall=false
```

Using `--limit tier1_server` is appropriate only when the agent topology itself does not need installation, reconciliation, or repair.

---

## Networking

### Ingress mode

With `expose_mode: ingress`, Traefik routes externally reachable traffic through ports 80 and 443.

| Service | Address |
|---|---|
| JupyterHub | `https://<host>/jupyter/` |
| Tier-0 model cache | `http://<host>/models/` |

A Traefik redirect middleware redirects `/jupyter` to `/jupyter/`.

### NodePort mode

With `expose_mode: nodeport`, services are exposed through configured Kubernetes NodePorts rather than Traefik paths.

| Service | Port variable | Default |
|---|---|---|
| JupyterHub, Tier-0 or Tier-1 | `jupyter_nodeport` | `30888` |
| Tier-0 model cache | `modelcache_nodeport` | `30080` |

Ensure the relevant ports are allowed by host and network firewalls before relying on NodePort access.

---

## TLS

TLS configuration is selected using `tier1.tls_mode` and is relevant in ingress mode.

### Self-signed certificate

```yaml
tier1:
  tls_mode: "selfsigned"
```

A certificate is generated on the Tier-1 server and stored in the Kubernetes secret `jhub-tls`. Browser warnings are expected because the certificate is not publicly trusted.

### Provided certificate

```yaml
tier1:
  tls_mode: "provided"
  tls_cert_dir: "/path/to/your/certs"
```

The specified directory on the control machine must contain `tls.crt` and `tls.key`. Ansible copies them to the Tier-1 server and updates the Kubernetes TLS secret.

### Let’s Encrypt

```yaml
tier1:
  tls_mode: "letsencrypt"
  tls_acme_email: "admin@example.org"
  jupyterhub:
    jupyterhub_public_url: "https://yourdomain.example/jupyter"
```

Let’s Encrypt requires:

- a real DNS name rather than a raw IP address;
- public reachability on ports 80 and 443; and
- an email address for ACME registration.

### No TLS

```yaml
tier1:
  tls_mode: "none"
  jupyterhub:
    jupyterhub_public_url: "http://10.64.45.176/jupyter"
```

Use this only in controlled non-production environments. It is unsuitable for credentials, research data, or any sensitive traffic.

---

## JupyterHub authentication

When OIDC is enabled, JupyterHub delegates authentication to Keycloak or another compatible OpenID Connect provider:

1. the user visits JupyterHub;
2. JupyterHub redirects the user to the identity provider;
3. the user authenticates;
4. the identity provider returns an OIDC token; and
5. JupyterHub validates the token and establishes the user session.

Register the callback URL with the identity provider:

```text
https://<your-host>/jupyter/hub/oauth_callback
```

When `oidc.oidc_enabled: false`, JupyterHub uses a dummy authenticator. This is appropriate only for controlled demonstrations and development because it accepts arbitrary username/password combinations.

---

## Storage and notebook seeding

JupyterHub user homes are backed by persistent volume claims using:

```yaml
tier1:
  jupyterhub:
    storage_class: "local-path"
```

Select a storage class appropriate to the availability and persistence requirements of the deployment. `local-path` is convenient for a basic k3s installation but has node-local behaviour. For multi-node persistence requirements, use a properly configured shared storage solution such as a tested NFS-backed provisioner.

Example notebooks are supplied to JupyterHub user servers through a Kubernetes ConfigMap rather than a node-specific host-path volume. This removes the previous node pinning constraint. Validate notebook seeding by logging in and spawning a real user server after relevant configuration changes.

---

## Uninstall

To run the configured uninstall lifecycle:

```bash
ansible-playbook \
  -i inventories/prod/hosts.ini \
  playbooks/site.yml \
  -e digitafrica_uninstall=true
```

Before using this command, review the uninstall tasks and determine the fate of:

- JupyterHub user PVCs and research notebooks;
- application data and experiment outputs;
- cluster certificates and secrets; and
- shared resources not owned exclusively by this deployment.

---

## Post-deployment checks

After deployment, use [Operations and validation](operations-and-validation.md) to check:

- k3s nodes and system workloads;
- Helm release state;
- JupyterHub ingress reachability;
- JupyterHub user-server spawning and seeded notebooks;
- Silo workspace rollout and bootstrap; and
- the distinction between platform readiness and a completed federated-learning experiment.

## Related documentation

- [Project overview](../README.md)
- [Federated-learning application](federated-learning-application.md)
- [Operations and validation](operations-and-validation.md)
- [Architecture](architecture.md)
