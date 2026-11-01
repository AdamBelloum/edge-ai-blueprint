#!/usr/bin/env python3
"""Explicit root-run candidate asset delivery; never build or change services.

An administrator must exclude non-cooperating Docker/filesystem writers.
Maintenance confirmation is an attestation, not an enforced Docker-wide lock.
Partial staging failures retain evidence and never trigger rollback or reset.
"""
import argparse
from contextlib import contextmanager
import json
import os
import re
import sys

from teardown_directory import FLAGS, check_ancestor
from livy_candidate_delivery import protected_directory, read_delivery
from livy_candidate_stage import stage_verified_candidate

BUNDLE = re.compile(r"/var/lib/digitafrica-livy-stage-[A-Za-z0-9_-]+")


@contextmanager
def open_bundle(path):
    """Open only an existing protected temporary bundle, without following links."""
    if os.geteuid() != 0:
        raise PermissionError("Candidate delivery requires root.")
    if not isinstance(path, str) or not BUNDLE.fullmatch(path):
        raise ValueError("Expected a temporary /var/lib/digitafrica-livy-stage-* bundle.")
    descriptors = []
    try:
        fd = os.open("/", FLAGS)
        descriptors.append(fd)
        check_ancestor(fd)
        for component in ("var", "lib"):
            fd = os.open(component, FLAGS, dir_fd=fd)
            descriptors.append(fd)
            check_ancestor(fd)
        fd = os.open(path.rsplit("/", 1)[1], FLAGS, dir_fd=fd)
        descriptors.append(fd)
        protected_directory(os.fstat(fd), 0)
        yield fd
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def deliver_candidate(path, *, bundle_context=open_bundle,
                      reader=read_delivery, stage=stage_verified_candidate):
    with bundle_context(path) as fd:
        files, reviewed = reader(fd)
    return stage(files, reviewed_text_files=reviewed)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Stage verified isolated Livy candidate assets only; no build or startup.")
    parser.add_argument("bundle")
    parser.add_argument(
        "--maintenance-window-confirmed", action="store_true", required=True,
        help="Administrator confirms non-cooperating Docker/filesystem writers are excluded.")
    args = parser.parse_args(argv)
    try:
        created = deliver_candidate(args.bundle)
    except Exception as error:
        print("Candidate staging failed: " + str(error), file=sys.stderr)
        return 1
    print(json.dumps({
        "status": "candidate-assets-staged",
        "created": created,
        "runtime_readiness": "not-validated",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
