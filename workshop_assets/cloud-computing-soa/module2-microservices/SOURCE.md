# Source and licence record

This workshop material is derived from:

- Repository: https://github.com/AdamBelloum/Tutorials
- Pinned source commit: `8879982c56276455d03b2e5e3b50c42eb1cdfbd2`
- Source path: `Distributed-Systems/cloud-computing-soa/02-microservices`
- Upstream licence: Apache License 2.0

The upstream starter and solution service code, participant guides, and test
assets are adapted for deployment through `edge-ai-blueprint`.

Runtime publication separates beginner, advanced, and reference-solution
materials. Participant workspaces receive only the selected track, and
reference solutions are released only through an organiser action.

The upstream reference material contains generated RSA key files. Those files
are intentionally excluded from this integration. Each participant workspace
generates fresh local key material at runtime; only its public verification key
is copied from the authentication-service directory to the shortener-service
directory.
