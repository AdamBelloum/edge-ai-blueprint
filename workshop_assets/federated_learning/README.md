# Federated-learning workshop application

This directory contains the versioned application source used by the
DIGITAfrica federated-learning workshop.

## Source boundary

`edge-ai-blueprint` is the sole source repository used to deploy the workshop.
Deployment tasks and Silo containers must use these committed files; they must
not clone or pull a separate application repository at runtime.

## Contents

- `server/server.py` — Flower aggregation server entry point.
- `requirements.txt` — pinned Python runtime baseline.
- `client/client.py` — repository-owned Flower Silo client for the
  deterministic synthetic-feature workflow demonstration.

## Runtime configuration

The deployment derives the number of worker groups from the local workshop
inventory. It supplies Flower server settings, including the expected client
count, through environment variables. Do not hard-code a particular number of
groups in application source.

## Excluded runtime artefacts

Do not commit virtual environments, downloaded data, generated partitions,
logs, process identifiers, credentials, or workshop release records.

## Runtime dependencies

`requirements.lock` is the workshop Python runtime baseline captured from the
verified Tier-1 Flower virtual environment:

- Python `3.13.5`
- Flower `1.36.0`

Every package is version-pinned. Deployment installs only from this file; it
does not install a floating package specification such as `flwr>=1.0.0`.
