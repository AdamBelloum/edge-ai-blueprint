# Workshop assets

This folder is the single source of the teaching material for every workshop:
notebooks, exercise code, tests, datasets and the small runtimes that Ansible
deploys for a workshop. Deployment code reads from here; do not keep copies of
these files inside Ansible roles. (The legacy Tier-0 roles, which are not part
of the current workshop menus, still carry their own sample notebooks.)

## Layout

```text
workshop_assets/
└── <workshop-id>/                  workshop_type used by the organiser scripts
    ├── <module-id>[-<topic>]/      workshop_module, optionally followed by a topic
    │   ├── beginner/               guided track
    │   ├── intermediate/           TODO track, where a module has three levels
    │   ├── advanced/               exercise track: TODO, or the specification
    │   ├── solutions/              reference solutions, released after the workshop
    │   └── shared/                 files several tracks use, for example tests
    ├── runtime/                    deployed to hosts by Ansible, not to participants
    └── ta-audit/                   tools for teaching assistants, never deployed
```

Rules:

- **Folder names are the identifiers used at run time.** `<workshop-id>` is the
  `workshop_type` and `<module-id>` the `workshop_module` that the organiser
  scripts write to the `digitafrica-workshop-state` ConfigMap. Numbered modules
  add a topic (`module2-microservices`); others use the identifier alone
  (`spark`, `openmp-01-basics`).
- **A module only has the tracks it actually offers.** Track folders are named
  `beginner`, `intermediate`, `advanced` and `solutions`. Most modules have two
  levels, `beginner` and `advanced` (TODO exercises). Cloud Computing SOA
  Modules 1–3 have three: `beginner` (complete code), `intermediate` (TODO
  exercises) and `advanced` (the assignment specification, with files that
  hold only a few comments; Module 3 also gives the Module 2 services).
- **The repository layout is not what participants see.** Ansible copies files
  to fixed staging paths on the central server, and JupyterHub copies them into
  fixed folders in each participant's home. Moving a file here only requires
  updating the Ansible source path; `tests/test_workshop_asset_paths.py` fails
  when a source path no longer exists.

## Catalogue

### Workshops, tracks and status

| Workshop | Module | Beginner | Intermediate | Advanced | Solutions | Status |
|---|---|:-:|:-:|:-:|:-:|---|
| Introduction to AI | Module 1 – Symbolic AI | – | – | – | – | One notebook, no tracks |
| | Module 2 – Foundations of ML | ✓ | – | ✓ | ✓ | Available |
| | Module 3 – Deep learning (2 notebooks) | ✓ | – | ✓ | ✓ | Available |
| Federated Learning | single module (Flower) | ✓ | – | ✓ | ✓ | Available; the organiser also starts the Flower server |
| Cloud Computing SOA | Module 1 – REST API | ✓ | ✓ | ✓ | ✓ | Available |
| | Module 2 – Microservices and JWT | ✓ | ✓ | ✓ | ✓ | Available |
| | Module 3 – Containerization and orchestration | ✓ | ✓ | ✓ | ✓ | Teaching files only; exercise runtime not validated |
| | Module 4 | – | – | – | – | Does not exist |
| | Module 5 – OpenFaaS | ✓ | – | – | – | Offline rehearsal only; live readiness not validated, publication blocked |
| Big Data | Spark | ✓ | – | planned | planned | Beginner pilot; advanced and solutions reserved for a future sprint |
| HPC | OpenMP basics | ✓ | – | – | – | Beginner only, no solution release; toolchain not yet version-locked |

Solutions are released only after the workshop, and only for the tracks in
which participants write the code themselves: advanced, and in Cloud Computing
SOA Modules 1–3 also intermediate. Status
follows the organiser menu and action descriptions (October 2026); update this
table when a module changes. Spark and HPC run on x86_64 only.

### Folders

| Workshop (`workshop_type`) | Module (`workshop_module`) | Folder | Participant folder |
|---|---|---|---|
| `introduction-to-ai` | `module1` | `introduction-to-ai/module1-symbolic-ai/` | `~/Introduction-to-AI/Module-1/` |
| | `module2` | `introduction-to-ai/module2-foundations-of-ml/` | `~/Introduction-to-AI/Module-2/` |
| | `module3` | `introduction-to-ai/module3-deep-learning/` | `~/Introduction-to-AI/Module-3/` |
| `federated-learning` | – | `federated-learning/` | `~/digitafrica/` (advanced: `advanced/`, solutions: `reference-solutions/`) |
| `cloud-computing-soa` | `module1` | `cloud-computing-soa/module1-rest-api/` | `~/Cloud-Computing-SOA/Module-1/` |
| | `module2` | `cloud-computing-soa/module2-microservices/` | `~/Cloud-Computing-SOA/Module-2/` |
| | `module3` | `cloud-computing-soa/module3-containerization-orchestration/` | `~/Cloud-Computing-SOA/Module-3/` |
| | `module5` | `cloud-computing-soa/module5-openfaas/` | `~/Cloud-Computing-SOA/Module-5/` |
| `big-data` | `spark` | `big-data/spark/` | `~/Big-Data/Spark/` |
| `hpc` | `openmp-01-basics` | `hpc/openmp-01-basics/` | `~/HPC/` |

