# Spark beginner workshop — Phase 1 baseline and integration map

## Status and scope

Phase 1 baseline inspection was reviewed and committed as 15103aa.
This correction records the recovered workshop agreement; its review and commit
remain pending. Runtime implementation and validation are separate next steps.
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
- Tracked workshop orchestration uses scripts/workshops/ (singular).

## Verified integration points

| Area | Implementation | Finding |
| --- | --- | --- |
| Entry point | scripts/workshops/organizer-main.sh | Owns CLI validation, shared menus, helper setup, and dispatch. |
| Workshop registration | organizer-main.sh | Requires menu routing and controller loading; any new explicit CLI actions also require help, parser registration, option validation, and dispatch. |
| Controller pattern | scripts/workshops/controllers/cloud_computing_soa.sh | Sourced facade delegates to a course implementation under its own workshop directory. |
| Activation safeguards | scripts/workshops/cloud-computing-soa/course-main.sh | Cloud handlers validate cohort completeness, shared activation permission, and asset readiness before patching state. These are patterns to reuse, not Spark runtime tests. |
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

## Agreed workshop design

The initial shared-cluster recommendation was superseded by the agreement to
use one organiser-managed, containerised Spark cluster per assigned group VM.
The subsequent menu clarification places Spark under a top-level Big Data
workshop, alongside Cloud Computing SOA, Introduction to AI, and Federated Learning.
Do not reopen these decisions as unresolved.

### Organiser experience

- Follow the existing course/controller architecture for Big Data and its Spark module.
- Provide preparation, readiness checks, start/stop, and scoped reset actions.
- Prepare Spark containers, datasets, notebooks, and connection configuration per group VM.
- Pin compatible Spark/PySpark versions and bound resources to each VM's capacity.
- Isolate group outputs and do not expose the Docker socket to participants.
- Provide controlled Spark application UI access for observing jobs, stages, and executors.
- Validate notebook-to-cluster connectivity, including worker-to-notebook driver callbacks.

### Participant experience — beginner-first scope

- Continue using JupyterHub on the group's assigned worker VM.
- Containers facilitate delivery; container management is not a learning objective.
  Participants are assumed to know container technology already.
- Require no participant Spark installation or container-management commands.
- Start with a very short README: workshop goal, workspace structure, each file's
  role, exercise order, and links to detailed guidance and background material.
- Use a complete guided notebook as the primary learning environment.
- Focus on DataFrames, transformations versus actions, partitions, execution,
  and interpreting results.
- Finish with an aligned Python application and a provided spark-submit command.
  Its submission mechanism must work without granting participant Docker access.
- Keep organiser container configuration outside the participant workspace.
- Advanced TODO notebooks were discussed, but the current implementation focus
  is the beginner workshop; do not expand scope without agreement.

### Interpretation and implementation boundaries

Multiple Spark worker containers on one VM demonstrate execution across Spark
processes, not distribution across physical machines. Worker count must fit the
VM's CPU and memory. Cross-machine execution is not implied by this design.

The proposed notebook name 01-spark-beginner.ipynb is a naming suggestion, not
an existing asset. No notebook or participant README has been implemented here.

## Remaining implementation choices and verification

These details implement the agreed design rather than replace it:

1. Spark module identifier, repository asset paths, and participant workspace paths.
2. Pinned container images and compatible Java, Python, Spark, and PySpark versions.
3. Per-VM worker count, resource limits, network endpoints, driver callback ports,
   and controlled application UI access.
4. Dataset choice, writable output paths, and notebook/script analysis alignment.
5. Participant-safe spark-submit mechanism and organiser lifecycle commands.
6. Scoped reset behaviour and regression protection for existing workshops.

## Phase 1 acceptance checklist

- [x] Clean branch created from the verified baseline.
- [x] Local runtime files preserved outside version control.
- [x] Organiser dispatch and controller pattern located.
- [x] Asset staging, state validation, and seed preservation inspected.
- [x] Inventory-derived worker placement inspected.
- [x] Constraints and unresolved design decisions recorded.
- [x] Review this record against the inspected source excerpts.
- [x] Commit only this documentation file on the Spark branch (15103aa).

## Agreement correction acceptance

- [x] Review the recovered agreement recorded above.
- [ ] Commit this documentation correction only.

Phase 2 implementation must not be described as complete until runtime and participant-access evidence exists. Regression validation must cover existing workshop activation, seeding, placement, and reset behaviour.
