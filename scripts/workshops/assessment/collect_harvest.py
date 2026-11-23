#!/usr/bin/env python3
"""Select and copy the latest harvested exam notebook per group (worker side).

Runs as root. Everything below the PVC directory is participant-controlled, so
no path component is ever resolved through a symlink: every level is opened
with O_NOFOLLOW relative to the directory descriptor of its parent.
Prints a JSON manifest on stdout. Never modifies or deletes participant data.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile

MAX_BYTES = 50 * 1024 * 1024
PVC_RE = re.compile(r"^pvc-[^/]+_digitafrica_claim-(group-[0-9]+)---[^/]+$")
GROUP_DIR_RE = re.compile(r"^group_[0-9]+$")
STEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


def list_names(dir_fd):
    with os.scandir(dir_fd) as entries:
        return sorted(e.name for e in entries)


def open_chain(parent_fd, names):
    """Open nested directories without following symlinks; caller closes all."""
    opened = []
    cur = parent_fd
    try:
        for name in names:
            cur = os.open(name, DIR_FLAGS, dir_fd=cur)
            opened.append(cur)
    except OSError:
        for fd in opened:
            os.close(fd)
        raise
    return opened


def close_all(fds):
    for fd in fds:
        os.close(fd)


def find_candidates(storage_fd, stem, problems):
    pattern = re.compile(r"^" + re.escape(stem) + r"_([0-9]{8}T[0-9]{6})\.ipynb$")
    found = {}
    for pvc in list_names(storage_fd):
        match = PVC_RE.match(pvc)
        if not match:
            continue
        group = match.group(1).replace("-", "_")
        try:
            chain = open_chain(storage_fd, [pvc, ".assessment", "submissions"])
        except FileNotFoundError:
            continue  # no submissions area yet: nothing to collect
        except OSError as exc:
            problems.append("%s: submissions path refused (%s)" % (group, exc.strerror))
            continue
        try:
            for gdir in list_names(chain[-1]):
                if not GROUP_DIR_RE.match(gdir):
                    continue
                if gdir != group:
                    problems.append("group directory %s inside PVC of %s skipped" % (gdir, group))
                    continue
                try:
                    gchain = open_chain(chain[-1], [gdir])
                except OSError as exc:
                    problems.append("cannot open %s/%s: %s" % (group, gdir, exc.strerror))
                    continue
                try:
                    for fname in list_names(gchain[-1]):
                        m = pattern.match(fname)
                        if m:
                            found.setdefault(group, []).append(
                                {"timestamp": m.group(1), "pvc": pvc, "gdir": gdir, "fname": fname})
                finally:
                    close_all(gchain)
        finally:
            close_all(chain)
    return found


def read_candidate(storage_fd, cand, out_path):
    """Re-walk the path without following symlinks, hash (and optionally copy)."""
    chain = open_chain(storage_fd, [cand["pvc"], ".assessment", "submissions", cand["gdir"]])
    try:
        fd = os.open(cand["fname"], FILE_FLAGS, dir_fd=chain[-1])
    finally:
        close_all(chain)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError("not a regular file")
        if st.st_size > MAX_BYTES:
            raise ValueError("file too large")
        src = os.fdopen(fd, "rb")
    except Exception:
        os.close(fd)
        raise
    digest = hashlib.sha256()
    size = 0
    dst = None
    try:
        if out_path:
            dst = os.fdopen(os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600), "wb")
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError("file too large")
            digest.update(chunk)
            if dst:
                dst.write(chunk)
    except Exception:
        if dst:
            dst.close()
            dst = None
            os.unlink(out_path)
        raise
    finally:
        src.close()
        if dst:
            dst.close()
    return digest.hexdigest(), size


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True)
    ap.add_argument("--stem", required=True)
    ap.add_argument("--dry-run", action="store_true", help="select and hash only; copy nothing")
    args = ap.parse_args()
    if not STEM_RE.match(args.stem):
        sys.exit("invalid --stem")

    problems = []
    items = []
    out_dir = None
    storage_fd = os.open(args.root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        found = find_candidates(storage_fd, args.stem, problems)
        selected = []
        for group in sorted(found):
            newest = max(c["timestamp"] for c in found[group])
            top = [c for c in found[group] if c["timestamp"] == newest]
            if len(top) > 1:
                problems.append("ambiguous: %s has %d PVCs with timestamp %s; skipped" % (group, len(top), newest))
                continue
            selected.append((group, top[0]))
        if selected and not args.dry_run:
            out_dir = tempfile.mkdtemp(prefix="assessment-collect.", dir="/var/tmp")
        for group, cand in selected:
            name = "%s_%s.ipynb" % (group, cand["timestamp"])
            try:
                sha, size = read_candidate(storage_fd, cand, os.path.join(out_dir, name) if out_dir else None)
            except (OSError, ValueError) as exc:
                problems.append("%s: not collected (%s)" % (group, getattr(exc, "strerror", None) or exc))
                continue
            items.append({"group": group, "timestamp": cand["timestamp"], "name": name,
                          "sha256": sha, "size": size, "pvc": cand["pvc"]})
    finally:
        os.close(storage_fd)
    result = {"out_dir": out_dir, "items": items, "problems": problems}
    if out_dir:
        mfd = os.open(os.path.join(out_dir, "manifest.json"),
                      os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        with os.fdopen(mfd, "w") as handle:
            json.dump(result, handle)
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
