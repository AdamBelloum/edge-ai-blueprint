# HPC staging reset

## Scope

`reset-workshop.sh` delegates HPC-owned staging cleanup to `cleanup-staging.sh`.
Both `openmp-01-basics` and `mpi-01-basics` share the same staged teaching assets
and runtime definitions. Selecting either module cleans this shared staging;
this is not selective deletion of only one module's files.

The shared workshop context selects the released inventory and groups:

- Worker group: matching allowlisted teaching files under `/opt/digitafrica/hpc`.
- Control-plane group: the three installed runtime files under
  `/opt/digitafrica/hpc-runtime`.

Only allowlisted regular files matching expected SHA-256 content, root ownership,
installation permissions, and single-link status are removed. Staging directories
are preserved. Non-allowlisted files, including legacy assets outside the current
installation allowlist, are not targeted. Modified targets, symlinks, hard links,
unsafe directory paths, or ownership/permission conflicts block cleanup.

No participant homes/PVCs, cached participant environments, accounts, credential
exports, shared host packages, images, or shared infrastructure are removed.
The helper does not stop participant servers or perform neutral reconciliation.
Removal of `digitafrica-runtime-hpc` and disabling HPC pod integration remain
responsibilities of global neutral reconciliation.

**A successful HPC helper invocation does not verify a full workshop reset.**

## Operational prerequisites

For deletion, obtain administrator approval, stop participant servers, and keep
exclusive maintenance in place: no concurrent staging, workshop publication,
application reconciliation, participant spawning, or filesystem administration.
The helper does not automatically verify or enforce these operational conditions.
A fleet-wide preflight precedes deletion; files are rechecked before unlinking.
This is not a transactional reset or protection against concurrent root changes.
A failure during execution can leave partial cleanup requiring inspection.

Use administrator SSH/become access. No Keycloak credential is requested by this
helper. Keep participant spawning paused after staging deletion: Kubernetes
resources are not reconciled by this operation.

## Commands

Run from the repository root. Read-only preflight:

```bash
scripts/workshops/hpc/cleanup-staging.sh --check
```

Authorised staging-only reset:

```bash
scripts/workshops/hpc/reset-workshop.sh \
  --runtime-only --module mpi-01-basics
```

The default manifest uses current working-tree installation sources. For an older
staged baseline, explicitly supply its full lowercase 40-character commit SHA
using `--source-revision` on either HPC helper. For example, the validated
Tier-2 staging baseline was:

```bash
scripts/workshops/hpc/cleanup-staging.sh \
  --check \
  --source-revision 75740411e0333568532a253bf9b87aed09bd0f73
```

For an authorised deletion, pass the same option to `reset-workshop.sh` after
`--runtime-only --module <module-id>`. This option is implemented in the HPC
helpers, not added to the global reset CLI.

The revision must be an available commit and an ancestor of current HEAD.
Its tracked HPC installation roles must match the current working tree.
Checksums come from pinned Git source blobs; missing sources are refused.
There is no checkout, automatic history search, restaging, force override, or
acceptance of hashes merely observed on a deployment. Inventory path, source,
and allowlist overrides are refused. A different historical installation layout
requires a separately reviewed migration rather than widening deletion scope.

## Verification and recovery

The engine verifies allowlisted files are absent after deletion. Repeating a
successful cleanup should report no changes while maintenance remains exclusive.
Empty staging directories and unrelated files may remain by design.

Do not resume participant spawning solely because cleanup succeeded. Either
complete the separately approved global reset/neutral reconciliation workflow,
or restore required assets and runtime integration through existing staging,
workshop preparation, and application reconciliation workflows. Reverify workshop
readiness before resuming. This helper does not perform recovery automatically.

## Recorded validation

- 66 HPC tests and 15 shared reset-entrypoint tests passed: 81 tests in total.
- Ansible syntax checking passed using a synthetic localhost inventory.
- Offline tests cover guards, non-target preservation, repeat safety, delegation,
  inventory scoping, failure propagation, temporary exports, and pinned revisions.
- The initial live Tier-2 current-source preflight correctly refused older staged
  content. Worker provenance and MPI helper hashes matched commit
  `75740411e0333568532a253bf9b87aed09bd0f73`.
- Pinned-source preflight passed on `tier2-worker-1`, `tier2-worker-2`, and
  `tier2-server`, with no changes.
- An authorised staging-only run through the MPI entry point completed on all
  three hosts, each reporting one changed cleanup task and no failures.
- A repeat through the OpenMP entry point completed with zero changes and no
  failures on all three hosts.

Full global reset, neutral reconciliation after this deletion, and live Tier-1
cleanup were not validated in this sprint. Live non-target content was not
independently inventoried before and after the test; preservation guards were
exercised in the offline filesystem tests.
