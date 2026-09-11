# Workflow-demo Silo client

The client reads `image,label` CSV partitions. It **does not open image files**:
the image value is only a stable row identifier for deterministic synthetic
feature generation.

The model is a small NumPy softmax classifier trained through Flower FedAvg.
Its output demonstrates container-to-server connectivity, client participation,
aggregation, and per-round evaluation. It is not a validated cassava disease
classifier and must not be presented as one.

Required environment variables:

- `FLOWER_SERVER_ADDRESS` — Flower server address as reachable from the Silo.
- `CLIENT_DATA_PATH` — mounted path to the group's `train.csv`.

Deployment also supplies `GROUP_ID`, `NUM_CLASSES`, `SYNTHETIC_FEATURE_DIM`,
`SYNTHETIC_SEED`, `LEARNING_RATE`, and `LOCAL_EPOCHS`.
