#!/usr/bin/env python3
"""Audit existing exports; --verify tests worker-specific SSH authentication."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess

def command(argv, timeout=15):
    return subprocess.run(
        argv, stdin=subprocess.DEVNULL, capture_output=True,
        text=True, timeout=timeout, check=False,
    )

def require(condition, reason):
    if not condition:
        raise SystemExit(json.dumps({"status": "blocked", "reason": reason}))

def classify(rc, error):
    if rc == 0:
        return "authenticated"
    if "Host key verification failed" in error or "REMOTE HOST IDENTIFICATION HAS CHANGED" in error:
        return "host_trust_failed"
    if any(s in error for s in (
        "Load key ", "Identity file ", "identity file ",
        "sign_and_send_pubkey: signing failed", "error in libcrypto",
    )):
        return "client_identity_failed"
    if rc == 255 and re.search(
        r"^workshop@[^\r\n]+: Permission denied \([^\r\n]+\)\.?$",
        error, re.MULTILINE,
    ):
        return "authentication_rejected"
    return "inconclusive"

def load(root, worker):
    folder = root / "secrets/big-data-spark-direct" / worker
    key, known = folder / "login_key", folder / "known_hosts"
    for path in (root / "secrets", folder.parent, folder, key, known):
        info = path.lstat()
        directory = path not in (key, known)
        require(
            (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            and info.st_uid == os.getuid(),
            worker + ": unsafe export type or owner",
        )
        mask = 0o077 if path in (folder, key, known) else 0o022
        require(not stat.S_IMODE(info.st_mode) & mask,
                worker + ": unsafe export permissions")
    for path in (key, known):
        require(command([
            "git", "check-ignore", "-q", "--", str(path.relative_to(root)),
        ]).returncode == 0, worker + ": export is not Git-ignored")
    lines = [s.strip() for s in known.read_text().splitlines()
             if s.strip() and not s.lstrip().startswith("#")]
    require(len(lines) == 1, worker + ": expected one pinned endpoint")
    fields = lines[0].split()
    match = re.fullmatch(r"\[([^\]]+)\]:(\d+)", fields[0]) if fields else None
    require(match is not None and len(fields) >= 3,
            worker + ": invalid known_hosts record")
    host, port = match.group(1), int(match.group(2))
    ipaddress.ip_address(host)
    require(1 <= port <= 65535, worker + ": invalid port")
    public = command(["ssh-keygen", "-y", "-P", "", "-f", str(key)])
    require(public.returncode == 0, worker + ": unusable login key")
    identity = public.stdout.split()
    require(len(identity) >= 2 and identity[0] == "ssh-ed25519",
            worker + ": expected Ed25519 login key")
    return dict(worker=worker, host=host, port=port, key=key,
                known=known, identity=tuple(identity[:2]))

def verify(source, target):
    options = {
        "BatchMode": "yes", "IdentitiesOnly": "yes", "IdentityAgent": "none",
        "CertificateFile": "none", "StrictHostKeyChecking": "yes",
        "UserKnownHostsFile": str(target["known"]),
        "GlobalKnownHostsFile": "/dev/null", "UpdateHostKeys": "no",
        "PreferredAuthentications": "publickey", "PubkeyAuthentication": "yes",
        "PasswordAuthentication": "no", "KbdInteractiveAuthentication": "no",
        "HostbasedAuthentication": "no", "GSSAPIAuthentication": "no",
        "ControlMaster": "no", "ControlPath": "none", "ControlPersist": "no",
        "ConnectTimeout": "5", "ConnectionAttempts": "1",
    }
    argv = ["ssh", "-F", "/dev/null", "-T"]
    for name, value in options.items():
        argv += ["-o", name + "=" + value]
    argv += ["-i", str(source["key"]), "-p", str(target["port"]),
             "-l", "workshop", target["host"], "true"]
    expected = ("authenticated" if source["worker"] == target["worker"]
                else "authentication_rejected")
    try:
        result = command(argv)
        observed = classify(result.returncode, result.stderr)
    except subprocess.TimeoutExpired:
        observed = "timeout"
    return dict(source=source["worker"], target=target["worker"],
                expected=expected, observed=observed, passed=observed == expected)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", nargs="+", required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    require(len(args.workers) >= 2 and len(set(args.workers)) == len(args.workers),
            "Supply at least two distinct workers")
    require(all(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", w)
                for w in args.workers), "Unsafe worker alias")
    for rc, error, expected in (
        (0, "", "authenticated"),
        (255, "workshop@host: Permission denied (publickey).", "authentication_rejected"),
        (255, "Host key verification failed.", "host_trust_failed"),
        (255, "Connection timed out", "inconclusive"),
        (255, "Load key x: error in libcrypto\nworkshop@host: Permission denied (publickey).",
         "client_identity_failed"),
        (1, "workshop@host: Permission denied (publickey).", "inconclusive"),
    ):
        require(classify(rc, error) == expected, "Classifier regression failed")
    root_result = command(["git", "rev-parse", "--show-toplevel"])
    require(root_result.returncode == 0, "Run inside the repository")
    root = Path(root_result.stdout.strip()).resolve()
    exports = [load(root, w) for w in args.workers]
    require(len({e["identity"] for e in exports}) == len(exports),
            "Different workers share a login key")
    require(len({(e["host"], e["port"]) for e in exports}) == len(exports),
            "Different workers share an endpoint")
    report = {
        "classifier_checks": 6,
        "scope": "organiser-host authentication; not notebook credential delivery",
        "exports": [{k: e[k] for k in ("worker", "host", "port")} for e in exports],
        "status": "local_audit_passed",
    }
    if args.verify:
        report["tests"] = [verify(s, t) for s in exports for t in exports]
        report["status"] = "passed" if all(t["passed"] for t in report["tests"]) else "failed"
    print(json.dumps(report, indent=2))
    return int(report["status"] == "failed")

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise SystemExit(json.dumps({
            "status": "blocked",
            "reason": "Missing, malformed or unreadable export, unavailable command, or timeout",
        }))
