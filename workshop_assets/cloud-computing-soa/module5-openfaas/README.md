# Module 5 — Serverless Functions with OpenFaaS

## Status

**Beginner workshop under development; not yet validated or ready for delivery.**

This module is being authored in the Tutorials repository. Integration into
`edge-ai-blueprint`, publication, and activation are separate later phases.
Authoring does not change the current infrastructure or active workshop.

The beginner material will be the complete reference implementation. An aligned
advanced TODO version will be derived later.

## Learning objectives

After completing the validated workshop, participants should be able to:

- Explain HTTP request → OpenFaaS gateway → function → response, and distinguish
  the function developer's responsibilities from the platform provider's.
- Invoke a prepared function and inspect HTTP status, headers, and JSON data.
- Implement input validation and predictable successful and error responses.
- Follow a controlled source → build → registry push → deployment workflow.
- Distinguish changing request data from changing deployed function code.
- Process deterministic weather data and handle external-service failures in an
  optional live-data extension.
- Generate bounded local traffic, interpret verified metrics, and clean up only
  their assigned exercise resources.

Serverless does not mean that servers disappear: the provider manages the runtime
infrastructure. Cold starts may occur when an instance starts; they do not occur
before every invocation. Scaling, scale-to-zero, queues, billing, and operator
behaviour depend on the platform, edition, and configuration. JavaScript
`async/await` is not queued asynchronous FaaS invocation. These features are not
required exercises in this workshop.

## Participant journey

The intended validated workshop begins with participants as developers in an
organiser-prepared, isolated lab per participant or group. Participants will run
complete guided build, push, deploy, invoke, update, and cleanup steps themselves.
Installing Kubernetes, OpenFaaS, or monitoring is
not part of the mandatory beginner path.

A shared environment may be considered in a later advanced workshop for different
learning objectives, including ownership, permissions, and collaboration.

| Existing pre-live draft | Current executable coverage | Remaining delivery work |
|---|---|---|
| `beginner/01-explore-and-invoke.ipynb` | Offline source/configuration exploration and synthetic JSON/HTML response inspection; live Python invocation cells disabled by default. | Validated invocation access and response contract; curl exercise. |
| `beginner/02-develop-and-deploy.ipynb` | Offline source/test editing in temporary copies, candidate manifests and overwrite protection; guided retained-workspace editing and Node.js test commands. | Rehearsal of the terminal exercise in the participant environment; runnable participant build/push/deploy/readiness/update workflow. |
| `beginner/03-data-and-observability.ipynb` | Offline weather fixture and guided synthetic observation interpretation; retained weather-copy and additional unit-test instructions; live invocation and traffic disabled by default. | Rehearsal of the terminal exercise in the participant environment; validated deployment prerequisite, monitoring exercise, optional external-service failure handling, and scoped cleanup. |

**All three notebooks exist as pre-live authoring drafts, not complete workshop
deliverables.** Their default Python paths have regression coverage. Live cells
remain unvalidated; monitoring, external weather access, and cleanup are not
implemented. Synthetic observations are teaching examples, not measurements.

Open notebooks with the Python kernel started in `beginner/`. Current offline
cells use the Python standard library. The authoring tests executed cells directly
in Python, not through Jupyter; rendering, kernel integration, and browser behaviour
remain to be checked. Configuration is reused without printing credentials.
Each completed practical step must provide its purpose, execution location,
runnable action, expected result, verification checkpoint, and recovery guidance.

Workshop duration is pending a timed reference rehearsal. No tested duration is
currently available.

## Existing material and planned deliverables

Existing assets:

- [Legacy participant guide](participants-guide-new.md): retained for learning-outcome
  comparison, not an approved runnable path. It includes installation, build,
  runtime, permissions, and monitoring assumptions that require correction.
- [Existing lecture slides](docs/05-serverless-DA.pdf): retained source material;
  conceptual corrections and alignment with greeting/weather exercises are pending.
- `images/`: existing illustrations, with asset provenance still to be reviewed.

Implemented authoring assets:

