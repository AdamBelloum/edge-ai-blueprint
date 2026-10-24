# TA audit for Cloud Computing SOA Assignments 1–3

For teaching assistants only. Nothing in this folder is delivered to
participants: no Ansible task or JupyterHub seeder copies it, and
`tests/test_cloud_soa_ta_audit.py` fails if one does. For a workshop on the
platform, the organiser menu runs `audit_a1.py` and `audit_a2.py` on every
group's work in the cluster, in a container that the groups' code cannot read
(`docs/cloud-soa-batch-grading.md`).

The grading scripts in `module*/shared/tests/` give the rubric points that a
script can test, and participants run them as well. The audit scripts here go
further. They try everything the assignment asks for and much that can go
wrong (unusual input, concurrency, forged tokens, restarts, keys in images),
and report each problem with the evidence (the HTTP exchange, the file, the
Kubernetes object) and a question for the oral exam. Use them after the
grading script, to decide on deductions.

| Script | Assignment | Needs |
|---|---|---|
| `audit_a1.py` | 1: URL shortener | the running service |
| `audit_a2.py` | 2: authentication service and multi-user shortener | both running services; optionally their source folders |
| `audit_a3.py --part 3.1` | 3.1: containers | the running Compose project and the Docker CLI |
| `audit_a3.py --part 3.2` | 3.2: Kubernetes | the services' URLs and `kubectl` access to the cluster |

[`CHECKS.md`](CHECKS.md) lists every check with its severity, why it matters
and the oral-exam question.

## Requirements

Python 3.8 or newer with `requests` (`pip install requests`). Run the scripts
from this folder; they import `audit_common.py`. Part 3.1 also needs `docker`
with Compose v2 on the machine that runs the students' containers. Part 3.2
needs `kubectl` for the students' cluster, on this machine or through ssh
(`--kubectl "ssh USER@VM kubectl"`).

## Results

| Result | Meaning | What to do |
|---|---|---|
| FAIL | The submission breaks the specification or has a bug: a wrong status code, a crash, lost data, a security hole. | Grounds for a deduction. Check the evidence and ask the oral-exam question. |
| WARN | A questionable choice that the specification does not rule out, such as 404 instead of 403 for another user's mapping, or tokens that never expire. | Ask the question; deduct only if the answer does not convince. |
| INFO | Observations: the token's claims, the identifier scheme, how requests spread over the replicas. | Background for the oral exam. |
| SKIP | The check could not run; the report gives the reason (a missing option, or an earlier failure). | Usually explained by another finding. |
| ERROR | The audit itself failed, for example because the service stopped answering. | Rerun; look at the service's log. |

The exit code is 1 if a check fails and 0 otherwise. When a service does not
answer at all, `audit_a1.py` and `audit_a2.py` stop with exit code 2;
`audit_a3.py` goes on, because its container and cluster checks still apply,
and reports the problem under A3-COMPOSE-03 or A3-K8S-09. One bug can fail
several checks (a crash on broken JSON fails every check that sends broken
JSON): deduct per bug, not per check.

## Running

Every run uses its own account names and URLs, so runs do not interfere. Audit
a copy of the submission that you control (your own checkout, a test VM, the
students' laptop during the demo), never a service others depend on.

### Assignment 1

```bash
python audit_a1.py --url http://127.0.0.1:5000 --report a1-group07.md
```

The audit ends with `DELETE /`, which removes every mapping of the service.
`--quick` creates 200 identifiers instead of 1,000 and skips the search for
hash collisions (A1-ID-05).

### Assignment 2

```bash
python audit_a2.py --url http://127.0.0.1:5000 --auth-url http://127.0.0.1:5001 \
    --auth-source PATH/auth_service --shortener-source PATH/shortener_service \
    --report a2-group07.md
```

The way the shortener takes the token is detected (`Authorization: Bearer`,
the bare token, `x-access-token`); if detection fails, pass for example
`--token-header 'Authorization: Bearer {token}'`. Without the source folders,
the checks of the source code (A2-SRC) are skipped. After its own checks, the
script runs every Assignment 1 check again through the multi-user shortener,
reported as A2-METHOD-01 and so on. The audit deletes the mappings it created;
the accounts remain.

### Assignment 3.1

On the machine that runs the students' containers, with their project up:

```bash
python audit_a3.py --part 3.1 --compose-dir PATH/TO/THEIR/PROJECT \
    --url http://127.0.0.1:5000 --auth-url http://127.0.0.1:5001 \
    --allow-restart --report a3-1-group07.md
```

`--allow-restart` lets the audit run `docker compose restart`, and then
`docker compose down` followed by `up -d` (never `down -v`), to check that the
accounts and mappings survive. Without it, those two checks are skipped. Add
`--project NAME` if the students started the project with `-p NAME`. The image
checks export each image that the students built with `docker save` and read
every layer, so they also find a key that a later layer deletes.

The audit tells the shortener from the authentication service by the ports of
`--url` and `--auth-url`, or else by their names (`auth`, `users`,
`shortener`, `url` and the like; a database or proxy is neither). When it
cannot tell, for example behind an nginx proxy with services called `api` and
`accounts`, the checks that need to know are skipped with a hint: pass
`--shortener-service NAME` and `--auth-service NAME`, the names of the Compose
services (in Part 3.2, of the Deployments).

### Assignment 3.2

From a machine that reaches the node ports:

```bash
python audit_a3.py --part 3.2 --namespace THEIR_NAMESPACE \
    --url http://NODE_IP:30080 --auth-url http://NODE_IP:30081 \
    --kubectl "ssh USER@CONTROL_PLANE_IP kubectl" --allow-restart --report a3-2-group07.md
```

Make sure `kubectl` reaches the students' cluster and not yours: the report
shows the kubectl context under A3-K8S-20. `--allow-restart` runs
`kubectl rollout restart` for the Deployments of the two services.

A3-K8S-15 also looks into the volumes of a running shortener pod with
`kubectl exec`, which needs `python` in the image. A3-K8S-23 and A3-K8S-24 read
the images the Deployments use with Docker on this computer: `docker pull` for
the nodes' processor architecture, and the images the audit pulled are removed
again afterwards. Without Docker those two checks are skipped.

For both parts, also run `audit_a2.py` against the same URLs: the A3 audit
checks the deployment, the A2 audit the API.

## Using the report in the oral exam

1. Run the grading script for the rubric points, then the audit with
   `--report`.
2. Go through the FAIL findings. Each lists the requests or files that show the
   problem; reproduce one in front of the students if useful, and ask the
   question. Deduct for those that hold.
3. Use the WARN findings and their questions in the oral exam.
4. Keep the Markdown report with the grade.

`--only A2-JWT A2-MULTI` runs selected checks again, `-v` shows each check
while it runs, and `--json FILE` also writes every result, with its evidence,
to a JSON file.

## What the audit does not check

- Code quality, the report, the presentation, and who wrote the code.
- Load beyond what one computer sends (a few hundred requests).
- Details of the students' VMs, such as NFS permissions or firewalls; only
  their effect on the services.

## Changing a check

Each check is a function with a `@check` decorator in its script: the id, the
area, the title, the severity, why it matters and the oral-exam question. After
adding or changing one, run `python audit_common.py` to rewrite `CHECKS.md`.
Try a new check against a variant of the reference solution that has the
problem, and against the reference solution itself
(`module*/solutions/`), which must give no FAIL and no WARN.
