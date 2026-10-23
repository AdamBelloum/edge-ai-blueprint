# Module 3 — Intermediate workshop

## How to use this workshop

Complete the TODOs using the practical instructions and source comments. Execute and verify your own implementation before consulting any released solution. Follow Part 3.1 before Part 3.2.

## Part 3.1 — Container virtualization

Open `containerization/`.

1. Inspect both applications and their existing requirements files. Preserve the API from the previous practical.
2. Follow the local key-preparation instructions. Use `auth_service/requirements.txt` rather than a guessed dependency list.
3. Complete the Dockerfile TODOs for both services. Provide the runtime, dependencies, application files and startup command. Hint: dependency installation before copying frequently changed application code enables useful layer caching.
4. Complete the Compose TODOs to build and run both services, publish their ports and preserve application data with volumes. Use the accompanying comments for the required runtime mounts and configuration.
5. Build and deploy your implementation. Test representative authentication and URL-shortener operations and verify access from outside the Docker host.
6. Create test data and demonstrate persistence across service restarts and `docker compose down` followed by container recreation. Do not use `down -v` for this check.
7. Check your work with the grading script, on the Docker host, from `containerization/`:
   `python3 ../../tests/test_microservices.py --assignment 3.1 --restart "docker compose down && docker compose up -d"`.
   It tests both APIs in their containers, restarts the containers with the given command and checks that the data is still there. It needs Python 3 with `requests`; add `--url` and `--auth-url` if the services do not listen on ports 5000 and 5001 of this host.
8. Explain your persistence, image compactness and build-efficiency decisions in at most one page. Do not merely describe each Dockerfile line.

## Part 3.2 — Container orchestration

Open `orchestration/`.

1. Follow the supplied Kubernetes cluster-setup tutorial: prepare one control-plane VM and two worker VMs.
2. Complete the manifest TODOs and required environment-specific values using the instructions and comments.
3. Create a Deployment for each service and run at least three replicas of one service.
4. Create Kubernetes Services for external access. Explain why the selected Service type fits your deployment.
5. Verify external access and a consistent view of stored data across the replicated service.
6. Check your work with the grading script. On the control-plane VM, from `orchestration/`:
   `python3 ../../tests/test_microservices.py --assignment 3.2 --url http://NODE_IP:SHORTENER_NODE_PORT --auth-url http://NODE_IP:AUTH_NODE_PORT --namespace YOUR_NAMESPACE`.
   It checks the nodes, Deployments and Services with kubectl and sends requests through the Services; `sudo apt-get install -y python3-requests` provides `requests`. Run it once more from your own computer, without `--namespace`, to show that the services are reachable from outside the cluster.
7. Observe request distribution and support your load-balancing deductions with examples from actual requests and responses.

Write at most half a page about Kubernetes experience and challenges, and at most half a page about load-balancing observations.

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

Demonstrate both parts with your completed implementation. Document actual deployment commands and which files belong to each part. Keep optional extensions separate. Follow Assignment 3 for report, submission and source-attribution requirements.

These entry guidelines summarize the assignment. They do not replace the detailed practical instructions or the separately supplied cluster-setup tutorial. Runtime validation by the TA is pending.
