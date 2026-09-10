# DIGITAfrica Edge-AI Blueprint

Ansible-based blueprint for deploying an Edge-AI platform and preparing a federated-learning application environment.

The repository deliberately separates two concerns:

1. **Platform infrastructure** — Tier-0 and Tier-1 deployment, k3s, JupyterHub, networking, storage, TLS, and authentication.
2. **Federated-learning application** — Flower server and client workflows, Silo workspaces, datasets, experiment execution, and results.

The Ansible playbooks deploy and configure the platform. They prepare the federated-learning execution environment, but they do **not** automatically start a Flower server, start Flower clients, or run a federated-training round.

## Who should use which guide?

| Reader | Start here | Primary goal |
|---|---|---|
| Platform administrator | [Infrastructure deployment](docs/infrastructure-deployment.md) | Deploy and maintain Tier-0 or Tier-1 safely |
| Researcher or application developer | [Federated-learning application](docs/federated-learning-application.md) | Configure and run a reproducible federated-learning experiment |
| Operator or tester | [Operations and validation](docs/operations-and-validation.md) | Validate deployment status, diagnose failures, and record acceptance evidence |
| Architect or new project contributor | [Architecture](docs/architecture.md) | Understand component boundaries, responsibilities, and system interactions |

## What the blueprint provides

### Tier-0: single-node Edge-AI environment

Depending on configuration, Tier-0 can provide:

- a Docker-based Jupyter notebook environment;
- monitoring components such as cAdvisor and Node Exporter;
- a standalone k3s installation with JupyterHub; or
- a k3s agent joining a Tier-1 cluster.

### Tier-1: multi-node Edge-AI platform

Tier-1 provides:

- a k3s server and one or more k3s agents;
- JupyterHub with persistent user storage;
- Traefik ingress or NodePort exposure;
- configurable TLS and OIDC authentication;
- seeded example notebooks; and
- prepared Silo A and Silo B federated-learning workspaces.

## Federated-learning deployment scope

A successful Tier-1 deployment confirms that the platform and application workspaces are available. In the currently validated configuration, Silo A and Silo B:

- run as independent Kubernetes Deployments on worker nodes;
- contain Git and the required Python dependencies;
- obtain the configured tutorial/application repository during bootstrap; and
- remain available as prepared execution workspaces.

The following are separate application-level actions:

- starting the Flower server;
- starting each Silo client;
- registering clients with the server;
- executing training rounds; and
- recording models, metrics, logs, and experiment metadata.

See the [federated-learning application guide](docs/federated-learning-application.md) for those responsibilities.

## Quick start

### Prerequisites

On the Ansible control machine:

```bash
pip install ansible
ansible-galaxy collection install -r requirements.yml
```

Configure SSH access to the target nodes and review the environment-specific inventory and variables before deployment.

### Configure inventory and variables

- Inventory: `inventories/prod/hosts.ini`
- Configuration: `inventories/prod/group_vars/all.yml`

For Tier-1, define a `tier1_server` and one or more `tier1_agents`. Set the public JupyterHub URL, exposure mode, TLS mode, storage class, and authentication options for the target environment.

Do not commit passwords, private keys, or client secrets in inventory or variable files. Use Ansible Vault or an approved secret-management method.

### Deploy

Deploy both configured tiers:

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

For full configuration, deployment modes, and lifecycle guidance, see [Infrastructure deployment](docs/infrastructure-deployment.md).

## Validate after deployment

Use the [operations and validation guide](docs/operations-and-validation.md) to verify:

- k3s node and workload health;
- JupyterHub ingress reachability;
- JupyterHub user-server spawning and notebook seeding;
- Silo A and Silo B rollout and bootstrap completion; and
- federated-learning experiment execution, when applicable.

## Repository documentation map

```text
README.md
├── docs/
│   ├── infrastructure-deployment.md
│   ├── federated-learning-application.md
│   ├── operations-and-validation.md
│   └── architecture.md
├── inventories/
├── playbooks/
└── roles/
```

## Related blueprints

| Blueprint | Purpose |
|---|---|
| [k3s-cluster](https://gitlab.inria.fr/digitafrica/blueprints/services/k3s-cluster.git) | Standalone k3s cluster without the application layer |
| [nfs-server](https://gitlab.inria.fr/digitafrica/blueprints/services/nfs-server.git) | NFS server and provisioner for multi-node persistent storage |
| [jupyterhub-on-k3s](https://gitlab.inria.fr/digitafrica/blueprints/services/jupyterhub-on-k3s.git) | JupyterHub-only deployment on an existing cluster |
| [user-portal](https://gitlab.inria.fr/digitafrica/blueprints/services/user-portal.git) | Keycloak-based user portal for OIDC identity management |

