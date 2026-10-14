# Architecture

## Purpose

The DIGITAfrica Edge-AI Blueprint combines infrastructure deployment, workshop orchestration, and participant teaching materials. These layers have different owners and lifecycles. A platform deployment is not a prepared participant cohort, and a prepared cohort is not evidence that a practical or federated-learning experiment has completed.

## Layers and responsibilities

| Layer | Owner | Responsibilities |
|---|---|---|
| Platform infrastructure | Administrator | VM access, deployment configuration, k3s, networking, storage, TLS, authentication, JupyterHub, and infrastructure health checks |
| Workshop orchestration | Workshop organiser | Participant identities/groups, credential issuance, workshop preparation or activation, application reconciliation, solution release, and participant-state reset |
| Participant execution | Participant or experiment owner | Follow the selected track, complete exercises, start participant-controlled applications, and collect results |

Ansible playbooks and roles implement infrastructure configuration. Shell entry points route administrator and organiser operations to specialised helpers. Participant materials are separate from the control scripts that prepare or publish them.

## Deployment contexts

The guided administrator workflow supports Tier-1 and Tier-2 workshop deployments. Each tier has its own local inventory and configuration:

- Tier-1: `inventories/workshop/tier1/hosts.ini`, with `tier1_server` and `tier1_agents` groups.
- Tier-2: `inventories/workshop/tier2/hosts.ini`, with `tier2_server` and `tier2_agents` groups.

The setup wizard creates or replaces these ignored local settings. Operations must use the intended deployment context; a Tier-1 inventory must not be silently substituted for Tier-2.

Legacy Tier-0 options and production-inventory playbooks remain separate. `playbooks/site.yml` imports Tier-0 followed by Tier-1; Tier-2 has its own playbook.

## Administrator control flow

The public administrator entry point is `scripts/admin/admin-main.sh`. It delegates:

- configuration and deployment orchestration to `scripts/admin/setup-wizard.sh`;
- read-only infrastructure health checks to `scripts/admin/health-check.sh`;
- destructive disposable-VM cleanup to `scripts/admin/clean-vms.sh`; and
- paused managed-OIDC continuation to the setup wizard's resume action.

The deployment helpers include `scripts/admin/deploy-infrastructure.sh` for Ansible execution and `scripts/admin/keycloak-bootstrap.sh` for Keycloak provisioning/reconciliation.

Managed-Keycloak OIDC deployment establishes the long-lived identity integration and JupyterHub redirect configuration. Trusted TLS is a prerequisite for completing that profile. A paused deployment can resume from saved tier configuration after trusted TLS becomes available, without rerunning platform and identity phases.

VM cleanup is an infrastructure operation, not a workshop-cohort reset. The administrator menu requires a dry run and explicit confirmation before purging selected VM runtime state.

## Organiser control flow

`scripts/workshop/organizer-main.sh` owns top-level argument handling, shared menus, participant-account access, and routing to workshop controllers. Shared context/runtime libraries provide reusable configuration and safeguards; workshop helpers implement domain-specific preparation.

The organiser separates:

1. Provisioning participant identities and groups, without issuing passwords.
2. Preparing or activating a selected workshop/module and track.
3. Issuing credentials by resetting cohort passwords and writing a protected export.
4. Distributing credentials and running the practical.
5. Releasing reference solutions separately when appropriate.

Application reconciliation updates workshop applications and JupyterHub after content changes. It is a state-changing operation, not a read-only check or initial platform deployment.

Full active-workshop reset and identity-only reset have different scopes. Identity-only reset leaves application processes and JupyterHub workspaces in place; neither operation should be confused with VM cleanup.

## Teaching families and delivery

The workshop selector routes to Introduction to AI, Federated Learning, and Cloud Computing SOA. Introduction to AI and Cloud Computing SOA currently expose Modules 1–3 through the organiser entry point.

Beginner materials provide guided practicals; advanced materials use TODO-based instructions. Module publication/activation and reference-solution release are distinct actions. Content selected for new JupyterHub server spawns must not be assumed to appear immediately in already-running participant servers.

Cloud SOA Module 3 additionally supports direct local asset checks and bundle exports. These direct actions avoid platform access; the interactive organiser menu still loads platform context. Local export neither activates JupyterHub content nor releases solutions to participant servers. Structural/syntax checks do not establish runtime success.

## Federated-learning execution boundary

The FL organiser controller requires a complete participant cohort before preparation and delegates to the FL helper. Its preparation menu includes Flower server startup. Participant clients and completed training rounds remain separate execution steps governed by the selected practical.

Participant grouping and worker placement are inventory-derived. Two named Silo Deployments in legacy examples must not be treated as the universal topology of the current workshop workflow.

Distinguish three kinds of evidence:

- **Infrastructure health:** the selected platform's services are available.
- **Workshop readiness:** the intended cohort and teaching assets are prepared.
- **Execution success:** participants or experiment owners complete the intended application workflow and record its results.

Passing one level does not prove the next. Federated learning also does not, by itself, establish dataset permissions or guarantee privacy.

## Secrets and persistent state

Long-lived platform identity/TLS configuration is separate from disposable participant identities, workspaces, and credential exports. Generated secrets must remain outside Git, in ignored local files or protected secret stores.

Participant credential exports under `secrets/workshops/` are protected local files with mode `0600`. Reissuing credentials changes cohort passwords. Reference-solution bundles should be distributed only when the organiser intends to release them.

## Related documentation

- [README](../README.md): entry points and repository overview.
- [Infrastructure deployment](infrastructure-deployment.md): platform deployment procedures.
- [Workshop organiser guide](workshop-organiser.md): cohort and teaching-content lifecycle.
- [Federated-learning application](federated-learning-application.md): application and experiment responsibilities.
- [Operations and validation](operations-and-validation.md): validation evidence and troubleshooting.