- `examples/greeting/handler.js`: POST greeting handler with input validation.
- `examples/greeting/handler.test.js`: 15 handler unit tests.
- `examples/greeting/package.json`: dependency-free `npm test` entry point.
- `examples/weather/handler.js`: deterministic POST weather-summary handler.
- `examples/weather/handler.test.js`: 33 handler unit tests.
- `examples/weather/package.json`: dependency-free `npm test` entry point.
- `fixtures/weather-sample.json`: synthetic teaching input, not a real observation.
- `beginner/`: three pre-live notebook drafts described above.
- `config/lab.example.json`: offline template; live execution is rejected.
- `config/.gitignore`: excludes organiser-supplied `*.local.json` configuration in this directory.
- `.gitignore`: excludes participant-generated `workspace/` source copies and build artefacts from Git.
- `helpers/lab_config.py`: configuration validation and live-execution safeguard.
- `helpers/invoke.py`: bounded HTTP invocation, redirect refusal, inspectable HTTP errors, and no automatic retries; authentication support remains unresolved.
- `helpers/traffic.py`: sequential configured traffic, status counts, and client latency aggregates; transport failures stop execution.
- `helpers/manifests.py`: offline owned-function candidate rendering and exclusive file creation; template revision is recorded, not enforced.
- `tests/test_*.py`: 37 passing Python regression tests covering helpers, the three default offline notebook paths, and mocked invocation/traffic wiring.

Remaining delivery work:

- Complete the notebook exercises and validate the participant lifecycle, including source updates, build, push, deployment, readiness, invocation, monitoring, and scoped cleanup.
- Adopt exact platform/template versions and compatible manifests only after the execution contract and permission boundaries are tested.
- Add `organizers-guide.md` covering reference setup, access, preparation, and readiness.
- Add `docs/slide-corrections.md` and `docs/validation-report.md` with corrections, exact versions, evidence, resource observations, and limitations.

No organiser guide exists yet. The direct HTTP-wrapper baseline is available in
`tests/http-wrapper/`; image-build, gateway/runtime, and participant-isolation
validation remain pending. The legacy guide remains during drafting until its
relevant learning outcomes are covered.

### Offline Python regression tests

From this module directory:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The reported authoring run used Python 3.12.12 and passed 37 tests. Notebook tests
execute default code cells with invocation/network hooks blocked; Notebook 2 and
3 tests also block external-command hooks. Notebook files are checked for unchanged
contents and empty saved outputs. These mocks are regression safeguards, not an
OS-level sandbox or proof that arbitrary notebook code cannot access a network.
The separate JavaScript handler and direct-wrapper evidence is recorded below;
this Python command does not run those tests or validate CLI manifest acceptance.

Two additional tests enable Notebook 1 and 3 live switches only in compiled
in-memory copies, using signature-checked invocation/traffic mocks and the
real response class. They check call arguments and response handling without
contacting a gateway or changing notebook files. Configuration and responses
are mocked; these checks do not establish authentication, readiness, registry
access, isolation, or live platform behaviour.

### Participant working copies and local tests

Notebooks 2 and 3 now provide guided Bash-terminal instructions in addition to
Python cells. Run their terminal commands from the module directory `05-openfaas/`
in JupyterLab on the notebook host. These Markdown instructions are not executed
by notebook Run All or by the Python regression suite.

- Notebook 2 copies the greeting into `workspace/greeting/`, expects 15 baseline
  tests, changes the greeting response, demonstrates three expected test failures,
  then aligns the response expectations and expects all 15 tests to pass.
- Notebook 3 copies weather into `workspace/weather/`, expects 33 baseline tests,
  and supplies one additional deterministic test, for an expected total of 34.
  Keeping this directory depth preserves the test's relative fixture path.
- Working copies are retained and ignored by Git. Existing copies must be
  inspected rather than overwritten. Git ignore is not backup or secret storage.
- A later build manifest must reference the edited working copy, not the
  renderer's default `examples/` source. Changing an image tag alone neither
  builds nor deploys changed code.

The latest authoring runs passed all 37 Python regression tests. They did not
execute these terminal instructions, the greeting failure/recovery sequence, or
Notebook 3's added participant test. Earlier reference-handler and direct-wrapper
results below remain separate evidence, not a rehearsal of the new exercises.
Participant-environment testing and VM/platform validation are deferred to a
separate sprint; no deployment or activation is implied by these additions.

## Starting environment and responsibilities

### Participants

