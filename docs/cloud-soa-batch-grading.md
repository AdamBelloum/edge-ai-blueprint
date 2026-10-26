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
| `CLOUD_SOA_GRADING_EGRESS` | `none` | `none`: no network for the groups' code; `participant`: the internet, as from participant servers (see Network) |
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

A run's pods use the participant workspaces, so a reset could not delete them
while the run is in the cluster. The reset therefore refuses to start then,
and the grading entries remove a run that was cut off also while a reset is
incomplete.

## Results

```text
secrets/workshops/grading/<control-plane host>/<UTC time>-module1-tests-<run>/
├── run.json        settings, image, Kubernetes version, organiser commit, checksums of the files sent
├── summary.md      one line per group
├── summary.csv
└── group_07/
    ├── tests.txt, tests.json            the grading script's output (audit.md, audit.json, audit.txt for the audit)
    ├── code/                            the graded code, as the services ran it: app.py, or auth_service/auth.py and shortener_service/shortener.py
    ├── prepare.json                     the files graded, with checksums, and what the group changed
    ├── service.log                      the group's services
    ├── grade.json, result.json          how the grading went, the hosts that the code tried to reach; the pod's state and events
    └── grader.log, prepare.log, dns.log
```

A run that fails or is stopped with Ctrl-C still writes the summary of the
groups graded so far. When every group was graded but the run cannot be
removed from the cluster, for example because a pod hangs in deletion, the
results are complete, and the next grading entry offers to remove the run.

The Work column compares the track's code with what the group received. A
cohort may have received another version than the organiser's checkout has, so
every version counts: the checkout's, those in its Git history (also under the
module folders' earlier names, but not from another track), and the one in the
ConfigMaps that the cluster seeds participant servers with (run.json,
`published`). The same holds for the reference solution.

| Work | Meaning |
|---|---|
| `changed` | the group changed the track's code |
| `unchanged` | the files the group received, unchanged (the beginner code is complete and gets most points) |
| `solution` | the reference solution, for example copied after its release |
| `missing` | no Module folder, or the track's code is not there; prepare.json lists the folder's tracks |
| `too large` | the Module folder holds more than 400 MB, or more than 20,000 files and folders; not graded |

The Network use column lists the hosts that a group's code tried to reach,
with how often. Below the table, summary.md lists the groups
whose code tried to reach other hosts, and the command that grades them again
with network (see Network).

The points cover only what the grading script tests: 12 of the 45 points of
Assignment 1 and 11 of the 55 of Assignment 2. The rubric lines that need a TA
are listed in each group's tests.txt. For the audit, the summary counts FAIL,
WARN and ERROR findings; deduct per bug, not per check, and use the oral-exam
questions in audit.md (see `workshop_assets/cloud-computing-soa/ta-audit/README.md`).

The results hold the graded code, at most 1 MB per file, and the logs of the
groups' services, but not the rest of the Module folders, which a reset
deletes. Git ignores `secrets/`, but the folder is inside the checkout: if the
checkout is in a synchronised folder (OneDrive, Dropbox), set
`CLOUD_SOA_GRADING_RESULTS` to a folder outside it. Give the results to the
TAs who grade, and delete them when the grades are final.

## How a group is graded

```text
Pod grading-<run>-group-07
├── prepare  init container  waits for the pod's network rules, copies the group's Module folder from its volume (read-only) into an empty home
├── dns      sidecar         without network only: refuses every name lookup at once and writes down the name
├── service  sidecar         starts the group's services in that copy
└── grader   main container  waits for the services, runs the grading script or the audit, prints the results
```

All containers run as the participant (uid 1000) with the notebook image of
the JupyterHub deployment:

- **prepare** waits until the pod's network rules are in force (see Network),
  then copies `Cloud-Computing-SOA/Module-N` to the same path in an
  empty home, records checksums, and compares the track's code in the copy
  with the files the track delivers and with the reference solution. It also
  keeps a copy of the track's source files for the audit, and of the code
  files for the results; links are not followed.
- **dns**, in pods without network, answers on 127.0.0.1:53, the pod's only
  name server: it refuses every lookup at once and writes down the name (see
  Network). The pod lets uid 1000 open ports from 53 up (the sysctl
  `net.ipv4.ip_unprivileged_port_start`), and the services start only once dns
  answers.
- **service** starts the services as the participant instructions do. Module 1:
  `python app.py` in the track folder. Module 2: `bash setup_local_keys.sh` if
  the track has it, for at most 60 s, then `python auth.py` in `auth_service/`
  (port 5001) and `python shortener.py` in `shortener_service/` (port 5000).
  What the setup script leaves running is stopped first, such as an `auth.py`
  without a `__main__` guard, which serves as soon as the script imports it and
  would hold port 5001. Python finds the packages in the group's `~/.local`,
  read-only, and a virtual environment named `.venv`, `venv` or `env` in the
  track or Module folder is used if there is one. A service that stops is not
  restarted; service.log has its exit code.
- **grader** waits until the service container has started the services and
  their ports answer, then runs the grading script or the audit from the
  organiser's checkout, not the group's copy, and prints the results as one
  block that the organiser collects with `kubectl logs`.

The environment is that of the group's server after a restart, with the same
CPU and memory limits for the services. Packages that were installed outside
`~/.local` (or a virtual environment in the Module folder) are not there, and
services that the group started differently, from another folder or with
another command, are not found; the Outcome column then shows the ports that
were open instead. When the grading script or the audit ends without results,
the Outcome column says so; its output is in tests.txt or audit.txt. The
group's code runs in the service container as the same user as serve, so a
group that sets out to can still have something other than the code kept with
its results answer the grader.

## Isolation

