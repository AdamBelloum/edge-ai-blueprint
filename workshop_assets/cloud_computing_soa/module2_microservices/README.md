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

## Teaching and organiser guidelines

### Learning progression

1. Identify the responsibilities of the authentication and shortener services.
2. Follow registration and login through to issuance of an RS256 JWT.
3. Distinguish token signature verification from encryption and user lookup.
4. Exercise protected management routes and public redirects.
5. Compare authentication failures with ownership-based authorization failures.
6. Explain what the supplied tests cover and which security properties remain
   untested.

Beginner participants use the completed code and its explanatory comments.
Advanced participants implement the existing TODOs before testing.
Use the selected track's `upstream-participants-guide.md` alongside this README.
Reference solutions support comparison after explicit organiser release; they
are not a production-security baseline.

### Environment preparation

Use a Python environment with the dependencies in the module's
`requirements.lock` installed. In the participant workspace, that file is at
the Module-2 root, alongside this README, rather than inside a teaching track.
Run the services and tests inside the same participant server: a browser or
terminal on another machine has a different localhost.

### Activation and workspace delivery

Infrastructure deployment publishes the assets; organiser activation selects
the workshop module and teaching mode. Activation does not start Flask or
restart existing participant servers. The spawn-time seeder delivers assets
under `/home/jovyan/Cloud-Computing-SOA/Module-2`.

The seeder copies the selected teaching track and shared tests while preserving
existing participant files. A later asset update is therefore not a guarantee
that an existing workspace will receive revised files. Verify delivery using
the repository's deployment and workspace checks; do not delete participant
work merely to refresh documentation.

Reference code is copied into a separate `solutions/` directory only when
Module 2 is selected, mode is advanced, and the release flag is true. This
copying rule is not an authentication boundary or a revocation mechanism for
files already delivered.

Before using the Module 2 release action, verify that Module 2 is active.
The current organiser action checks workshop type and advanced mode, but does
not check `workshop_module`; its solution asset check covers only the reference
authentication file. These are known follow-up defects, not fixed by this
documentation update. Status text also still mentions `app.py`, although this
module uses `auth_service/auth.py` and `shortener_service/shortener.py`.

### Documentation maintenance

Keep participant instructions in this README, provenance in `SOURCE.md`,
implementation explanations beside the relevant code, and delivery comments
beside the template logic. Changes to teaching behaviour, asset mappings,
release guards, or tests require a separate functional change and validation.
Do not include generated keys, passwords, or tokens in documentation or Git.
