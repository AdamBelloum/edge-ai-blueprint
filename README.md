# DIGITAfrica Edge-AI Blueprint

An Ansible-based blueprint for deploying an Edge-AI teaching and research platform and organising practical workshops through JupyterHub.

The repository separates three responsibilities:

1. **Platform administration** — infrastructure deployment, k3s, JupyterHub, networking, storage, TLS, authentication, and infrastructure health checks.
2. **Workshop organisation** — participant cohorts, protected credential exports, workshop preparation and activation, solution release, and participant-state resets.
3. **Participant activities** — guided beginner practicals or advanced TODO-based exercises, including participant-controlled application execution.

Available workshop families are **Introduction to AI**, **Federated Learning**, and **Cloud Computing SOA**. Infrastructure deployment and workshop preparation are separate lifecycle steps: deploying the platform does not itself provision a fresh participant cohort or complete a practical.

## Who should use which guide?

| Reader | Start here | Primary goal |
|---|---|---|
| Platform administrator | [Infrastructure deployment](docs/infrastructure-deployment.md) | Configure, deploy, and maintain infrastructure |
| Workshop organiser | [Workshop organiser guide](docs/workshop-organiser.md) | Manage cohorts, prepare teaching content, and release solutions safely |
| Researcher or application developer | [Federated-learning application](docs/federated-learning-application.md) | Configure and run a reproducible federated-learning experiment |
| Operator or tester | [Operations and validation](docs/operations-and-validation.md) | Inspect deployment health, diagnose failures, and record acceptance evidence |
| Architect or contributor | [Architecture](docs/architecture.md) | Understand component boundaries and system interactions |

## Deployment profiles

### Tier-1 and Tier-2 workshop deployments

The administrator workflow supports explicit **Tier-1** and **Tier-2** selection. Tier-2 uses its own `tier2_server` and `tier2_agents` inventory groups and deployment configuration; it is not included in the legacy site playbook.

The configured platform provides k3s, JupyterHub, workshop assets, and the selected networking, storage, TLS, and authentication settings. Managed-Keycloak OIDC setup belongs to infrastructure deployment, not participant cohort preparation.

The setup wizard creates or replaces local ignored inventory and configuration for the selected tier. The administrator workflow uses:

- `inventories/workshop/tier1/hosts.ini`; or
- `inventories/workshop/tier2/hosts.ini`.

Configure SSH access to the intended VMs and review the selected inventory and settings before deployment. Keep generated secrets and credential exports outside Git.

### Legacy Tier-0 and site playbooks

Tier-0 retains single-node options, including Docker notebook/monitoring and k3s installation or joining a Tier-1 cluster, depending on configuration.

`playbooks/site.yml` imports **Tier-0 followed by Tier-1 only**. The legacy production-inventory commands remain separate from the guided Tier-1/Tier-2 workshop workflow; do not assume `site.yml` deploys Tier-2.

## Quick start: administrator

Prepare the Ansible control environment and install the required collections:

```bash
pip install ansible
ansible-galaxy collection install -r requirements.yml
```

From the repository root, open the administrator menu:

```bash
bash scripts/admin/admin-main.sh
```

The menu provides:

- **1 — Run infrastructure health check**: select Tier-1 or Tier-2.
- **2 — Configure and deploy infrastructure**: delegates to the setup wizard.
- **3 — Clean VMs for a fresh deployment**: destructive; intended for dedicated disposable VMs, with a mandatory dry run and explicit confirmation.
- **4 — Resume paused Managed-Keycloak OIDC deployment**: select the saved tier configuration and resume after trusted TLS is available, without rerunning the platform and identity phases.
- **0 — Exit**.

Do not use VM cleanup as a participant-cohort reset. See [Infrastructure deployment](docs/infrastructure-deployment.md) for deployment details and [Operations and validation](docs/operations-and-validation.md) for health-check guidance.

## Quick start: workshop organiser

After the administrator has deployed and validated the platform:

```bash
bash scripts/workshop/organizer-main.sh
```

The organiser menu provides participant cohort management, active-workshop resets, application reconciliation, and workshop selection.

The normal teaching workflow is:

1. Reconcile workshop applications after adding or updating a workshop/module, before publishing it.
2. Provision participant identities and groups.
3. Select the workshop/module and prepare or activate the intended track.
4. Issue and securely distribute participant credentials.
5. Run the practical; release reference solutions separately when appropriate.

Reconciliation changes deployed applications and JupyterHub; it is not a read-only documentation check. Provisioning identities does not issue passwords. Credential issuance is a separate action that resets cohort passwords and writes a protected export under `secrets/workshops/`.

See the [Workshop organiser guide](docs/workshop-organiser.md) for exact menu paths, supported actions, reset scopes, and local Module 3 exports.

## Teaching content and execution boundaries

- **Introduction to AI:** Modules 1–3, with module-specific publication/activation and solution-release actions where available.
- **Federated Learning:** beginner and advanced preparation, advanced reference-solution release, and Flower server lifecycle management.
- **Cloud Computing SOA:** Module 1 REST API, Module 2 Microservices and JWT Authentication, and Module 3 Containerization and Orchestration.

Beginner tracks provide guided exercises; advanced tracks use TODO-based instructions. Reference solutions are released separately by the organiser. Participants should follow the entry guide for their selected workshop, module, and track.

Infrastructure deployment does not automatically run a federated-training experiment. The FL organiser preparation workflow includes Flower server startup; participants follow their tutorial to start their clients and observe rounds. Participant groups and worker placement are inventory-derived; do not assume every workshop is limited to two fixed Silos.

Cloud SOA Module 3 also supports local asset checks and track-specific bundle exports without platform access through direct local actions. These checks are structural/syntax checks, not evidence that containers, services, or participant exercises work at runtime. Local export is separate from JupyterHub activation and participant solution release.

## Repository documentation map

```text
README.md
├── docs/
│   ├── infrastructure-deployment.md
│   ├── federated-learning-application.md
│   ├── operations-and-validation.md
│   ├── workshop-organiser.md
│   └── architecture.md
├── scripts/
│   ├── admin/
│   └── workshop/
├── workshop_assets/
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
