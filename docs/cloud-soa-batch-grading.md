# Cloud Computing SOA: grading every group's work

After a Module 1 or Module 2 workshop, the organiser menu can test the work of
every participant group with the assignment's grading script, or run the TA
audit on it. Each group's work runs in its own pod on the cluster, on a copy of
the group's workspace; the workspace itself is mounted read-only. Participant
servers and files are not changed, and the results are written on the
organiser's machine.

## Running it

In the organiser menu, choose Workshops → Cloud Computing SOA → Module 1 or
Module 2, then under AFTER THE WORKSHOP:

| Entry | Action | Result per group |
|---|---|---|
| 7 Test every group's work | `cloud-module1-grade`, `cloud-module2-grade` | the grading script's points (`test_api.py`, `test_microservices.py`) |
| 8 Audit every group's work | `cloud-module1-audit`, `cloud-module2-audit` | the TA audit's findings (`audit_a1.py`, `audit_a2.py`) |

Run them before releasing the reference solutions and before a reset: a reset
deletes the workspaces. The entries grade the module's active track; when
another module is active, they ask for the track. They show what will be
graded and ask for confirmation before they start.

| Setting | Default | Meaning |
|---|---|---|
| `CLOUD_COMPUTING_SOA_MODE` | the active track | `beginner`, `intermediate` or `advanced`: the track to grade |
| `CLOUD_SOA_GRADING_GROUPS` | all groups | for example `group_03,group_07` |
| `CLOUD_SOA_GRADING_PARALLEL` | `4` | pods that run at the same time (1 to 20) |
| `CLOUD_SOA_GRADING_EGRESS` | `participant` | `none` gives the pods no network access at all (see Network) |
| `CLOUD_SOA_GRADING_IMAGE` | the JupyterHub notebook image | another image for the pods |
| `CLOUD_SOA_TA_AUDIT_DIR` | `workshop_assets/cloud-computing-soa/ta-audit` | another copy of the TA audit |
| `CLOUD_SOA_GRADING_RESULTS` | `secrets/workshops/grading` in the checkout | where the results are written |
| `DIGITAFRICA_ASSUME_YES` | `false` | `true` answers the confirmations, for the actions in scripts |

A run refuses to start while a reset is incomplete, when there are no
participant workspaces, or when the cluster runs Kubernetes older than 1.29.
A pod waits up to 2.5 minutes for the group's services; the grading script
then has 10 minutes and the audit 40. If the control plane does not answer, a
step is tried again for about five minutes before the run stops.

Only one grading run can be in the cluster at a time. When a run was cut off,
for example because the organiser's machine lost its connection, the next run
offers to remove it. A run that an organiser followed in the last 10 minutes
may still be going, so its removal always needs an answer at the terminal,
also with `DIGITAFRICA_ASSUME_YES=true`.

## Results

```text
secrets/workshops/grading/<control-plane host>/<UTC time>-module1-tests-<run>/
├── run.json        settings, image, Kubernetes version, organiser commit, checksums of the files sent
├── summary.md      one line per group
├── summary.csv
└── group_07/
    ├── tests.txt, tests.json            the grading script's output (audit.md, audit.json, audit.txt for the audit)
    ├── prepare.json                     the files graded, with checksums, and what the group changed
    ├── service.log                      the group's services
    ├── grade.json, result.json          how the grading went; the pod's state and events
    └── grader.log, prepare.log
```

The Work column compares the track's code with what the group received:

| Work | Meaning |
|---|---|
| `changed` | the group changed the track's code |
| `unchanged` | the files the group received, unchanged (the beginner code is complete and gets most points) |
| `solution` | the reference solution, for example copied after its release |
| `missing` | no Module folder, or the track's code is not there; prepare.json lists the folder's tracks |
| `too large` | the Module folder holds more than 400 MB, or more than 20,000 files and folders; not copied |

The points cover only what the grading script tests: 12 of the 45 points of
Assignment 1 and 11 of the 55 of Assignment 2. The rubric lines that need a TA
are listed in each group's tests.txt. For the audit, the summary counts FAIL,
WARN and ERROR findings; deduct per bug, not per check, and use the oral-exam
questions in audit.md (see `workshop_assets/cloud-computing-soa/ta-audit/README.md`).

The results hold the groups' code and logs. Git ignores `secrets/`, but the
folder is inside the checkout: if the checkout is in a synchronised folder
(OneDrive, Dropbox), set `CLOUD_SOA_GRADING_RESULTS` to a folder outside it.
Give the results to the TAs who grade, and delete them when the grades are
final.

## How a group is graded

```text
Pod grading-<run>-group-07
├── prepare  init container  copies the group's Module folder from its volume (read-only) into an empty home
├── service  sidecar         starts the group's services in that copy
└── grader   main container  waits for the services, runs the grading script or the audit, prints the results
```

