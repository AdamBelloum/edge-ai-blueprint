#!/usr/bin/env python3
"""Verify staged submissions and place them in the organiser collection directory.

Input:  <staging>/<host>/manifest.json plus the notebooks it lists
        (produced by playbooks/collect-assessment-submissions.yml)
Output: <dest>/<group>_<workshop>_<module-dir>_<YYYYMMDD>.ipynb
        (_<HHMM>, then _<HHMM>_<N>, only when the name is taken by different content)

Dates and times are UTC: harvest timestamps come from utcnow() in assessment_tools.py.
Only the latest submission per group is considered. Entries that fail verification
are reported and skipped; nothing is deleted anywhere. Notebook content is never printed.
Exit status: 0 clean, 3 finished with problems, 1 fatal error.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import stat
import sys
import tempfile

MAX_BYTES = 50 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
GROUP_RE = re.compile(r"^group_[0-9]+$")
TS_RE = re.compile(r"^[0-9]{8}T[0-9]{6}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
WORKSHOP_RE = re.compile(r"^[a-z0-9-]+$")
MODULE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def clean(text, limit=300):
    return re.sub(r"[^\x20-\x7e]", "?", str(text))[:limit]


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def valid_timestamp(ts):
    try:
        datetime.datetime.strptime(ts, "%Y%m%dT%H%M%S")
    except ValueError:
        return False
    return True


def open_regular(path):
    """Open read-only: no symlink at the final component, never blocks on a FIFO,
    and only a regular file is accepted. Returns (fd, fstat result)."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError("not a regular file")
    except BaseException:
        os.close(fd)
        raise
    return fd, st


def read_regular(path, limit):
    """Read a regular file (see open_regular) up to a size limit."""
    fd, st = open_regular(path)
    try:
        if st.st_size > limit:
            raise ValueError("file too large")
        with os.fdopen(fd, "rb") as handle:
            fd = None
            data = handle.read(limit + 1)
    finally:
        if fd is not None:
            os.close(fd)
    if len(data) > limit:
        raise ValueError("file too large")
    return data


def ensure_private(path):
    """Set mode 0600 on an existing regular file via its descriptor.
    Returns True if the mode had to be changed."""
    fd, st = open_regular(path)
    try:
        if stat.S_IMODE(st.st_mode) != 0o600:
            os.fchmod(fd, 0o600)
            return True
        return False
    finally:
        os.close(fd)


def verify_item(hdir, host, item, problems, failed):
    try:
        group, ts, name = item["group"], item["timestamp"], item["name"]
        sha, size = item["sha256"], item["size"]
    except (KeyError, TypeError):
        problems.append("%s: malformed manifest entry" % host)
        return None
    if not (isinstance(group, str) and GROUP_RE.match(group)
            and isinstance(ts, str) and TS_RE.match(ts) and valid_timestamp(ts)
            and name == "%s_%s.ipynb" % (group, ts)
            and isinstance(sha, str) and SHA_RE.match(sha)
            and is_int(size) and size > 0):
        problems.append("%s: manifest entry has unexpected values" % host)
        return None

    def fail(reason):
        failed.add(group)
        problems.append("%s/%s: not collected (%s)" % (host, group, reason))

    try:
        data = read_regular(os.path.join(hdir, name), MAX_BYTES)
    except (OSError, ValueError) as exc:
        fail("cannot read staged file: %s" % clean(exc))
        return None
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha:
        fail("checksum or size mismatch")
        return None
    try:
        nb = json.loads(data)
        valid = (isinstance(nb, dict) and is_int(nb.get("nbformat"))
                 and isinstance(nb.get("cells"), list))
    except ValueError:
        valid = False
    if not valid:
        fail("not a valid notebook")
        return None
    return {"group": group, "timestamp": ts, "sha256": sha, "host": host, "data": data}


def load_candidates(staging, problems):
    candidates, failed = [], set()
    for host in sorted(os.listdir(staging)):
        hdir = os.path.join(staging, host)
        if not HOST_RE.match(host) or os.path.islink(hdir) or not os.path.isdir(hdir):
            problems.append("ignored unexpected staging entry %s" % clean(host))
            continue
        mpath = os.path.join(hdir, "manifest.json")
        if not os.path.lexists(mpath):
            continue
        try:
            manifest = json.loads(read_regular(mpath, MAX_MANIFEST_BYTES))
            items = manifest["items"]
            helper_problems = manifest.get("problems", [])
            if not isinstance(items, list) or not isinstance(helper_problems, list):
                raise ValueError("unexpected manifest structure")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            problems.append("%s: unusable manifest (%s)" % (host, clean(exc)))
            continue
        for msg in helper_problems:
            problems.append("%s: worker reported: %s" % (host, clean(msg)))
        for item in items:
            cand = verify_item(hdir, host, item, problems, failed)
            if cand:
                candidates.append(cand)
    return candidates, failed


