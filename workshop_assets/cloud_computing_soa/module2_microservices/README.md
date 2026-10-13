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

Before starting:
- In the advanced track, implement `ensure_keys_exist()` in
  `auth_service/auth.py` before running the setup helper. Complete the remaining
  service TODOs before expecting the endpoint tests to pass.
- Use separate JupyterHub terminals for the two services and the tests.
  All commands and HTTP requests run inside the same participant server.

1. Run `bash setup_local_keys.sh`.
2. In one terminal, run `cd auth_service && python auth.py`.
3. In another terminal, run `cd shortener_service && python shortener.py`.
4. From the selected-track directory, run
   `cd ../tests && python -m unittest -v`.

The setup helper calls the authentication service's `ensure_keys_exist()`
function. The complete implementation reuses the key files when both exist;
otherwise it generates an RSA private/public key pair under `auth_service/keys/`.
The helper restricts private-key permissions and copies only `public_key.pem`
to `shortener_service/keys/`. Generated key material is ignored by Git and must
not be committed.

Both services store their application data in memory. Restarting the
authentication service clears registered users; restarting the shortener
clears URL mappings. Local JWT verification does not consult the current user
dictionary, so restarting authentication or changing a password does not by
itself invalidate an already issued token.

The tests create accounts and mappings against the running services and attempt
mapping cleanup. Use a disposable workshop session: the supplied implementation
can reassign ownership when another user submits the same URL. The ownership
test checks selected list/update/delete restrictions, not this same-URL case.
Successful `DELETE /` returns `404` under this workshop's contract.

This is an educational implementation, not a production authentication system.
Unsalted SHA-256 password hashing and Flask's debug development server are not
appropriate for production.

In the source repository, see `SOURCE.md` alongside this README for
provenance and licence information. It is not currently copied into the
JupyterHub participant workspace.
