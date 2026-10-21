# Module 3 — Beginner workshop

## How to use this workshop

Use the supplied implementation. Read the practical instructions and the comments in the code and configuration files. Execute the practical and keep evidence of each required result. Follow Part 3.1 before Part 3.2.

## Part 3.1 — Container virtualization

Open `containerization/`.

1. Examine the two service Dockerfiles. Identify how they install dependencies, copy application files and start the services.
2. Examine `docker-compose.yml`. Identify the services, externally published ports and persistent data volumes.
3. Follow the local key-preparation instructions before starting the services. Use the existing `auth_service/requirements.txt` for the Python dependencies; do not substitute a guessed package list.
4. Build and deploy both services with Docker Compose.
5. Test representative authentication and URL-shortener operations using the API from the previous practical. Verify access from outside the Docker host.
6. Create test data. Show that it survives service restarts and `docker compose down` followed by container recreation. Do not use `down -v` for this test, because it removes named volumes.
7. Explain how Dockerfile command ordering and exclusion of unnecessary dependencies and files improve build efficiency and image compactness.

Record the working requests, persistence evidence and key implementation decisions. The assignment asks for a description of Part 3.1 of at most one page, not a line-by-line Dockerfile explanation.

## Part 3.2 — Container orchestration

Open `orchestration/`.

1. Follow the supplied Kubernetes cluster-setup tutorial: prepare one control-plane VM and two worker VMs.
2. Examine the supplied Kubernetes manifests and complete the environment-specific configuration required by their instructions and comments.
3. Deploy both services and expose them through Kubernetes Services.
4. Verify that at least one service has three running replicas.
5. Test access from outside the cluster and demonstrate that the replicas offer a consistent view of stored data.
6. Observe repeated requests and use your observations to reason about request distribution across replicas. Keep examples supporting your deductions.

Write at most half a page about your Kubernetes experience and challenges, and at most half a page about your load-balancing observations.

## Runtime prerequisites and safety

- Run container exercises on the organiser-approved Docker host.
  Receiving these files in JupyterHub does not imply Docker access.
- For Kubernetes, use the organiser-approved isolated lab namespace.
  Follow the cluster-setup tutorial only when provisioning dedicated lab
  VMs; do not reinstall or reconfigure an existing shared cluster.
- Before deploying Kubernetes manifests, verify the configured images
  are available to all eligible nodes and the required NFS/RWX storage
  is provisioned for this lab. Node-local RWO storage is not a substitute.
- For external-access evidence, record the client host, endpoint, and
  access method. Label SSH-tunnel results explicitly; they do not prove
  direct reachability of the published host or cluster endpoint.
- A consistent view during sequential requests is an observation, not
  proof of safe concurrent storage. Shared JSON files can suffer lost
  updates or corruption with concurrent writers. Keep replica experiments
  controlled; this storage design is not suitable for production.
- Stop Compose services using the same file and project name used at
  startup. Preserve volumes during persistence tests. Delete lab data
  only through an explicit, scoped reset.
- Remove only your lab-owned Kubernetes resources. Do not delete shared
  namespaces, storage, or other workshop resources.
- Keep generated private keys and credentials outside Git and shared
  bundles. Do not include them in reports or request evidence.

## Completion

Demonstrate the required results for both parts. Document actual deployment commands and identify the files used for each part. Keep optional extensions separate from required work. Follow Assignment 3 for report, submission and source-attribution requirements.

These entry guidelines summarize the assignment. They do not replace the detailed practical instructions or the separately supplied cluster-setup tutorial. Runtime validation by the TA is pending.