Participants need basic familiarity with HTTP/JSON and JavaScript, plus the ability
to run guided Python cells and Bash commands. The organiser will prepare JupyterLab
with a Python kernel, `faas-cli`, `curl`, Git, CA certificates, and the required
Python packages. The retained-workspace exercises in Notebooks 2 and 3
require organiser-supplied Node.js 22 and npm on the notebook host. Their
dependency-free handler tests require no participant `npm install`. Exact tool
versions and the supported Node.js function runtime must be pinned and tested
before delivery; do not reuse an end-of-life runtime. Apptainer remains an
authoring test method, not the selected participant runtime.

The planned execution environment is Linux with Bash in JupyterLab. Linux/amd64 is
the initial reference target, not a claim of tested compatibility. Other host or
image architectures require separate validation. The participant's laptop only
needs a browser compatible with the prepared JupyterLab service; native macOS or
Windows installation is not required. Exact browser versions remain to be tested.

Notebook cells and notebook terminals run on the notebook host, not on the
participant's laptop. In a notebook command, `localhost` means the notebook host;
in a laptop browser, it means the laptop. The organiser must supply reachable
notebook and browser routes instead of assuming they are interchangeable.

### Organisers

Organisers prepare the reference platform, registry and protected builder, deploy
initial functions, distribute configuration through an appropriate protected
channel, verify readiness, and provide monitoring access. They retain platform
administration and infrastructure-cleanup responsibilities.

Participant access must be confined to the assigned disposable lab and registry
repositories. Participants must not receive shared-platform administrator
credentials, infrastructure-host Docker socket access, platform-admin kubeconfigs,
or unrestricted registry credentials. Any administrative capability within the
isolated lab must be documented explicitly.

The isolation boundary, image-building capability, registry permissions, and scoped
cleanup must be validated. Function-name prefixes alone are not authorisation.

## Per-group VM reference specification — provisional

The organiser provisions one disposable VM per group. JupyterLab and the
group's OpenFaaS lab run inside that VM. Participants do not install the platform.

The following is an initial engineering recommendation for reference rehearsal,
not a measured minimum, optimal configuration, or validated capacity guarantee.

| Item | Reference specification |
|---|---|
| Operating system | Ubuntu Server 24.04 LTS; record the exact image and updates used during rehearsal. |
| Architecture | Linux/amd64 (x86_64); use matching CLI binaries and function images. |
| CPU | 4 vCPUs per group VM. |
| Memory | 8 GiB RAM per group VM. |
| Disk | 80 GiB SSD-backed disk per group VM; monitor free space and image/build-cache growth. |
| Notebook environment | One JupyterLab session shared by the group, with a Python kernel and Bash terminal. |
| Initial workload | One image build at a time per VM, small exercise functions, and bounded request load. |
| Administration | Organiser sudo/root access for provisioning; participant sudo/root and container-daemon access are not assumed. |
| Networking | Organiser-provided access routes and enforced cross-group restrictions; required download, registry, and runtime connectivity must be tested. |

This budget must accommodate the selected Kubernetes/OpenFaaS installation,
JupyterLab, the protected builder, and exercise monitoring. Their exact versions,
resource limits, registry placement, and privilege model remain S2 decisions.

For cohort planning, multiply the per-VM allocation by the number of simultaneous
groups, then budget shared services and infrastructure overhead separately.
These allocations do not guarantee host capacity, especially with CPU
overcommitment or simultaneous builds.

Before delivery, rehearse a complete lab lifecycle and measure peak memory,
CPU use, build duration, disk growth, and function responsiveness. Adjust the
specification and record the evidence. Other operating systems or architectures
require separate validation.

## Indicative infrastructure recommendation

**The beginner workshop uses isolated labs. The shared profile below is retained
only as an indicative alternative; it is not a sizing recommendation for the
selected beginner model.** Per-lab resources, concurrency, and total cohort capacity
must be estimated separately and validated through rehearsal.

The following is an **unmeasured planning profile** for a dedicated small shared
pilot with **two simultaneous participant/group sessions**, small functions,
lightweight monitoring, and serial image builds. It is not a vendor minimum,
benchmark result, or guarantee of cohort capacity.

