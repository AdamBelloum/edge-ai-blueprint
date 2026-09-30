
# Workshop organiser guide

## Purpose and responsibility boundary

The workshop organiser manages disposable, participant-level workshop state after the platform administrator has deployed and validated the infrastructure.

The administrator is responsible for the long-lived platform configuration: trusted TLS, Keycloak availability and realm configuration, the confidential JupyterHub OIDC client, JupyterHub OIDC redirect configuration, and infrastructure health checks.

The organiser does not create or reconfigure the JupyterHub OIDC client. The organiser prepares and cleans up workshop cohorts.

## Entry point

Run the organiser menu from the repository root:

```bash
scripts/workshop/organizer-main.sh
```

The menu provides two workshop lifecycle actions:

1. **Prepare and initialise a beginner or advanced workshop**
2. **Delete participant workspaces and Keycloak identities**

Flower server and client processes are not started by preparation. Start them only after cohort preparation has completed.

## Prepare a workshop cohort

Choose menu option `1` and select `beginner` or `advanced`.

Preparation first validates workshop readiness and then initialises the selected cohort. It creates the participant-level workshop state required for the selected tutorial, including the identities, group assignments, workspace setup, and prepared local data required by the workshop workflow.

For automation, use an explicit mode and the required safety acknowledgement:

```bash
scripts/workshop/organizer-main.sh \
  --non-interactive \
  --mode beginner \
  --confirm-cohort-reset \
  prepare
```

The explicit acknowledgement is required because cohort preparation may replace participant JupyterHub workspaces.

## Reset participant state

The organiser provides two separate reset actions. Both preserve long-lived
platform and administrator material.

### Full federated-learning reset

Choose menu option `2`, or run `organizer-main.sh reset`, after a workshop
cycle finishes or when the complete cohort must be removed.

It stops the organiser-controlled Flower server and removes:

- selected participant JupyterHub servers and workspaces;
- inventory-derived participant Keycloak users and groups; and
- matching protected local credential exports under `secrets/workshops/`.

The confirmation explicitly includes deletion of stale initial credentials.
They must not be committed to Git.

### Participant-identity reset only

Choose menu option `3`, or run `organizer-main.sh reset-participants`, when
only participant identities and their credential exports must be removed.

It removes inventory-derived participant Keycloak users/groups and matching
protected local credential exports. It does **not** stop or start Flower,
remove JupyterHub servers or workspaces, change tutorial mode, create a new
cohort, or alter platform infrastructure.

Both actions leave the Keycloak realm and administrator credentials, JupyterHub
OIDC client material, TLS certificates/private keys, SSH keys, and deployment
inventory/configuration intact.

After a full reset, prepare a new workshop cycle before participants use the
platform again. An identity-only reset deliberately retains existing
FL/JupyterHub state.

## Participant guidance

Provide participants with their credentials only after preparation succeeds. Participants should follow the `00_START_HERE.md` notebook guide for their selected workshop level. The participant guides describe work after cohort preparation; they do not replace organiser preparation or reset procedures.
