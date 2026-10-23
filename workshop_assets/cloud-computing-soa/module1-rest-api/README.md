# Cloud Computing SOA — Module 1: REST API

This is the participant-asset source for the first Cloud Computing SOA module:
a Flask URL-shortener REST API.

## Tracks

- `beginner/`: guided learning material with complete, explained code.
- `intermediate/`: TODO-based Flask implementation exercise.
- `advanced/`: the specification (`advanced/README.md`) and an `app.py` that
  holds only a few comments; participants design and write the service
  themselves.
- `solutions/`: reference implementation; not seeded until an organiser
  releases it, and only for the intermediate and advanced tracks.
- `shared/tests/`: the Assignment 1 grading script and its input data, used by
  all participant tracks.

## Grading script

`test_api.py` (in `shared/tests/`; participants find it in `tests/`) sends HTTP
requests to a running service and prints the points for each line of the
Assignment 1 rubric that can be tested this way: 12 of the 20 demo points (the
seven test functions, unique identifiers, URL validation). The remaining points
need a TA and are listed in the output. Run it from the tests folder with
`python test_api.py`, adding `--url http://HOST:PORT` for a service elsewhere;
`python -m unittest -v test_api` gives plain pass/fail output. Participants
receive the same script, so they can check their work before the demo.

The reference solution in `solutions/` gets all 12 points: identifiers come
from a base-62 counter (as short as possible, never reused), and URLs are
checked with a regular expression on POST and PUT.

## Runtime boundary

The Flask development server runs only within the participant's JupyterHub
server on `127.0.0.1:5000`. It is tested locally and is not exposed through a
shared ingress or public service.

See `SOURCE.md` for provenance and licence information.

## Beginner implementation provenance

`beginner/app.py` is adapted from the documented `Complete Final Code (example)` section in `beginner/upstream-participants-guide.md`, with explanatory comments and minor code-structure differences. The supplied file is the runnable beginner implementation; the guide explains its design and behaviour.