| | |
|---|---|
| Group volume | mounted read-only in prepare and service only; nothing is written to it, and its ownership is not changed |
| Group code | runs only in the service container, which mounts neither the grading script, the audit, the results nor the source copy; prepare never writes through a link that the group's files contain; the grader reads the group's network-use files, but follows no link and opens no pipe there; the names that dns writes down are out of the group's reach |
| Containers | uid 1000, no privilege escalation, all capabilities dropped, the default seccomp profile; CPU and memory limits (for the services those of a participant server); size limits on the temporary volumes and on what is returned |
| Kubernetes access | no service-account token, no environment variables for the namespace's services |
| Network | no connections in; none out, unless the organiser asks for the internet (see Network) |
| Participant servers | not touched; a pod can run while the group's server runs, on the same node |
| Cleanup | every object of a run carries the label `digitafrica.io/grading-run=<run>` and belongs to the lock ConfigMap `digitafrica-grading-run`; the run removes them at its end, also after an error or Ctrl-C, and the next run offers to remove a run that was cut off; while a pod cannot be removed, the run's NetworkPolicy and lock stay too, so that the pod keeps its network rules and the next run offers to remove it again |
| TA audit | sent from the organiser's checkout in a ConfigMap that only the grader mounts, and deleted with the run |

`tests/test_cloud_soa_ta_audit.py` still keeps the audit out of all deployment
code; only `grading-local.py` may name the audit folder.

## Network

By default the groups' code has no network: it cannot reach the internet or
anything in the cluster, with the exceptions under Limits. The grader still
reaches the services, over 127.0.0.1 inside the pod.

Neither assignment needs the network. Assignment 1 asks for a regular
expression to check URLs, and Assignment 2 allows keeping users and mappings in
memory. The grading scripts and the audit talk only to the services and never
follow a redirect, and the services find their packages in the group's
workspace. The reference solutions and the delivered beginner code get the
same points with and without network, and the reference solutions the same
audit findings. Without network, a group's result depends on its code only,
not on how other websites answer at the time of grading, and grading leaves no
trace outside the pod, such as test accounts in a database that a group runs
elsewhere.

How the pods are kept offline:

- The run's NetworkPolicy `grading-<run>` allows no connections in or out.
  Kubernetes NetworkPolicies are firewall rules for pods; k3s enforces them with
  its built-in network-policy controller, unless it was installed with
  `--disable-network-policy`, which this repository's installation does not do.
- A new pod is without its rules for a moment. prepare therefore waits until
  they are in force, that is until neither the Kubernetes API nor the kubelet
  on the pod's node answers any more, before it copies the group's code. If
  they are still not in force after a minute, the group is not graded and its
  code never runs; on a cluster that does not enforce NetworkPolicies, no group
  is graded.
- Name lookups go to 127.0.0.1, the pod's only name server, where its dns
  container refuses each one at once and writes down the name. At the cluster
  DNS, blocked lookups can take up to 5 seconds each, and a service that looks
  up names could run out of time.

Code that contacts other hosts fails its checks without network. A URL check
that looks the host up, for example, rejects every URL, also the ones that the
grading script expects to be accepted, and a service that keeps its users in a
database elsewhere cannot reach it. Such a group gets in its own server points
that it does not get here. To show which groups that concerns, the pod writes
down what the group's code tries to reach:

- the dns container: every name that is looked up, by any library or program,
  such as dnspython for a `mongodb+srv://` address, or libpq for PostgreSQL;
- a start-up hook in every Python process of the group's code (`sitecustomize`,
  through `PYTHONPATH`): the names that it looks up and the addresses that it
  connects to, from Python's audit events, at most 1000 lines per process.

Neither blocks anything, and both leave out the pod itself. The summary lists
these hosts under Network use, and the command that grades those groups again
with network, for comparison. Not recorded are connections to an address
rather than a name by programs other than Python, and with network, lookups
that Python does not report: the dns container runs only without network.

### Grading with network

`CLOUD_SOA_GRADING_EGRESS=participant` gives the pods DNS and the internet, as
participant servers have them, for example to grade one group again whose code
needs it:

```bash
CLOUD_SOA_GRADING_EGRESS=participant CLOUD_SOA_GRADING_GROUPS=group_07 \
  scripts/workshops/organizer-main.sh cloud-module1-grade
```

JupyterHub's policy for participant servers blocks private address ranges and
the cloud metadata server. That keeps the servers away from the other pods,
but from the nodes only while the nodes have private addresses; the production
inventory lists public ones. The grading pods therefore block more: private
ranges, shared address space (`100.64.0.0/10`), link-local addresses
(`169.254.0.0/16`, the cloud metadata server among them), and the addresses of
the nodes and of the Kubernetes API, which the run reads from the cluster and
records in run.json (`unreachable`). Nor do they get the connections to
JupyterHub's hub and proxy that a participant server needs for its login.
Other machines on the internet, including those near the nodes, stay reachable,
as they are from participant servers. So do addresses that the cluster does
not show, such as a public address that is translated to a node's private one,
or a load balancer in front of the Kubernetes API: check `unreachable` in
run.json after the first run with network.

### Limits

Without network, two kinds of connection still get through, for participant
servers too; they need fixes on the nodes, not in the grading:

- NetworkPolicies on this single-stack cluster filter IPv4. Where pods have
  IPv6 link-local addresses (`fe80::`, see `/proc/net/if_inet6` in a pod), a
  pod can reach the other pods on its node and the node itself over IPv6;
  ip6tables rules that drop IPv6 from the pod bridge would stop that.
- k3s's network-policy controller lets pods reach their own node on ports
  30000 to 32767 (the NodePort range), so a program that listens on such a port
  of the node stays reachable.

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
