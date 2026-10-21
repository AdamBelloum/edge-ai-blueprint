# Hands-on Computing Platform

Infrastructure deployment and workshop orchestration for repeatable, hands-on computing education.

This independently maintained project builds on the [original DIGITAfrica Edge-AI blueprint](https://gitlab.inria.fr/digitafrica/blueprints/edge-ai-blueprint). It extends the original infrastructure foundation with role-based administrator and workshop-organiser workflows for preparing participant environments and delivering tutorial materials through JupyterHub.

The associated tutorial collection is available at **[Parallel & Distributed Computing Learning Hub](https://adambelloum.github.io/Tutorials/)**.

Deploying infrastructure does not automatically prepare a participant cohort, publish every tutorial, or execute workshop activities.

## Scope and responsibilities

| Layer | Responsibility |
|---|---|
| Infrastructure | Deploy and configure nodes, Kubernetes, networking, persistent storage, TLS, authentication, and JupyterHub |
| Workshop orchestration | Prepare participant identities and environments, select supported teaching modes, publish materials, and manage workshop-specific preparation and reset actions |
| Learning activities | Participants follow tutorials, complete exercises, and run the selected workshop's activities |

Workshop-specific components, datasets, execution procedures, and validation results belong in dedicated guides.

### Relationship to the tutorial collection

The [Tutorials learning hub](https://adambelloum.github.io/Tutorials/) provides educational content: notebooks, exercises, reference materials, and module-specific instructions.

This platform provides the infrastructure and operational workflows used to deliver supported materials to participants. Availability in the tutorial collection does not, by itself, mean that a workshop is integrated or runtime-validated on this platform.

Beginner and advanced modes, guided notebooks, and organiser-controlled solution release are available only where implemented. [Workshop assets](workshop_assets/README.md) lists every workshop, module and track with its current status; the organiser menu and module documentation remain the reference for limitations.

## Who uses this repository?

| Role | Responsibilities | Start here |
|---|---|---|
| Platform administrator | Configure and deploy infrastructure, check health, recover paused deployments, and maintain the platform | [Infrastructure deployment](docs/infrastructure-deployment.md) |
| Workshop organiser | Prepare participant cohorts, publish materials, distribute credentials, and manage preparation and reset | [Workshop organiser guide](docs/workshop-organiser.md) |
| Participant | Access JupyterHub and complete assigned activities | Instructions distributed by the organiser |
| Operator or contributor | Inspect architecture, diagnose failures, and record validation evidence | [Operations and validation](docs/operations-and-validation.md) and [Architecture](docs/architecture.md) |

## Deployment configurations

The **Tier-0 and Tier-1 terminology originates from the [DIGITAfrica Edge-AI blueprint](https://gitlab.inria.fr/digitafrica/blueprints/edge-ai-blueprint)**. This project extends the deployment workflows with a Tier-2 context.

The current administrator menu offers **Tier-1** and **Tier-2**. Configure the appropriate inventory through the setup wizard and use the same tier for health checks and recovery.

Tier-0 infrastructure functionality is retained from the original blueprint, but is not an option in the current administrator menu. Consult the infrastructure guide before using its lower-level playbooks.

Deployment topology and authentication profile are separate choices:

| Profile | Intended use | Important boundary |
|---|---|---|
| Basic fallback | Controlled testing using self-signed TLS and direct JupyterHub dummy authentication | Certificate warnings are expected; dummy authentication is unsuitable for untrusted public access |
| Managed-Keycloak OIDC | Authenticated participant access with trusted TLS and managed identity integration | Deployment can pause until trusted TLS is ready; participant provisioning remains an organiser action |

The administrator menu can resume paused managed-OIDC deployments after checking trusted TLS.

See [Infrastructure deployment](docs/infrastructure-deployment.md) for topology and configuration details. The scripts are the implementation source of truth if a guide has not yet been updated.

## Hardware and network requirements

Sizing depends on deployment profile, concurrent participant sessions, tutorial workloads, container images, and persistent data. Infrastructure readiness is not a participant-capacity benchmark.

### Hardware used for testing

The repository's deployment and workshop workflows have been tested in a three-node environment with these specifications per node:

| Resource | Specification per node |
|---|---|
| Architecture | x86_64 |
| CPU | 4 logical CPUs; Intel Xeon Cascadelake reported by the operating system |
| Memory | Approximately 8 GiB; 7.8 GiB reported |
| Storage | Approximately 100 GB root disk; 99 GB filesystem reported |
| Operating system | Debian GNU/Linux 13 (trixie) |

This describes the hardware used for testing, not a guarantee that every module or profile has passed end-to-end validation. Consult the relevant guides for feature-specific validation status.

In this configuration, `/`, `/var/lib`, and `/home` share one root filesystem. Container images, platform state, participant files, datasets, and logs compete for its capacity.

Testing on this hardware does not establish a maximum participant count, a tested minimum configuration, or support for every operating system and processor architecture.

### Minimum and recommended sizing

The following figures are **provisional planning guidance**, not validated acceptance thresholds:

| Configuration | CPU per server/worker | RAM per server/worker | Usable disk per server/worker | Guidance |
|---|---:|---:|---:|---|
| Minimum starting point for a small pilot | 4 logical CPUs | 8 GiB | 100 GB | Start at the tested hardware scale and validate the selected profile and workshop |
| Recommended starting point for additional headroom | 4–8 logical CPUs | 16 GiB | 150–200 GB | Allow more capacity for concurrent sessions, images, workspaces, and runtime services |

Provision the node count required by the selected topology. These figures do not replace module-specific requirements or imply that every workload fits within them.

For larger cohorts, increase worker capacity or count based on measured resource use, participant resource limits, storage growth, and concurrent-session tests. Validate central services and participant workloads before advertising a supported cohort size.

Assess GPUs, specialised runtimes, and additional storage in workshop-specific documentation. No universal optimal configuration is claimed.

### Control machine and connectivity

The control machine needs Bash, Git, Python 3, Ansible, and the required Ansible collections, plus SSH access and deployment privileges on target nodes.

Before deployment, confirm:

- node-to-node connectivity required by the selected Kubernetes topology;
- participant access to the configured public platform URL;
- DNS and certificate prerequisites for the selected TLS profile;
- access to required repositories, package sources, and image registries; and
- sufficient storage for platform state and participant workspaces.

For Let's Encrypt HTTP-01 issuance, the hostname must resolve correctly and the challenge endpoint must be reachable on port 80. HTTPS participant access requires port 443. Consult the deployment guide for the complete network configuration; this is not an exhaustive firewall rule list.

## Getting started

Run commands from the repository root. Review the linked guides before deployment or reset changes.

### 1. Install Ansible dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install ansible
ansible-galaxy collection install -r requirements.yml
```

Additional requirements depend on the selected deployment and workshop.

### 2. Administrator: configure and deploy

```bash
bash scripts/admin/admin-main.sh
```

The menu provides:

- **Inspect:** read-only health checks for the selected tier;
- **Deploy:** configuration and deployment through the setup wizard;
- **Recover:** resume a paused Managed-Keycloak OIDC deployment; and
- **Cleanup:** destructive cleanup of dedicated disposable VMs, with a mandatory dry run and confirmation.

Tier-specific inventories are located under:

```text
inventories/workshop/tier1/hosts.ini
inventories/workshop/tier2/hosts.ini
```

Deploy and validate the platform before workshop preparation. Infrastructure readiness does not prove participant login, notebook execution, or workshop-runtime acceptance.

### 3. Organiser: prepare access and materials

```bash
bash scripts/workshops/organizer-main.sh
```

Follow the workflow supported by the selected profile and workshop:

1. Provision participant identities and groups where managed identity is used.
2. Prepare the workshop after the required cohort exists.
3. Issue and export credentials when ready for distribution.
4. Distribute the platform URL, credentials, and instructions securely.
5. Verify participant access and activity execution before the session.

After pulling updates or adding a workshop/module, run application reconciliation before publishing updated materials:

```bash
bash scripts/workshops/organizer-main.sh reconcile-applications
```

Reconciliation changes deployed configuration; it is not read-only. Review the organiser guide and use the correct deployment context.

Teaching-file publication, delivery activation, runtime installation, and participant execution validation are distinct steps. Some actions provide only local checks or staging; others remain blocked pending validation. Consult action descriptions and module guides.

### 4. Participant: access the assigned environment

Open the organiser-provided JupyterHub URL in a browser, follow the authentication instructions, and complete the assigned materials. Participants do not need administrator SSH access or deployment privileges.

## Operational lifecycle

1. Configure and deploy infrastructure.
2. Validate infrastructure and authentication readiness.
3. Prepare the cohort and teaching materials.
4. Validate participant access and activity execution.
5. Run the session and retain required evidence.
6. Reset the appropriate workshop or participant state.

Workshop reset, participant-account removal, and VM cleanup have different scopes. Infrastructure cleanup is not a routine substitute for organiser-level reset.

## Documentation and repository map

| Guide | Purpose |
|---|---|
| [Infrastructure deployment](docs/infrastructure-deployment.md) | Configuration and deployment procedures |
| [Workshop organiser](docs/workshop-organiser.md) | Cohort preparation, delivery, and reset |
| [Operations and validation](docs/operations-and-validation.md) | Health checks, troubleshooting, and acceptance evidence |
| [Architecture](docs/architecture.md) | Component boundaries and interactions |
| [Workshop assets](workshop_assets/README.md) | Where each workshop's material lives and how it reaches participants |

Module-specific requirements and validation documents are maintained under `docs/`. Historical material under `docs/archive/` is not the default operational procedure.

```text
scripts/admin/         Administrator entry point and deployment helpers
scripts/workshops/     Organiser entry point, controllers, and module helpers
scripts/lib/           Shared script utilities
inventories/           Inventories and deployment configuration
playbooks/             Ansible deployment playbooks
roles/                 Ansible implementation roles
workshop_assets/       Teaching material for every workshop (catalogue in workshop_assets/README.md)
tests/                 Automated checks and validation support
docs/                  Operational and module-specific documentation
data/                  Local/generated runtime data where applicable
secrets/               Protected local secret records; not for Git
```

## Security and generated files

- Never commit passwords, private keys, client secrets, or participant credential exports.
- Use protected, ignored local files such as `secrets/`, Ansible Vault, or an approved secret store as supported by the workflow.
- Distribute credential exports only through authorised channels.
- Keep participant workspaces and generated datasets separate from source-controlled teaching assets.
- Do not use dummy authentication for an untrusted public deployment.
- Use VM cleanup only on dedicated disposable machines and review its dry run.

## Origin and acknowledgements

This independently maintained project uses the [DIGITAfrica Edge-AI blueprint](https://gitlab.inria.fr/digitafrica/blueprints/edge-ai-blueprint) as its starting point. We acknowledge the original contributors for the Ansible-based infrastructure foundation and Edge-AI platform structure.

This project extends that foundation with multi-workshop orchestration, participant-environment management, deployment recovery, and role-based operational workflows. Attribution identifies the project's origin; it does not imply ongoing DIGITAfrica ownership or endorsement.

Educational materials have their own provenance and licensing. Their licence statements must not be assumed to apply automatically to this infrastructure repository. Applicable upstream licence and attribution obligations must be preserved.

## Related projects and services

| Project | Purpose |
|---|---|
| [Tutorials learning hub](https://adambelloum.github.io/Tutorials/) | Associated educational materials and hands-on tutorials |
| [Original DIGITAfrica Edge-AI blueprint](https://gitlab.inria.fr/digitafrica/blueprints/edge-ai-blueprint) | Original infrastructure foundation and tier terminology |
| [DIGITAfrica k3s-cluster](https://gitlab.inria.fr/digitafrica/blueprints/services/k3s-cluster.git) | Standalone k3s infrastructure |
| [DIGITAfrica nfs-server](https://gitlab.inria.fr/digitafrica/blueprints/services/nfs-server.git) | NFS server and provisioner for persistent storage |
| [DIGITAfrica jupyterhub-on-k3s](https://gitlab.inria.fr/digitafrica/blueprints/services/jupyterhub-on-k3s.git) | JupyterHub deployment on Kubernetes |
| [DIGITAfrica user-portal](https://gitlab.inria.fr/digitafrica/blueprints/services/user-portal.git) | Original Keycloak-based identity-service blueprint |
| [Independently maintained user-portal](https://github.com/AdamBelloum/user-portal) | Separately maintained Keycloak-based identity service |