Cloud Computing SOA Modules 1–3 also have a `shared/tests/` folder that is
delivered with the selected track.

Course-specific notes:

- **Introduction to AI Module 1** is published by
  `scripts/workshops/introduction-to-ai/module1.sh` from the notebook named in
  `workshop-release.env` (`INTRODUCTION_TO_AI_MODULE1_SOURCE_FILE`), not by
  Ansible.
- **Federated Learning** has one module, so its tracks sit directly in the
  workshop folder. `federated-learning/runtime/` holds the Flower server and
  client and their locked requirements; Ansible copies the whole folder to the
  central server and the workers.
- **Cloud Computing SOA**: `cloud-computing-soa/ta-audit/` holds the TA audit
  scripts for Assignments 1–3. They test a submission far more thoroughly than
  the grading scripts in `shared/tests/`, report each problem with its evidence
  and suggest oral-exam questions (see its `README.md`). The folder is not a
  module and is never deployed: deployment code reads only the `module*`
  folders, which `tests/test_cloud_soa_ta_audit.py` checks.
- **Big Data**: `big-data/spark/docker-compose.yml` is a legacy file and is not
  delivered to participants.
- **HPC**: the folder names under `hpc/openmp-01-basics/` are copied unchanged
  into participants' homes, so they keep their numbered names. Participants get
  both exercise folders.
  `hpc/runtime/environment.yml` is the toolchain that Ansible stages.

## How material reaches participants

1. Ansible stages the files. Application reconciliation
   (`scripts/workshops/organizer-main.sh reconcile-applications`) copies the
   Introduction to AI, Federated Learning and Cloud Computing SOA tracks to
   `/opt/digitafrica/k8s-notebooks/` on the central server and creates
   ConfigMaps from them. Federated Learning uses the top-level `beginner/`,
   `advanced/` and `solutions/` folders there; the other workshops use
   `<workshop-id>/<module-id>/`. The `spark-prepare` and `hpc-prepare` actions
   copy the Big Data and HPC files to `/opt/digitafrica/big-data/spark` and
   `/opt/digitafrica/hpc` on the workers, which are mounted into participant
   servers.
2. The organiser publishes a module and chooses the track. This sets
   `workshop_type`, `workshop_module`, `mode` (`beginner`, `intermediate` or
   `advanced`, where the module offers it) and
   `solutions_released` in the `digitafrica-workshop-state` ConfigMap. Only one
   module is active at a time.
3. When a participant server starts, JupyterHub copies the active track into
   the participant folder listed above.
4. Solutions are released only after the workshop, for the advanced track (in
   Cloud Computing SOA Modules 1–3 also the intermediate track), with the
   module's `release-solutions` action. This sets
   `solutions_released`; the next server start adds the solutions folder.

## Related code

| What | Where |
|---|---|
| Organiser menus and actions | `scripts/workshops/organizer-main.sh`, `scripts/workshops/<workshop-id>/` |
| Staging to the central server and ConfigMaps | `roles/k8s_apps/tasks/install.yml`, `cloud-soa-module3-assets.yml`, `openfaas-assets.yml` |
| Copying into participant homes | `roles/k8s_apps/templates/jhub-values.yaml.j2`, `roles/k8s_apps/templates/workshop-hooks/` |
| Federated Learning runtime | `roles/fl_workshop_*` |
| Big Data and HPC staging | `roles/big_data_workspace`, `roles/hpc_workspace`, `roles/hpc_runtime`, `playbooks/prepare-*.yml` |

## Adding a module

1. Create `<workshop-id>/<module-id>-<topic>/` with the track folders it offers.
2. Add the staging tasks with `src: "{{ playbook_dir }}/../workshop_assets/..."`
   and a destination under `/opt/digitafrica/k8s-notebooks/<workshop-id>/<module-id>/`.
3. Add the seeding logic and organiser actions, following an existing module of
   the same workshop.
4. Add a row to the catalogue above and run the tests.
