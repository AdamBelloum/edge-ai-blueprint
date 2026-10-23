# Cloud Computing SOA — Module 2: Microservices and JWT Authentication

This is the participant-asset source for the second Cloud Computing SOA module.
It evolves Module 1's single URL-shortener REST API into two independently
running local services:

- an authentication service that manages users and issues RS256 JSON Web Tokens;
- a URL-shortener service that validates tokens locally and enforces ownership
  of URL mappings.

## Tracks

- `beginner/`: complete, explained service implementations and guided material.
- `intermediate/`: TODO-based implementations and an assignment guide.
- `advanced/`: the specification (`advanced/README.md`) and two service files
  that hold only a few comments; participants design and write both services
  themselves. Until the solutions are released, this track does not receive
  this README or `.gitignore`, which describe the design of the other tracks.
- `solutions/`: reference implementation; not seeded until an organiser releases it.
- `shared/tests/`: the Assignment 2 grading script and its input data, used by
  all participant tracks.

## Runtime boundary

Both Flask development servers run only within an individual participant's
JupyterHub server:

- authentication service: `http://127.0.0.1:5001`
- URL-shortener service: `http://127.0.0.1:5000`

They are not exposed through a shared ingress or public Kubernetes Service.

## Local startup sequence

From the selected `beginner/`, `intermediate/`, or released `solutions/`
directory (the advanced track has no code to start; see `advanced/README.md`):

Before starting:
- In the intermediate track, implement `ensure_keys_exist()` in
  `auth_service/auth.py` before running the setup helper. Complete the remaining
  service TODOs before expecting the endpoint tests to pass.
- Use separate JupyterHub terminals for the two services and the tests.
  All commands and HTTP requests run inside the same participant server.

1. Run `bash setup_local_keys.sh`.
2. In one terminal, run `cd auth_service && python auth.py`.
3. In another terminal, run `cd shortener_service && python shortener.py`.
4. From the selected-track directory, run
   `cd ../tests && python test_microservices.py`.

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
itself invalidate an already issued token. (The reference solution keeps its
data in JSON files instead when the `DATA_DIR` environment variable is set;
Module 3 uses this.)

This is an educational implementation, not a production authentication system.
The beginner and intermediate tracks hash passwords with unsalted SHA-256 and
run Flask's debug development server; the reference solution uses salted
PBKDF2 and no debug mode. None of them is meant for production.

In the source repository, see `SOURCE.md` alongside this README for
provenance and licence information. It is not currently copied into the
JupyterHub participant workspace.

## Grading script

`test_microservices.py` (in `shared/tests/`; participants find it in `tests/`)
sends HTTP requests to both services and prints the points for each line of the
Assignment 2 rubric that can be tested this way: 11 of the 20 demo points (the
authentication service, the shortener's methods with multi-user support, and
the JWT). The remaining points need a TA and are listed in the output.
`test_ownership_isolation.py` holds the multi-user checks and is run as part of
it: a second user must not see, change or delete the first user's mappings,
also after shortening the same URL. Add `--url` and `--auth-url` for services
elsewhere; `python -m unittest -v` gives plain pass/fail output. Module 3 uses
the same script for Assignment 3.

The tests create accounts and mappings against the running services and delete
their mappings afterwards; the accounts remain until the authentication service
restarts. Use a disposable workshop session. Successful `DELETE /` returns
`404` under this workshop's contract.

The reference solution gets all 11 points. It is also the service code of the
Module 3 solution: the same files, unchanged.

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
Intermediate participants implement the existing TODOs before testing.
Advanced participants write both services from the specification in
`advanced/README.md`. In the beginner and intermediate tracks, use the
`upstream-participants-guide.md` alongside this README.
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
Module 2 is selected, mode is intermediate or advanced, and the release flag
is true. This copying rule is not an authentication boundary or a revocation
mechanism for files already delivered.

The organiser release action refuses unless Module 2 is the active module and
its intermediate or advanced track is selected, and it checks that both
reference service files are deployed.

### Documentation maintenance

Keep participant instructions in this README, provenance in `SOURCE.md`,
implementation explanations beside the relevant code, and delivery comments
beside the template logic. Changes to teaching behaviour, asset mappings,
release guards, or tests require a separate functional change and validation.
Do not include generated keys, passwords, or tokens in documentation or Git.