| Component | Initial planning recommendation | Assumptions |
|---|---|---|
| Shared lab budget | 8 vCPUs, 16 GiB RAM, 80 GiB available disk | Kubernetes/OpenFaaS, small functions, monitoring, and one build at a time; budget unrelated workloads separately. |
| Notebook session | 1 vCPU and 2 GiB RAM per session | Included in the shared total if colocated; not a dedicated image-building budget. |
| Image builder | One concurrent build initially | Protected build submission; explicit CPU, memory, and ephemeral-storage limits; measure peaks before increasing concurrency. |
| Function execution | One replica per exercise function initially | Use tested requests/limits and supported configuration; do not assume scale-to-zero or unrestricted scaling. |
| Registry | Reachable compatible image registry | Verify edition-specific access support; account for retained images and build-cache growth. |
| Monitoring | Prometheus; Grafana optional initially | Expose only the access needed for the exercises; verify metric names and dashboard compatibility. |

A multi-node topology is optional. Physical placement does not determine the
learning sequence. Isolated labs per participant and larger cohorts require their
own provisioning, security model, and sizing. Pilot observations will refine this
profile after the reference rehearsal.

The reference setup must document and verify:

- Kubernetes distribution/version, OpenFaaS edition/release/chart settings,
  CLI version, template revision, Node.js runtime, and image architecture.
- A protected build mechanism and registry reachable by both builder and runtime.
- Notebook/browser access to gateway and monitoring, DNS resolution, trusted TLS
  where applicable, and appropriate network restrictions.
- Image/template download routes during preparation; optional outbound access to
  the selected weather provider only for the live-data extension.
- Safe credential storage outside Git, notebooks, function images, and fixtures.
  Build/deployment credentials must not be disclosed in outputs or diagnostics.

The deterministic core weather exercise must work without an external weather API.

## Execution contract — pending S2

The selected reference topology is one organiser-provisioned, disposable Linux
VM per group, with JupyterLab running inside that group's VM. Participants execute
build, push, and deploy commands from this JupyterLab environment. The lab VM is
the intended infrastructure isolation boundary; it is not yet a validated
security boundary.

Organisers prepare the lab infrastructure before participant access. The
Kubernetes/OpenFaaS installation, builder implementation and privileges, registry
permissions, network restrictions, and credential distribution remain pending.
Participant build access must not expose shared-infrastructure Docker sockets or
administrator credentials. Any administrative capability inside the disposable
lab must be explicitly documented.

Executable deployment cells cannot be finalised until this complete path and
negative cross-group access tests have been documented and validated.

S2 must resolve:

1. Exact platform edition, versions, CLI, template, runtime, and handler contract.
2. Participant identity, assigned function names, allowed operations, and enforced
   ownership boundaries, including negative cross-participant tests.
3. Protected source submission, build, push, deploy, readiness, update, and cleanup.
4. Matching manifests, registry repository names, and versioned image tags.
5. Configuration distribution, invocation access, monitoring routes, and verified
   invocation/error/duration metrics.

Organiser-mediated build/deployment is not the selected beginner workflow.
Organisers prepare the isolated labs; participants perform the function lifecycle.
The selected implementation must support this distinction without granting access
to the shared infrastructure.

## Inspected reference candidates — not yet validated

The following candidates have been inspected upstream. They are not an approved
or platform-validated version set. The standalone Node.js authoring runtime
and direct HTTP wrapper described below have been executed. The template image
build, watchdog, and OpenFaaS platform have not been validated.

| Component | Candidate | Evidence and limitations |
|---|---|---|
| OpenFaaS CLI | `0.18.16` | Linux/amd64 release binary checksum verified locally; `version` and `build --help` executed. Image build, push, and deployment remain unvalidated. |
| Node.js template | `node22` from `openfaas/templates`, commit `262e6a608a3f987bcbe3322d1543b44e0e4282dc` | Greeting build context prepared with the verified CLI; copied handler matched source. Image build remains unvalidated; image tags and dependency resolution remain mutable. |
| OpenFaaS chart | `15.0.13` from `openfaas/faas-netes`, commit `f97de9fc1314bad45848f7e0bfaadb69710615a6` | CE selection and monitoring templates inspected; chart not rendered or deployed. |

Published SHA-256 for the CLI release asset named `faas-cli`:
`16f82d999d92ada11c3abb5ab4be32207fc99b83463672227a9ea57c0cf36299`.
The Linux/amd64 release binary was downloaded into the user cache and matched
this checksum before execution. `faas-cli version` reported version `0.18.16`
and commit `9e9b014aaf03cae10b49edf7a093e6ddfb7ea903`.
`faas-cli build --help` executed successfully and confirmed that `--shrinkwrap`
only writes files into `./build/`. No image build, registry authentication,
push, deployment, or protected-builder access was performed. This verifies
the local CLI candidate, not the complete participant lifecycle or platform.

