
# Workshop organiser guide

## Purpose and responsibility boundary

The workshop organiser manages disposable, participant-level workshop state after the platform administrator has deployed and validated the infrastructure.

The administrator is responsible for the long-lived platform configuration: trusted TLS, Keycloak availability and realm configuration, the confidential JupyterHub OIDC client, JupyterHub OIDC redirect configuration, and infrastructure health checks.

The organiser does not create or reconfigure the JupyterHub OIDC client. The organiser prepares and cleans up workshop cohorts.

## Entry point

Run the organiser menu from the repository root:

```bash
scripts/workshops/organizer-main.sh
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
scripts/workshops/organizer-main.sh \
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

## Cloud Computing SOA Module 3 runtime reset

Use this after the Module 3 exercise runtime has been started on participant
VMs. It stops the workshop-specific services and removes the workshop
artifacts. It selects resources by name or label, so run the preview first.

In the organiser menu, open **Cloud Computing SOA**, then its Module 3 menu:

- option `11` previews the reset and makes no changes;
- option `12` performs the reset after you confirm.

(Option `9` starts the beginner containerization runtime on the assigned VMs
and option `10` shows its status.)

### What the reset removes

For each current or previously recorded Module 3 target VM:

- the Docker Compose project `m3-containerization-group_NN`: its containers,
  networks and named volumes (the volumes hold the services' stored user and
  URL records) and its images that have no custom tag, via
  `docker compose down --volumes --remove-orphans --rmi local`, followed by a
  sweep for remaining resources that carry the project label;
- the runtime directory `/var/lib/digitafrica/module3-runtime/group_NN`,
  including the generated authentication keys, and its marker file.

In Kubernetes, every NetworkPolicy named `module3-group-<N>-runtime-egress` in
the `digitafrica` namespace is deleted, for any group number. The organiser's
local record of target VMs is pruned only for VMs whose cleanup was verified.

### What it is not intended to touch

The reset does not delete the Module 3 teaching ConfigMaps
(`…-module3-*`), the staging directory under `/opt/digitafrica/k8s-notebooks/`,
JupyterHub resources, other workshops' resources, or the Docker build cache.
Direct-credential Secrets or ConfigMaps, if any were created, are not removed
either.

Do not give unrelated resources names or Compose labels matching the patterns
above, because they would be removed.

### Safety checks and failure handling

- The reset refuses a runtime directory or Compose project without a matching
  Module 3 marker file. The marker is a safety guard, not proof of ownership.
- If the reset reports a failure, state may be partly removed. Fix the reported
  problem, run the preview again, then repeat the reset and verify the result.
- The global workshop reset does **not** stop the Module 3 runtime. It asks you
  to confirm that no external Module 3 runtime remains. Where a runtime exists,
  run option `12`, verify it is gone, and only then confirm truthfully.

### Validation status

Start, preview and reset were exercised in two live cycles on the Tier-2
inventory with two worker VMs; independent post-checks were run. This is not
full acceptance. Concurrent organisers, failure paths, other tiers and
pod-level access are untested.

## Participant guidance

Provide participants with their credentials only after preparation succeeds. Participants should follow the `00_START_HERE.md` notebook guide for their selected workshop level. The participant guides describe work after cohort preparation; they do not replace organiser preparation or reset procedures.
