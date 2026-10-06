# Cloud Computing SOA — Module 2: Microservices and JWT Authentication

This is the participant-asset source for the second Cloud Computing SOA module.
It evolves Module 1's single URL-shortener REST API into two independently
running local services:

- an authentication service that manages users and issues RS256 JSON Web Tokens;
- a URL-shortener service that validates tokens locally and enforces ownership
  of URL mappings.

## Tracks

- `beginner/`: complete, explained service implementations and guided material.
- `advanced/`: TODO-based implementations and an advanced assignment guide.
- `solutions/`: reference implementation; not seeded until an organiser releases it.
- `shared/tests/`: local verification assets used by both participant tracks.

## Runtime boundary

Both Flask development servers run only within an individual participant's
JupyterHub server:

- authentication service: `http://127.0.0.1:5001`
- URL-shortener service: `http://127.0.0.1:5000`

They are not exposed through a shared ingress or public Kubernetes Service.

## Local startup sequence

From the selected `beginner/`, `advanced/`, or released `solutions/` directory:

1. Run `bash setup_local_keys.sh`.
2. In one terminal, run `cd auth_service && python auth.py`.
3. In another terminal, run `cd shortener_service && python shortener.py`.
4. From the selected-track directory, run
   `cd ../tests && python -m unittest -v`.

The authentication service creates a fresh RSA private/public key pair under
`auth_service/keys/`. The setup helper copies only `public_key.pem` to
`shortener_service/keys/`. Generated key material is ignored by Git and must
not be committed.

See `SOURCE.md` for provenance and licence information.
