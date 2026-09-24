# DIGITAfrica Advanced Federated-Learning Workshop

## Purpose

This is the advanced, skeleton-based version of the DIGITAfrica
federated-learning workshop. It uses the same protected group workspace,
local data partition, Flower server, and approved runtime as the beginner
track.

The difference is pedagogical: you will implement the key local analysis and
client-launch steps yourself.

## Workshop sequence

1. Open `01_Inspect_Local_Partition.ipynb`.
2. Complete the `TODO` cells to validate and inspect your assigned partition.
3. Discuss your local class distribution and synthetic representation with the
   organiser and other groups.
4. Wait until the organiser confirms that the Flower server is ready.
5. Open `02_Run_Federated_Client.ipynb`.
6. Complete the readiness and launch tasks, then run the client once.

## Rules for the advanced track

- Complete the skeleton in your persistent Jupyter workspace; do not edit the
  mounted workshop application or dataset.
- Use only your assigned local partition.
- Run the client-launch cell once, and only after organiser approval.
- If you become blocked, explain the error and your attempted diagnosis to the
  organiser before requesting the reference solution.
- The reference solution is released only by the organiser, when appropriate.

## Important boundaries

- Your group cannot access another group’s local partition.
- The mounted workshop application and dataset are read-only.
- Local CSV metadata remains within the group workspace.
- Federation exchanges model updates, not the raw CSV rows.
- Do not use Kubernetes commands, terminals, or direct service URLs.