The planned beginner sequence uses separate `faas-cli build`, `faas-cli push`,
and `faas-cli deploy` commands against the same manifest, followed by readiness
checks and invocation. Explicit image versions will distinguish code updates.
`--shrinkwrap` prepares a build context; it does not build an image.

Before adopting these candidates, resolve CE distribution terms for the intended
institution-run workshop, registry access restrictions, VM and network isolation,
notebook/browser routes, supported Kubernetes and Docker versions, image digests,
dependency locking, and meaningful tests. Then rehearse the complete lifecycle
in a disposable reference lab. No installation is required on the authoring host.

### Greeting build-context preparation

The verified CLI `0.18.16` prepared a greeting context using `build --shrinkwrap`
and `--disable-stack-pull` with the exact template revision recorded above.
The generated handler matched `examples/greeting/handler.js` byte-for-byte.
The context included the handler tests and function package configuration.

The generated Dockerfile:
- Uses `ghcr.io/openfaas/of-watchdog:0.12.5` and `node:22-alpine` as mutable
  image tags, with Linux/amd64 as the default target platform.
- Runs `npm i` for both wrapper and function dependencies.
- Includes a function-level `npm test` build step, not yet executed in an image
  build. The outer wrapper package has a placeholder test script.
- Configures the watchdog to forward HTTP requests to the Node.js wrapper.

The generated wrapper context contains no dependency lockfile. Its dependency
resolution is therefore not established by the separately locked direct-wrapper
tests. Image digests, dependency locking, and build-time test execution remain
validation requirements.

This check used temporary storage and a non-routable placeholder image name.
It did not build an image, use a container daemon, authenticate, push, or deploy.
Docker and BuildKit commands were absent from the authoring host's PATH; Podman
was present but was not exercised. The protected participant builder remains
an unresolved execution-contract requirement.

### Build and push execution contract

Source inspection at CLI commit
`9e9b014aaf03cae10b49edf7a093e6ddfb7ea903` established that:
- The standard local build path executes `docker build` and checks the
  command's exit status.
- The separate push path executes `docker push`. It requires the built image
  to be accessible through the Docker environment used for push.
- The push execution helper terminates the CLI on command failure.
- A remote-builder branch exists, but its availability, permissions, and
  compatibility with the planned separate build/push sequence are unvalidated.
- Buildx references occur in the separate publish implementation; they do not
  establish that the standard local build path invokes Buildx.

A local failure-propagation probe used the checksum-verified CLI and a temporary
`docker` stub. The stub was invoked for the expected image and deliberately
returned exit status `23`; `faas-cli push` returned exit status `1`.
This confirms that the tested CLI reports push-command failure, without
preserving the original command exit code.

The probe did not contact a registry, use credentials, access a container
daemon, build an image, or deploy a function. Successful registry push remains
unvalidated. Podman compatibility and protected-builder access also remain
unvalidated.

Notebook push checkpoints must check command failure and must not treat
printed progress messages alone as evidence of registry availability.
The disposable reference lab must validate the complete build/push path,
registry permissions, and image retrieval by the function runtime.

### CE adoption blockers — source inspection

At faas-netes revision `f97de9fc1314bad45848f7e0bfaadb69710615a6`,
chart `15.0.13` selects CE provider image `ghcr.io/openfaas/faas-netes:0.18.17`.
The pinned README identifies controller mode as the only CE operating mode;
the legacy participant guide's CE/operator instructions are not reusable as-is.

Both deployment and update handlers call `isAnonymous`, which attempts an
anonymous registry manifest HEAD request and rejects failures with a public-image
restriction message. Function Docker-config secret handling exists separately,
but does not bypass this check. The inspected validation code contains no
explicit localhost exception, despite a comment mentioning local registry testing.
Registry reachability and the distributed image's behaviour remain untested.

Chart-level `imagePullSecrets` applies to chart-installed deployments, not
automatically to participant function deployments. The previously suggested
`faasnetes.imagePullSecrets` setting was not substantiated.

The pinned repository LICENSE assigns OpenFaaS Ltd/Alex Ellis contributions to
the CE EULA and third-party contributions to MIT; it is not an Apache-only licence.

