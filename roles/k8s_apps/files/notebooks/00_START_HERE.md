# DIGITAfrica Student-Driven Federated Learning Workshop

## How this workshop works

JupyterHub is the central browser gateway. When you log in as your assigned
group, your notebook kernel runs on that group’s designated client VM.

That notebook can read only the prepared local partition mounted for your group.
The shared Flower aggregation server runs separately on the central workshop VM.

## Workshop sequence

1. Open `01_Inspect_Local_Partition.ipynb`.
2. Run its cells to inspect your assigned partition and the synthetic features
   generated from it.
3. Wait until the organiser confirms that all groups are ready.
4. Open `02_Run_Federated_Client.ipynb`.
5. Run its final cell to start your group’s Flower client.

The client cell stays active while the shared federated-learning workflow runs.
It returns after the configured federation rounds have completed.

## Important boundaries

- Use only the provided JupyterLab notebooks.
- Your group cannot access another group’s local partition.
- The mounted workshop application and dataset are read-only.
- You may save notes and copies in your persistent Jupyter workspace.
- Do not use Kubernetes commands, terminals, or direct service URLs.