All three containers run as the participant (uid 1000) with the notebook image
of the JupyterHub deployment:

- **prepare** copies `Cloud-Computing-SOA/Module-N` to the same path in an
  empty home, records checksums, and compares the track's code with the files
  the track delivers and with the reference solution. It also keeps a copy of
  the track's source files for the audit.
- **service** starts the services as the participant instructions do. Module 1:
  `python app.py` in the track folder. Module 2: `bash setup_local_keys.sh` if
  the track has it, then `python auth.py` in `auth_service/` (port 5001) and
  `python shortener.py` in `shortener_service/` (port 5000). Python finds the
  packages in the group's `~/.local`, read-only, and a virtual environment
  named `.venv`, `venv` or `env` in the track or Module folder is used if there
  is one. A service that stops is not restarted; service.log has its exit code.
- **grader** waits for the ports, then runs the grading script or the audit
  from the organiser's checkout, not the group's copy, and prints the results
  as one block that the organiser collects with `kubectl logs`.

The environment is that of the group's server after a restart, with the same
CPU and memory limits for the services. Packages that were installed outside
`~/.local` (or a virtual environment in the Module folder) are not there, and
services that the group started differently, from another folder or with
another command, are not found; the Outcome column then shows the ports that
were open instead. When the grading script or the audit ends without results,
the Outcome column says so; its output is in tests.txt or audit.txt.

## Isolation

| | |
|---|---|
| Group volume | mounted read-only in prepare and service only; nothing is written to it, and its ownership is not changed |
| Group code | runs only in the service container, which mounts neither the grading script, the audit, the results nor the source copy; prepare never writes through a link that the group's files contain |
| Containers | uid 1000, no privilege escalation, all capabilities dropped, the default seccomp profile; CPU and memory limits (for the services those of a participant server); size limits on the temporary volumes and on what is returned |
| Kubernetes access | no service-account token, no environment variables for the namespace's services |
| Network | no connections in; out as for participant servers, but not to the nodes or the Kubernetes API (see Network) |
| Participant servers | not touched; a pod can run while the group's server runs, on the same node |
| Cleanup | every object of a run carries the label `digitafrica.io/grading-run=<run>` and belongs to the lock ConfigMap `digitafrica-grading-run`; the run removes them at its end, also after an error or Ctrl-C, and the next run offers to remove a run that was cut off |
| TA audit | sent from the organiser's checkout in a ConfigMap that only the grader mounts, and deleted with the run |

`tests/test_cloud_soa_ta_audit.py` still keeps the audit out of all deployment
code; only `grading-local.py` may name the audit folder.

## Network

Kubernetes NetworkPolicies are firewall rules for pods. k3s enforces them with
its built-in network-policy controller, unless it was installed with
`--disable-network-policy`; this repository's k3s installation does not
disable it. The JupyterHub chart gives participant servers a policy that
allows DNS and connections to the internet, but not to private address ranges
or the cloud metadata server. That keeps them away from the other pods, but
from the nodes only while the nodes have private addresses; the production
inventory lists public ones.

The grading pods get DNS and the internet as participant servers do, but none
of: private ranges, shared address space (`100.64.0.0/10`), link-local
addresses (`169.254.0.0/16`, the cloud metadata server among them), and the
addresses of the nodes and of the Kubernetes API, which the run reads from the
cluster and records in run.json (`unreachable`). Nor do they get the
connections to JupyterHub's own hub and proxy that a participant server needs
for its login. A group's code then behaves as in its own server, for example a
URL check that contacts the URL. The grader talks to the services over
127.0.0.1 inside the pod, which the rules do not affect.
With `CLOUD_SOA_GRADING_EGRESS=none` the pods get no network at all; services
that need the internet then fail their checks.

## Module 3

Module 3 is not included. On the platform it delivers teaching files only:
participant servers have no Docker or Kubernetes, so there is nothing running
to grade. TAs grade Assignment 3 on the students' machines with
`test_microservices.py --assignment 3.1` or `3.2` and `audit_a3.py`.

## Code

| File | Runs on | Does |
|---|---|---|
| `scripts/workshops/cloud-computing-soa/grading-main.sh` | organiser machine | menu entries and actions; follows a run and removes it |
| `scripts/workshops/cloud-computing-soa/grading-local.py` | organiser machine | builds each remote step, reads its answer, writes the results |
| `scripts/workshops/cloud-computing-soa/grading-remote.py` | control plane (`run_deployment_remote`) | status, start, step and cleanup of a run |
| `scripts/workshops/cloud-computing-soa/grading-pod.py` | grading pods | prepare, serve and grade |

The grading scripts and the audit scripts have a `--json FILE` option for this.
The tests are `tests/test_cloud_soa_grading_*.py`: the pod's steps with real
services and broken variants, the control-plane steps against a fake cluster,
the organiser's flow, and the JSON reports.
