#!/usr/bin/env python3
"""Prepare a pinned Node.js runtime in a home PVC; never invoke OpenFaaS."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile
from urllib.request import urlopen

MAX_BYTES = 100 * 1024 * 1024


def validate_config(config):
    version = config["version"]
    if not re.fullmatch(r"v22\.\d+\.\d+", version):
        raise ValueError("Expected an exact Node.js 22 version")
    archive = f"node-{version}-linux-x64.tar.gz"
    expected_url = f"https://nodejs.org/dist/{version}/{archive}"
    if (config["platform"] != "linux-x64" or
            config["archive"] != archive or config["url"] != expected_url):
        raise ValueError("Unexpected platform, archive or official download URL")
    if not re.fullmatch(r"[0-9a-f]{64}", config["sha256"]):
        raise ValueError("Invalid SHA256")
    if not re.fullmatch(r"\d+\.\d+\.\d+", config["npm_version"]):
        raise ValueError("Invalid npm version")


def check_binaries(directory, config):
    environment = dict(os.environ)
    environment["PATH"] = str(directory / "bin") + os.pathsep + environment.get("PATH", "")
    for executable, expected in (("node", config["version"]),
                                 ("npm", config["npm_version"])):
        result = subprocess.run(
            [str(directory / "bin" / executable), "--version"],
            env=environment, check=True, capture_output=True, text=True,
            timeout=30,
        )
        if result.stdout.strip() != expected:
            raise RuntimeError(f"Unexpected {executable} version")


def prepare(config, home, opener=urlopen):
    validate_config(config)
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("This pinned runtime supports Linux x86_64 only")
    base = Path(home) / ".local/share/digitafrica/runtime/module5-node"
    destination = base / f"node-{config['version']}-linux-x64"
    marker = destination / ".digitafrica-runtime.json"
    if destination.exists():
        if not marker.is_file() or json.loads(marker.read_text()) != config:
            raise RuntimeError("Existing runtime has no matching receipt; refusing overwrite")
        check_binaries(destination, config)
        print("[module5-node] Cached runtime validated; no download required.")
        return destination / "bin"

    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=base) as temporary:
        staging = Path(temporary)
        archive = staging / config["archive"]
        digest = hashlib.sha256()
        total = 0
        with opener(config["url"], timeout=30) as response, archive.open("wb") as output:
            # Do not accept redirects to another host or an unpinned release.
            if response.geturl() != config["url"]:
                raise RuntimeError("Unexpected archive redirect")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BYTES:
                    raise RuntimeError("Archive exceeds the 100 MiB limit")
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != config["sha256"]:
            raise RuntimeError("SHA256 mismatch; refusing extraction")

        # Extract only the official archive after verifying its pinned checksum.
        subprocess.run(
            ["tar", "--no-same-owner", "-xzf", str(archive), "-C", str(staging)],
            check=True, timeout=120,
        )
        extracted = staging / destination.name
        check_binaries(extracted, config)
        (extracted / marker.name).write_text(json.dumps(config, sort_keys=True) + "\n")
        # Never replace an existing installation, including a concurrent one.
        if destination.exists():
            raise RuntimeError("Runtime appeared during preparation; retry to validate it")
        extracted.rename(destination)
    print("[module5-node] Pinned Node.js and npm installed and validated.")
    return destination / "bin"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--delivery-enabled", choices=("true", "false"), required=True)
    args = parser.parse_args()
    if args.delivery_enabled != "true":
        print("[module5-node] Delivery disabled; preparation skipped.")
        return

    def state(name):
        path = args.state_dir / name
        return path.read_text().strip() if path.is_file() else ""

    if (state("workshop_type"), state("workshop_module")) != ("cloud-computing-soa", "module5"):
        print("[module5-node] Module 5 is not active; preparation skipped.")
        return
    if state("mode") != "beginner" or state("solutions_released") != "false":
        raise RuntimeError("Module 5 requires beginner mode and solutions_released=false")
    config = json.loads(args.config.read_text())
    binary_path = prepare(config, Path.home())
    print(f"[module5-node] Binary directory: {binary_path}")
    print("[module5-node] No OpenFaaS execution or teaching-file changes performed.")


if __name__ == "__main__":
    main()
