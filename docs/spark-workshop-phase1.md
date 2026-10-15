# Spark beginner workshop — Phase 1 baseline and integration map

## Status and scope

Phase 1 inspection is complete for the integration points listed below.
Acceptance remains pending review and a documentation commit.
No Spark runtime, tutorial assets, controller, or activation has been implemented.
No live deployment has been tested during this phase.

## Verified baseline

- Repository: AdamBelloum/edge-ai-blueprint.
- Working directory: /home/adam/edge-ai-blueprint.
- Baseline: e34211d, merge of PR #20 (Cloud SOA module-menu refactoring).
- Branch: feat/spark-beginner-workshop.
- Working tree was clean before creating this record.
- Existing local release records, backups, and caches were preserved.
- A local Git exclude protects scripts/workshops/workshop-release.env;
  neither that record nor the exclude rule is part of this documentation.
- Tracked workshop orchestration uses scripts/workshop/ (singular).

## Verified integration points

| Area | Implementation | Finding |
| --- | --- | --- |
| Entry point | scripts/workshop/organizer-main.sh | Owns CLI validation, shared menus, helper setup, and dispatch. |
| Workshop registration | organizer-main.sh | Requires menu routing and controller loading; any new explicit CLI actions also require help, parser registration, option validation, and dispatch. |
| Controller pattern | scripts/workshop/controllers/cloud_computing_soa.sh | Sourced facade delegates to a course implementation under its own workshop directory. |
| Activation safeguards | scripts/workshop/cloud-computing-soa/course-main.sh | Cloud handlers validate cohort completeness, shared activation permission, and asset readiness before patching state. These are patterns to reuse, not Spark runtime tests. |
| Asset staging | roles/k8s_apps/tasks/install.yml | Module 2 copies canonical workshop_assets sources to central staging and creates ConfigMaps with explicit flat keys. |
| Workshop state | install.yml and roles/k8s_apps/templates/jhub-values.yaml.j2 | Shared state includes workshop_type, workshop_module, mode, and solutions_released. State migration and seeder validation must accommodate the chosen Spark identity. |
| Asset delivery | jhub-values.yaml.j2 | Spawn-time seeder selects assets and reconstructs participant directories. ConfigMap source mounts and seed destinations must both be configured. |
| Worker mapping | jhub-values.yaml.j2, initial Jinja mapping | Ordered fl_workshop_client_hosts generate group_01 through group_N; node names come from hostvars[worker].ansible_fqdn. |
| Participant placement | configure_digitafrica_group_workspace | OIDC participants require exactly one recognised workshop group. Its mapping sets kubernetes.io/hostname and GROUP_ID. Administrators do not receive student placement through this hook. |
| Existing host workspace | same pre-spawn hook | /opt/digitafrica/fl-workshop is mounted read-only at /home/jovyan/digitafrica/workshop. Preserve this FL-specific behaviour. |
| Organiser documentation | docs/workshop-organiser.md | Existing sections cover responsibility boundaries, entry point, cohort preparation, resets, and participant guidance. |

## Delivery and runtime constraints

- Activation affects subsequent participant server spawns; it does not update running servers.
- Module 2 calls copy_seed_file with overwrite=false, preserving existing destination files.
- That helper sets copied files to mode 0644. Executable scripts need interpreter invocation or explicit permission handling.
- Documentation and dependency files need explicit asset mappings; SOURCE.md is not mapped by the inspected Module 2 block.
- Seed receipts show initial delivery, not runtime success or current workspace/source equivalence.
- A notebook pod's localhost is not automatically the VM host or a separate Spark container.
- Spark endpoint reachability, driver/executor callback connectivity, writable paths, dependency versions, and participant isolation require separate verification.
- ConfigMaps are suitable only for appropriately sized assets; assess notebook size and use another delivery mechanism for large datasets.

## Pending design decisions

1. Standalone Spark workshop versus a Cloud SOA module; do not assign a module number without agreement.
2. Spark runtime topology and lifecycle, including whether execution is local or distributed.
3. Notebook dependencies, supported versions, network endpoints, and writable output locations.
4. Asset directory, participant workspace, state identity, and any explicit CLI actions.
5. Workshop-specific reset scope that preserves unrelated applications, credentials, and participant work unless explicitly authorised.

## Phase 1 acceptance checklist

- [x] Clean branch created from the verified baseline.
- [x] Local runtime files preserved outside version control.
- [x] Organiser dispatch and controller pattern located.
- [x] Asset staging, state validation, and seed preservation inspected.
- [x] Inventory-derived worker placement inspected.
- [x] Constraints and unresolved design decisions recorded.
- [x] Review this record against the inspected source excerpts.
- [ ] Commit only this documentation file on the Spark branch.

Phase 2 implementation must not be described as complete until runtime and participant-access evidence exists. Regression validation must cover existing workshop activation, seeding, placement, and reset behaviour.
