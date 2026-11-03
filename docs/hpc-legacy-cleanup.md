# Reviewed legacy HPC staging cleanup

## Scope

The existing HPC cleanup/reset path now combines the current installation
allowlist with a cleanup-only legacy allowlist in
`scripts/workshops/hpc/build-cleanup-manifests.py`.

The legacy entries are relative to `/opt/digitafrica/hpc` on released worker
hosts only:

| Path | SHA-256 | Mode |
| --- | --- | --- |
| `openmp-01-basics/01-beginner/hello.c` | `b8f984c4119afc76f8cc30dd9e25df4f32446e31454f9485c4d7930276c4cb5c` | `0644` |
| `openmp-01-basics/02-intermediate/pi_serial.c` | `d59fd3cdbaba2e5a65f85894930c64fe0a1bae8b478b70f2d7949a0cc6ecf654` | `0644` |

Trusted source bytes are retained under `workshop_assets/hpc/`, with matching
hashes documented in `workshop_assets/hpc/PROVENANCE.md`. These files remain
excluded from the current installation role: cleanup does not restage them.

## Safety and source revisions

The builder refuses legacy source bytes that differ from the fixed reviewed
hashes. With an explicit source revision, it reads the legacy Git blobs from
that revision and still requires those same hashes. Existing ancestor and
installation-role compatibility checks remain in force. Missing or unrecognised
legacy source blobs fail closed; there is no historical auto-discovery or
acceptance of observed remote hashes.

Current and legacy entries share one worker manifest and the existing fleet
preflight before deletion. The deletion engine is unchanged: it requires regular,
single-link files, root ownership/group, expected permissions, and matching
content. Its staging-directory checks and no-follow descriptor handling remain
in force. Duplicate current/legacy paths are refused.

Already absent targets are safe to retry. Directories and unrelated files remain.
No recursive directory deletion is introduced.

## Operation

Existing HPC reset delegation automatically includes these legacy entries.
The existing `cleanup-staging.sh --check` and `--execute` modes include them too;
there is no additional legacy-only command or unguarded deletion path. Select
the intended deployment context using the existing workshop context workflow.

Before executing, stop participant servers and ensure exclusive administrator
maintenance: no concurrent staging, reconciliation, publication, spawning, or
filesystem administration. The staging helper does not automatically verify
these operational prerequisites.

Staging cleanup does not remove participant homes, identities, credentials,
ConfigMaps, shared services, or persistent-volume backing directories. It does
not by itself authorize global cleanup completion. Repository source assets
are preserved.

## Regression coverage

Legacy manifest tests cover exact paths/hashes, cleanup-only status, worker
scope, altered or symlinked sources, and duplicate entries. Disposable filesystem
tests cover check-only operation, successful deletion, safe repetition, unrelated
file/directory preservation, and modified content, links, modes, or ownership
expectation conflicts. Source-revision tests cover trusted historical bytes,
unrecognised historical bytes, and missing legacy Git blobs.
