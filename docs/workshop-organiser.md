# Workshop organiser guide

## Purpose and responsibility boundary

The workshop organiser manages participant cohorts and teaching content after the platform administrator has deployed and validated the infrastructure.

The administrator owns long-lived platform configuration: TLS, authentication, Keycloak realm configuration and the confidential JupyterHub OIDC client where managed OIDC is enabled, JupyterHub redirect configuration, and infrastructure health checks. The organiser does not create or reconfigure the JupyterHub OIDC client.

Workshop application reconciliation is available to the organiser after workshops or modules are added or updated. It updates workshop applications and JupyterHub; it is not a replacement for initial infrastructure deployment.

## Entry point and current menu

Run from the repository root:

```bash
bash scripts/workshops/organizer-main.sh
```

The top-level menu provides:

- **1 — Manage participant cohort**: provision identities/groups, issue/export credentials, or inspect participant-account status.
- **2 — Reset active workshop cycle**: reset the active workshop and cohort, or remove participant identities and credential exports only.
- **3 — Reconcile workshop applications after adding or updating a workshop/module**.
- **4 — Workshops**: select Introduction to AI, Federated Learning, or Cloud Computing SOA.
- **0 — Exit**.

Use the script's help for the supported command-line actions:

```bash
bash scripts/workshops/organizer-main.sh --help
```

## Recommended workshop sequence

1. Have the administrator deploy and validate the platform.
2. After pulling changes that add or update a workshop/module, run **Reconcile workshop applications** before publishing or activating that content. This changes deployed applications and JupyterHub; do not treat it as a documentation-only check.
3. Choose **Manage participant cohort → Provision participant identities and groups**. This provisions identities without passwords; participants cannot log in until credentials are issued. A complete existing cohort is left unchanged. Inconsistent accounts must be repaired or reset before proceeding.
4. Choose **Workshops**, then the workshop and, where applicable, module. Prepare or activate the intended beginner or advanced track.
5. Choose **Manage participant cohort → Issue and export participant credentials** when ready to distribute access. This resets all cohort passwords and writes a protected local TSV export with mode `0600` under `secrets/workshops/`. Reissuing credentials changes the passwords; securely redistribute the new export.
6. Distribute credentials securely and direct participants to the selected workshop's entry guide.

Participant-account operations require authorised Keycloak access. Do not commit credential exports, passwords, tokens, or private keys to Git.

## Workshop-specific actions

### Federated Learning

Under **Workshops → Federated Learning**, the menu provides:

1. Prepare beginner workshop and start Flower.
2. Prepare advanced workshop and start Flower.
3. Release advanced reference solutions.
4. Manage Flower server.

Preparation requires a complete participant cohort and delegates to the Federated Learning helper. The organiser workflow includes Flower server startup; it must not be described as preparation without server startup. Participants follow their track's instructions to start and observe their clients. Do not assume organiser preparation automatically runs participant clients or completes training rounds.

For non-interactive FL preparation, use the explicit mode and destructive-operation acknowledgement:

```bash
bash scripts/workshops/organizer-main.sh \
  --non-interactive \
  --mode beginner \
  --confirm-cohort-reset \
  fl-prepare
```

The supported action is `fl-prepare`, not `prepare`. The acknowledgement is required because preparation may replace participant workspaces. These non-interactive options apply to FL preparation, not to every workshop action.

### Introduction to AI

Choose **Workshops → Introduction to AI**, then the intended module. Modules 1–3 are available. Follow the selected module's readiness and publication/activation actions. Where available, release advanced reference solutions separately when the organiser intends participants to receive them.

### Cloud Computing SOA

Choose **Workshops → Cloud Computing SOA**, then:

- **Module 1 — REST API**;
- **Module 2 — Microservices and JWT Authentication**; or
- **Module 3 — Containerization and Orchestration**.

Each module offers readiness checking, beginner activation, advanced TODO activation, advanced reference-solution release, and deployment status. Activation selects content for new participant server spawns; do not assume already-running servers immediately receive it.

Module 3 additionally offers local asset validation, beginner/advanced bundle exports, reference-solution export with confirmation, and local workflow information. Direct local actions bypass platform context:

```bash
bash scripts/workshops/organizer-main.sh cloud-module3-local-check beginner
bash scripts/workshops/organizer-main.sh cloud-module3-local-export beginner /tmp/module3-beginner.tar.gz
```

For a reference-solution bundle, explicit confirmation is required:

```bash
bash scripts/workshops/organizer-main.sh cloud-module3-local-export solutions /tmp/module3-solutions.tar.gz --confirm-solutions
```

Local checks validate mapped assets and Python/Bash syntax only; they do not test containers or services. Exports contain the selected track plus shared tests, not generated keys. Local exports do not activate a workshop or release solutions to participant servers. The interactive organiser menu still loads platform context.

## Reset participant state

Under **Reset active workshop cycle**, choose the reset scope deliberately.

### Reset active workshop and participant cohort

Choose submenu option **1**, or run:

```bash
bash scripts/workshops/organizer-main.sh reset
```

Although implemented in the Federated Learning reset helper, this action uses the active deployment inventory to select the participant cohort. After confirmation, it performs these steps in order:

1. Stops the organiser-controlled Flower server.
2. Stops selected participant JupyterHub server pods and waits for termination.
3. Deletes the selected participant persistent workspaces.
4. Deletes inventory-derived participant Keycloak users and same-named groups, then removes local credential exports matching the configured Keycloak hostname.
5. Patches `digitafrica-workshop-state` to a neutral selection: `workshop_type: none`, `workshop_module: none`, `mode: beginner`, and `solutions_released: false`.

Participants must copy any needed data before confirming this destructive action. Reset does not prepare a replacement workshop, recreate accounts, or issue credentials. Prepare a new workshop cycle and issue fresh credentials before participants return.

The helper stops on failure; cleanup is sequential, not atomic, and earlier completed steps are not automatically rolled back. Check its output before assuming the full reset completed. The final state patch changes the workshop selection and release flag; it does not itself prove previously delivered solution files have been removed from every location.

### Remove participant identities and credential exports only

Choose submenu option **2**, or run:

```bash
bash scripts/workshops/organizer-main.sh reset-participants
```

This removes inventory-derived participant identities/groups and matching protected credential exports. It does not stop or start Flower, remove JupyterHub servers/workspaces, or prepare a new workshop. Retained workspaces are not a newly prepared cohort.

Both reset scopes preserve long-lived platform and administrator material, including Keycloak realm/client configuration, TLS material, SSH keys, and deployment inventory/configuration. Top-level option **3** is application reconciliation, not participant reset.

## Participant guidance and TA review

Provide the entry guide for the selected workshop, module, and track; do not assume every workshop uses `00_START_HERE.md`. Participant guides describe work after organiser preparation and do not replace cohort or infrastructure procedures.

Beginner materials should guide participants step by step. Advanced materials should identify TODOs and expected outcomes without requiring access to unreleased reference solutions.

For the TA participant test, record the repository commit and selected track. TAs should attempt the practical using its comments and guides, recording the exact file/step for missing, unclear, or incorrect instructions and any organiser intervention needed. Separate documentation findings from environment or implementation failures. Structural checks are not evidence that participant guidance is sufficient or that the practical succeeds at runtime.