def select_latest(candidates, failed, problems):
    by_group = {}
    for cand in candidates:
        by_group.setdefault(cand["group"], []).append(cand)
    selected = []
    for group in sorted(by_group):
        if group in failed:
            continue  # a copy of this group failed verification; do not fall back
        newest = max(c["timestamp"] for c in by_group[group])
        top = [c for c in by_group[group] if c["timestamp"] == newest]
        if len({c["sha256"] for c in top}) > 1:
            problems.append("%s: conflicting copies with timestamp %s on hosts %s; not collected"
                            % (group, newest, ", ".join(sorted(c["host"] for c in top))))
            continue
        selected.append(top[0])
    return selected


def candidate_names(prefix, ts):
    day, hhmm = ts[:8], ts[9:13]
    yield "%s%s.ipynb" % (prefix, day)
    yield "%s%s_%s.ipynb" % (prefix, day, hhmm)
    for n in range(2, 100):
        yield "%s%s_%s_%d.ipynb" % (prefix, day, hhmm, n)


def existing_pattern(prefix):
    """Exactly the names candidate_names() can produce for this prefix."""
    return re.compile(r"^" + re.escape(prefix)
                      + r"[0-9]{8}(?:_[0-9]{4}(?:_[0-9]{1,2})?)?\.ipynb$")


def place(dest, cand, prefix, problems):
    """Returns (status, name, note)."""
    group = cand["group"]
    pattern = existing_pattern(prefix)
    for existing in sorted(os.listdir(dest)):
        if not pattern.match(existing):
            continue
        path = os.path.join(dest, existing)
        try:
            found = hashlib.sha256(read_regular(path, MAX_BYTES)).hexdigest()
        except (OSError, ValueError) as exc:
            problems.append("%s: could not check existing %s for duplicates (%s)"
                            % (group, clean(existing), clean(exc)))
            continue
        if found == cand["sha256"]:
            note = ""
            try:
                if ensure_private(path):
                    note = " (permissions corrected to 0600)"
            except (OSError, ValueError) as exc:
                problems.append("%s: could not set 0600 on existing %s (%s)"
                                % (group, clean(existing), clean(exc)))
            return "already collected", existing, note
    fd, tmp = tempfile.mkstemp(prefix=".incoming.", dir=dest)  # mode 0600
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(cand["data"])
            handle.flush()
            os.fsync(handle.fileno())
        for name in candidate_names(prefix, cand["timestamp"]):
            final = os.path.join(dest, name)
            try:
                os.link(tmp, final)  # never overwrites an existing name
            except FileExistsError:
                continue
            try:
                ok = hashlib.sha256(read_regular(final, MAX_BYTES)).hexdigest() == cand["sha256"]
            except (OSError, ValueError):
                ok = False
            if not ok:
                removed = False
                try:
                    # remove only our own just-created link, never any other file
                    if os.path.samestat(os.lstat(tmp), os.lstat(final)):
                        os.unlink(final)
                        removed = True
                except OSError:
                    pass
                raise ValueError("verification of %s failed after writing; %s"
                                 % (name, "new copy removed" if removed else "copy left in place, check it"))
            return "collected", name, ""
        raise ValueError("no free file name")
    finally:
        os.unlink(tmp)


def prepare_dest(dest):
    if os.path.lexists(dest):
        if not stat.S_ISDIR(os.lstat(dest).st_mode):
            sys.exit("ERROR: destination is not a plain directory: %s" % dest)
    else:
        os.mkdir(dest, 0o700)  # parent (the assessment directory) must already exist
    os.chmod(dest, 0o700)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staging", required=True)
    ap.add_argument("--dest", required=True)
    ap.add_argument("--workshop", required=True)
    ap.add_argument("--module-dir", required=True)
    args = ap.parse_args()

    if not WORKSHOP_RE.match(args.workshop) or not MODULE_RE.match(args.module_dir):
        sys.exit("ERROR: invalid --workshop or --module-dir")
    dest = os.path.abspath(args.dest)
    if not dest.endswith("/assessment/submissions") or not os.path.isdir(os.path.dirname(dest)):
        sys.exit("ERROR: --dest must be <module>/assessment/submissions under an existing assessment directory")
    if os.path.islink(args.staging) or not os.path.isdir(args.staging):
        sys.exit("ERROR: staging directory missing or a symlink")

    problems = []
    candidates, failed = load_candidates(args.staging, problems)
    selected = select_latest(candidates, failed, problems)

    collected = already = 0
    if selected:
        prepare_dest(dest)
    for cand in selected:
        prefix = "%s_%s_%s_" % (cand["group"], args.workshop, args.module_dir)
        try:
            status, name, note = place(dest, cand, prefix, problems)
        except (OSError, ValueError) as exc:
            problems.append("%s: not collected (%s)" % (cand["group"], clean(exc)))
            continue
        print("%-17s %s -> %s%s" % (status, cand["group"], name, note))
        if status == "collected":
            collected += 1
        else:
            already += 1
    for line in problems:
        print("PROBLEM: %s" % line)
    print("Summary: %d collected, %d already collected, %d problem(s)" % (collected, already, len(problems)))
    return 3 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
