# Module 3 — Advanced workshop

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
7. Explain your persistence, image compactness and build-efficiency decisions in at most one page. Do not merely describe each Dockerfile line.

## Part 3.2 — Container orchestration

Open `orchestration/`.

1. Follow the supplied Kubernetes cluster-setup tutorial: prepare one control-plane VM and two worker VMs.
2. Complete the manifest TODOs and required environment-specific values using the instructions and comments.
3. Create a Deployment for each service and run at least three replicas of one service.
4. Create Kubernetes Services for external access. Explain why the selected Service type fits your deployment.
5. Verify external access and a consistent view of stored data across the replicated service.
6. Observe request distribution and support your load-balancing deductions with examples from actual requests and responses.

Write at most half a page about Kubernetes experience and challenges, and at most half a page about load-balancing observations.

## Completion

Demonstrate both parts with your completed implementation. Document actual deployment commands and which files belong to each part. Keep optional extensions separate. Follow Assignment 3 for report, submission and source-attribution requirements.

These entry guidelines summarize the assignment. They do not replace the detailed practical instructions or the separately supplied cluster-setup tutorial. Runtime validation by the TA is pending.