The referenced [CE EULA](https://github.com/openfaas/faas/blob/master/EULA.md)
was retrieved from mutable master on 2026-10-18. Retrieved SHA-256:
`1b81c9ee4a2789b6b7618469f2b92ab444f5d3a30cc20f8d121b32deed90c26a`.
This records inspected text, not the EULA version applicable to the candidate image.

The retrieved terms do not explicitly resolve the institution-run, multi-VM
teaching model. They include organisational acceptance, commercial-installation
limits, and prior-commercial-licensee restrictions. Before selecting CE, establish
the applicable terms and obtain institutional approval and any necessary written
vendor clarification. Do not assume that individual group VMs create separate
licensees or restart an evaluation allowance.

CE remains an unapproved candidate. Do not publish participant images publicly,
bypass validation, or provision CE merely to work around these unresolved gates.

## Validation and release gate

### Local greeting-handler baseline

Implementation checkpoint: `95bbd65a2a5c74f5e0b7acc6626fa8648b5ae22a`.

On the Linux/x86_64 authoring host, `npm test` passed all 15 tests with no failures,
skips, or TODOs using Apptainer `1.4.0-1.el8`, Node.js `v22.23.3`, and npm `10.9.9`.
The runtime was executed with a read-only source bind and required neither a
host Node.js installation nor Docker.

Source image: `docker.io/library/node:22-alpine`, resolved to the verified
Linux/amd64 OCI manifest digest:
`sha256:2c752226d477b4a886378baa95b9af252be59301b725fdb0b7e15208131505a8`.

Local converted SIF SHA-256:
`aa8a5e9435fa2ae5c1c837f626a5fd2b1300029cfdb250aedd912a117871dadf`.
This identifies the recorded local file; independent conversions may produce
different SIF checksums.

Tests cover successful greetings, trimming, the 80-unit JavaScript string-length
boundary, invalid bodies/names, and GET rejection with an Allow header. They use a
context stub, not the actual OpenFaaS HTTP wrapper. Separate direct-wrapper
observations are recorded below. Container builds, watchdog/gateway invocation,
and participant isolation remain unvalidated. The test-image pin does not pin the template's build images or
dependency ranges. Apptainer is an authoring test method, not a selected
participant runtime or function-image builder.

### Local weather-handler baseline

All 33 weather unit tests passed using the recorded Apptainer `1.4.0-1.el8`
runtime, Node.js `v22.23.3`, and npm `10.9.9`. The recorded SIF checksum and
Linux/x64 runtime were verified before execution with a read-only module bind.
The greeting suite also passed all 15 tests. Both suites had zero failures,
cancellations, skips, or TODOs.

The weather handler processes supplied `city`, `temperature_c`, and `condition`
fields without external requests. Tests cover the synthetic fixture, trimming,
text-length boundaries, input preservation, numeric temperatures, invalid
bodies/fields, JSON response headers, and GET/PUT/DELETE rejection.

Temperature validation requires a finite number, not meteorological plausibility.
Non-finite-number cases test the handler directly; they are not valid JSON inputs.

This subsection records context-stub unit validation only. Separate weather
HTTP-wrapper observations are recorded below. Image builds, watchdog/gateway
invocation, deployment, and isolation remain unvalidated.

### Direct HTTP-wrapper observations

The unmodified `node22/index.js` from template revision
`262e6a608a3f987bcbe3322d1543b44e0e4282dc` was executed with the greeting handler
in an external scratch directory using the recorded Apptainer/Node.js runtime.
Dependencies resolved to Express `5.3.0` and body-parser `2.3.0`.

The scratch dependency lockfile SHA-256 was
`86c9d89afa68de7e64c5408caf2808656d452c5ce6b5236d62925cab10feb5ee`.
The lockfile is preserved in `tests/http-wrapper/package-lock.json` for
the authoring test only; it is not integrated into the function-image build.

A test-only interception bound the server to loopback on an automatically
assigned port without modifying the wrapper source. Seven HTTP observations
matched expectations in both default mode and explicit `NODE_ENV=production`:

- Valid JSON returned 200 with the expected JSON greeting.
- An invalid name returned 400 with `invalid_name`.
- A JSON array and plain text returned 400 with `expected_json_object`.
- GET returned 405 with JSON and `Allow: POST`.
- A URL-encoded form containing `name=Ada` was accepted with 200.
- Malformed JSON returned 400 with HTML before the handler ran.

In default mode, the malformed-JSON response included parser stack details.
Production mode replaced those client-facing details with `Bad Request`, but the
parser diagnostic and submitted malformed body still appeared in server logs.

These are observations, not approval of a JSON-only request contract or uniformly
JSON error responses. Request media-type policy and parser-error handling remain
execution-contract decisions. Production mode alone does not resolve those gaps.
The stale `node20` startup label does not identify the runtime, and the logged
port was not the actual port used by this test.

The repeatable baseline is preserved in `tests/http-wrapper/`. Its `index.js`
and `package.json` are unmodified upstream files from the recorded template
revision; `LICENSE` preserves their upstream MIT notice. This does not assign a
licence to other module assets.

From this module directory, run:

    bash tests/http-wrapper/run.sh /absolute/path/to/node22.sif

The runner requires Bash, Apptainer, standard Linux utilities, and an existing
Linux/x86_64 Node.js `v22.23.3` SIF. It prints the image checksum rather than
enforcing an image-digest pin. It uses `npm ci --ignore-scripts` with the preserved
lockfile in temporary storage, requiring access to the locked npm package URLs.
It copies the current repository greeting handler, runs all seven observations
in development and production modes, and removes temporary files on exit.
Both modes passed with the recorded reference image.

The probe also asserts development parser-error exposure and production
suppression of parser stack details in HTTP responses. Server-side diagnostics
are not automatically asserted. The wrapper source remains unchanged; a
test-only interception forces an ephemeral loopback listener.

This baseline does not exercise the watchdog, gateway, image build, deployment,
or participant isolation. Form acceptance and HTML parser errors are regression
observations, not approval of the final workshop request/error contract.

### Weather HTTP-wrapper observations

The weather probe passed all nine observations in both development and production
modes using the same upstream wrapper, locked dependencies, and verified reference
SIF as the greeting baseline. The greeting probe was rerun and passed all seven
observations in each mode: 32 HTTP checks passed across both exercises and modes.

Weather observations:
- Valid JSON returned 200 with the expected fields and summary.
- Invalid city, string temperature, and invalid condition returned 400 with their
  respective JSON validation errors.
- A JSON array and plain text returned 400 with `expected_json_object`.
- GET returned 405 with JSON and `Allow: POST`.
- URL-encoded form input returned 400 with `invalid_temperature`; the parsed
  temperature was a string. This does not establish a JSON-only media-type policy.
- Malformed JSON returned 400 with HTML before handler execution. Development
  exposed parser details in the response; production returned `Bad Request`.
  Parser diagnostics and the malformed body remained visible in server output
  in both modes. Server-side diagnostic content is observed, not asserted.

From this module directory, run either exercise:

    bash tests/http-wrapper/run.sh /absolute/path/to/node22.sif greeting
    bash tests/http-wrapper/run.sh /absolute/path/to/node22.sif weather

Omitting the exercise retains the original greeting default. The runner copies
the selected handler and probe into temporary storage; upstream wrapper sources
and the greeting probe are unchanged. The weather probe uses inline synthetic
HTTP inputs rather than loading the fixture file.

These are direct loopback wrapper tests, not OpenFaaS image-build, watchdog,
gateway, deployment, or participant-isolation validation.

### Delivery gate

Before delivery, a fresh reference rehearsal must complete all three notebooks and
check response semantics, invalid inputs, external-failure handling, bounded load,
scoped cleanup, and participant capability boundaries. Record exact versions,
commands, results, resource observations, and unresolved issues. Static notebook
checks and default offline execution tests do not establish live platform
compatibility or complete learning-outcome coverage.

No live OpenFaaS execution or end-to-end workshop validation has been performed in
this authoring sprint. No current platform deployment or activation is implied.
Advanced notebooks, production integration, required autoscaling/scale-to-zero,
queued invocation, and URL-shortener exercises are outside this sprint.

## Licensing and provenance — unresolved

The repository [LICENSE](../../../LICENSE) contains Apache License 2.0, while the
[root README](../../../README.md) states MIT for code and CC BY 4.0 for documentation.
This discrepancy must be resolved with the repository maintainer before publication;
this module does not infer or introduce a licence assignment for individual assets.
Review slide/image provenance and retain applicable attribution and licence notices.

Modification notice: this README has been revised for the beginner-first OpenFaaS
workshop authoring sprint, replacing the previous incomplete navigation and
prerequisites. The legacy guide, slides, and images are unchanged.
