
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

Choose menu option `2` when a workshop cycle has finished or must be restarted. The organiser asks for the public Keycloak URL when it has not already been configured.

Reset removes the selected participant state:

- participant JupyterHub workspaces;
- participant Keycloak users; and
- participant Keycloak groups.

It does not change the tutorial mode, create a replacement cohort, start Flower, or alter platform infrastructure.

The interactive menu reset also offers to remove the local participant credential export. In the currently configured deployment this is:

```text
secrets/workshops/ab-01.lab.uvalight.net-beginner-credentials.tsv
```

Remove this file when the associated participant accounts have been reset. It contains stale initial credentials and must not be committed to Git. The organiser must explicitly confirm its removal.

The reset action leaves long-lived platform and administrator material intact, including:

- the Keycloak realm and administrator credentials;
- the JupyterHub OIDC client and client secret;
- TLS certificates and private keys;
- SSH keys; and
- deployment inventory and configuration.

After reset, JupyterHub continues to redirect users to Keycloak. Removed participants cannot authenticate because their accounts no longer exist. Begin a new workshop cycle with preparation before participants can use the platform again.

> **Scope note:** local credential-export removal is offered by interactive menu option `2`. The explicit command-line `reset` action removes remote participant state but does not currently prompt to remove the local credential file.

## Participant guidance

Provide participants with their credentials only after preparation succeeds. Participants should follow the `00_START_HERE.md` notebook guide for their selected workshop level. The participant guides describe work after cohort preparation; they do not replace organiser preparation or reset procedures.
