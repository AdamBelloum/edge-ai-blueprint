# Cloud Computing SOA Module 3 — M3-05 validation

## Status and source identity

**Partially validated; M3-05 is not complete.**

Recorded HEAD: `adc1aa0`.
Branch: `feat/cloud-soa-module3-completion`.
The working tree contains uncommitted integration changes; these results
must not be interpreted as validation of a clean, committed release.

Control shell: `fs2`.
Compose rehearsal host: `ab-02.lab.uvalight.net` (x86_64).

Track names are as recorded at that HEAD. The "advanced" TODO track described
below has since been renamed `intermediate`, and a new `advanced` track (the
assignment specification, the Module 2 services and near-empty configuration
files) was added.

## Compose rehearsal

Earlier session results recorded successful beginner/reference builds,
startup, key generation and private/public separation, and all eight
shared functional tests against each implementation.
Reference persistence survived restart and container recreation.
An initial advanced TODO and replica-safety review was recorded.

These results do not establish direct external service reachability.
Shared JSON persistence must not be presented as safe concurrent or
production storage.

## Standalone bundle export

PASS at recorded HEAD:
- Unconfirmed solution export rejected; no archive created.
- Beginner and advanced: 35 mapped files plus bundle notes each.
- Solutions: 34 mapped files plus bundle notes.
- Exact mapped content, file permissions, selected-track isolation,
  prohibited secret-path exclusion, and validation-limit notice checked.
- Common PEM private-key markers checked; not a comprehensive embedded
  credential scan.
- Temporary archives removed after checks.

## Kubernetes prerequisite inspection

Read-only inspection used `/etc/rancher/k3s/k3s.yaml`, context `default`,
on `ab-01.lab.uvalight.net`.
All three nodes were Ready on k3s `v1.30.4+k3s1`.
Only local-path storage and three bound RWO PVs were observed.
Neither worker had an active NFS server or readable configured exports.

Kubernetes rehearsal is BLOCKED: no verified dedicated NFS/RWX endpoint.
Image availability, mounted shared storage, service access, replica
observations, and Kubernetes exercise cleanup remain unvalidated.
No cluster resources were changed during these checks.

## Scoped cleanup

Executed `docker compose down --timeout 20` with explicit project/file
selection for:
- `m3-beginner-1q6nksju`
- `m3-reference-6krkm3v3`

PASS: all four rehearsal containers and both project networks removed.
Images, volumes, rehearsal directories, and generated keys were retained.
Three Spark containers remained running; this is not a Spark health check.

## Post-guidance local validation

Beginner and advanced entry guides now clarify approved execution hosts,
isolated Kubernetes use, NFS/RWX prerequisites, external-access evidence,
JSON concurrency limitations, scoped cleanup, and secret handling.

PASS on the modified working tree after these README edits:
- `module3-local.sh check beginner`
- `module3-local.sh check advanced`
- `module3-local.sh check solutions`
- `git diff --check`

Map counts: 32 beginner, 32 advanced, 31 solution, 3 shared-test assets.
Each selected track plus shared tests passed 6 Python and 2 Bash syntax checks.

ConfigMap JSON estimates against the 204800-byte project budget:
- Beginner: 69848 bytes.
- Advanced: 58432 bytes.
- Solutions: 47241 bytes.
- Shared tests: 29066 bytes.

These are local estimates, not validation of actual kubectl-rendered objects.
Earlier full bundle-export checks preceded the README edits.
A focused post-edit export check passed at HEAD `8997874`:
- Beginner and advanced exports succeeded.
- Each exported README matched its updated source exactly and included
  the runtime prerequisites and safety section.
- Temporary archives were removed.

This supplements the earlier full archive checks; it does not repeat
all archive-safety assertions or establish new runtime readiness.
Integration implementation changes remained uncommitted during this check.

## Remaining acceptance work

- Complete the isolated Kubernetes rehearsal with verified image,
  storage, and network prerequisites, or formally defer that scope.
- Verify the documented service-access method; direct external access
  remains unverified.
- Finish targeted guidance checks/fixes where required.

Cross-workshop regression and integration-release acceptance are outside
this M3-05 evidence record.

## Integration closeout

Scope: Module 3 teaching-file delivery and organiser lifecycle integration.
Kubernetes exercise-runtime validation is explicitly deferred.
M3-05 remains partially validated.

Workshops are intended to operate independently from a fresh infrastructure
deployment. Broader workshop-independence testing and dependency fixes are
follow-up work, not prerequisites requiring another workshop to run first.

Local tests passed on fs2 at HEAD `af30788` with the modified working tree,
including the new, then-untracked hooks and tests:

- `python3 -m unittest discover -s tests -p 'test_cloud_module3_*.py' -v`
  — 74 tests passed.
- `python3 -m unittest discover -s tests -p 'test_openfaas_full_seed.py' -v`
  — 4 tests passed.
- `git diff --check` — passed.

Coverage includes mapped delivery, repeat-delivery preservation, source and
destination safety, solution gating, state validation, publication
confirmation, controller routing, mocked reconciliation, and rendered hooks.

The Module 5 test is a local shared-seeder compatibility check, not a
requirement to deploy or execute Module 5 before Module 3.

These results do not establish live JupyterHub participant spawns, real
ownership changes, full Helm rendering, independent clean-install success,
or Kubernetes exercise readiness. Service-access validation also remains
outstanding. No broader cross-workshop regression result is claimed.

This closeout supplements the earlier M3-05 evidence; it does not mark
the complete teaching runtime or deployment acceptance as passed.
