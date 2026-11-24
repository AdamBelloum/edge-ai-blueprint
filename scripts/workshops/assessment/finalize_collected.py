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
MAX_STATE_BYTES = 1024 * 1024
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


def _slug(name):
    import unicodedata
    text = unicodedata.normalize(
        "NFKC", unicodedata.normalize("NFKC", name).strip().casefold())
    out = []
    for ch in text:
        if ch.isalnum() or unicodedata.category(ch).startswith("M"):
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")


def valid_person(person):
    """A participant slug exactly as assessment_tools.participant_slug() makes it."""
    try:
        return bool(person) and len(person.encode("utf-8")) <= 80 and _slug(person) == person
    except (UnicodeError, TypeError):
        return False


def show(text):
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    return str(text).encode(enc, "backslashreplace").decode(enc)


def scratch_name(group, person, ts):
    """ASCII-only staging name; the real person name travels in the manifest."""
    if not person:
        return "%s_%s.ipynb" % (group, ts)
    return "%s_p%s_%s.ipynb" % (group, hashlib.sha256(person.encode("utf-8")).hexdigest()[:16], ts)


def label(cand):
    return cand["group"] + (" [%s]" % show(cand["person"]) if cand["person"] else "")


def verify_item(hdir, host, item, problems, failed):
    try:
        group, ts, name = item["group"], item["timestamp"], item["name"]
        sha, size = item["sha256"], item["size"]
        person = item["person"] if "person" in item else ""
    except (KeyError, TypeError):
        problems.append("%s: malformed manifest entry" % host)
        return None
    if not (isinstance(group, str) and GROUP_RE.match(group)
            and isinstance(ts, str) and TS_RE.match(ts) and valid_timestamp(ts)
            and isinstance(person, str) and (person == "" or valid_person(person))
            and name == scratch_name(group, person, ts)
            and isinstance(sha, str) and SHA_RE.match(sha)
            and is_int(size) and size > 0):
        problems.append("%s: manifest entry has unexpected values" % host)
        return None

    def fail(reason):
        failed.add((group, person))
        problems.append("%s/%s%s: not collected (%s)"
                        % (host, group, (" [%s]" % show(person)) if person else "", reason))

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
    state, notes = load_state(hdir, item, person)
    return {"group": group, "person": person, "timestamp": ts, "sha256": sha, "host": host,
            "data": data, "state": state, "state_notes": notes}


def load_candidates(staging, problems):
    candidates, failed, incomplete = [], set(), False
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
            incomplete = True
            continue
        for msg in helper_problems:
            problems.append("%s: worker reported: %s" % (host, clean(msg)))
            incomplete = True
        for item in items:
            cand = verify_item(hdir, host, item, problems, failed)
            if cand:
                candidates.append(cand)
    return candidates, failed, incomplete


def select_latest(candidates, failed, problems):
    by_key = {}
    for cand in candidates:
        by_key.setdefault((cand["group"], cand["person"]), []).append(cand)
    selected = []
    for key in sorted(by_key):
        if key in failed:
            continue  # a copy of this group/person failed verification; do not fall back
        label_ = key[0] + (" [%s]" % show(key[1]) if key[1] else "")
        newest = max(c["timestamp"] for c in by_key[key])
        top = [c for c in by_key[key] if c["timestamp"] == newest]
        if len({c["sha256"] for c in top}) > 1:
            problems.append("%s: conflicting copies with timestamp %s on hosts %s; not collected"
                            % (label_, newest, ", ".join(sorted(c["host"] for c in top))))
            continue
        # identical notebooks on several hosts: prefer the copy that has a usable sidecar
        selected.append(next((c for c in top if c["state"]), top[0]))
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


def load_state(hdir, item, person):
    """Optional recorded-answer sidecar. Returns (dict or None, [notes]).
    Any trouble is only a note: the notebook itself is still collected."""
    meta = item.get("state")
    if not meta:
        return None, ["no recorded-answer file (.state.json) came with this submission"]
    try:
        sname, ssha, ssize = meta["name"], meta["sha256"], meta["size"]
        if not (sname == item["name"] + ".state.json"
                and isinstance(ssha, str) and SHA_RE.match(ssha)
                and is_int(ssize) and 0 < ssize <= MAX_STATE_BYTES):
            raise ValueError("unexpected manifest values")
        data = read_regular(os.path.join(hdir, sname), MAX_STATE_BYTES)
        if len(data) != ssize or hashlib.sha256(data).hexdigest() != ssha:
            raise ValueError("checksum or size mismatch")
        doc = json.loads(data)
        if not isinstance(doc, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, ["recorded-answer file not usable (%s)" % clean(exc)]
    notes = []
    if person:
        who = doc.get("participant")
        if not (isinstance(who, str) and _slug(who) == person):
            notes.append("participant name in the recorded-answer file differs from the notebook's; kept")
    return {"data": data, "sha256": ssha}, notes


def link_new(dest, data, final_name):
    """Create dest/final_name (mode 0600) with data, never overwriting. False if the name exists."""
    fd, tmp = tempfile.mkstemp(prefix=".incoming.", dir=dest)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, os.path.join(dest, final_name))
        except FileExistsError:
            return False
        return True
    finally:
        os.unlink(tmp)


def place_state(dest, nb_name, cand, warnings):
    """Place the sidecar next to the collected notebook. Returns 'collected',
    'already present' or None. Trouble becomes a warning; nothing is overwritten."""
    state = cand["state"]
    if not state:
        return None
    sname = nb_name + ".state.json"
    path = os.path.join(dest, sname)
    try:
        created = link_new(dest, state["data"], sname)
        found = hashlib.sha256(read_regular(path, MAX_STATE_BYTES)).hexdigest()
        if found != state["sha256"]:
            warnings.append("%s: %s differs from the collected recorded-answer file; existing file kept, "
                            "not overwritten" % (label(cand), clean(sname)))
            return None
        ensure_private(path)
        return "collected" if created else "already present"
    except (OSError, ValueError) as exc:
        warnings.append("%s: could not place recorded-answer file (%s)" % (label(cand), clean(exc)))
        return None


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
    ap.add_argument("--allow-incomplete", action="store_true",
                    help="place verified copies even if a host manifest was unusable or a worker reported problems")
    args = ap.parse_args()

    if not WORKSHOP_RE.match(args.workshop) or not MODULE_RE.match(args.module_dir):
        sys.exit("ERROR: invalid --workshop or --module-dir")
    dest = os.path.abspath(args.dest)
    if not dest.endswith("/assessment/submissions") or not os.path.isdir(os.path.dirname(dest)):
        sys.exit("ERROR: --dest must be <module>/assessment/submissions under an existing assessment directory")
    if os.path.islink(args.staging) or not os.path.isdir(args.staging):
        sys.exit("ERROR: staging directory missing or a symlink")

    problems = []
    candidates, failed, incomplete = load_candidates(args.staging, problems)
    selected = select_latest(candidates, failed, problems)
    if incomplete and not args.allow_incomplete:
        problems.append("host data incomplete or unusable, so the latest submission cannot be established; "
                        "nothing was placed (--allow-incomplete overrides)")
        selected = []

    collected = already = s_new = s_have = 0
    warnings = []
    if selected:
        prepare_dest(dest)
    for cand in selected:
        prefix = "%s_%s_%s_" % (cand["group"], args.workshop, args.module_dir)
        if cand["person"]:
            prefix += cand["person"] + "_"
        try:
            status, name, note = place(dest, cand, prefix, problems)
        except (OSError, ValueError) as exc:
            problems.append("%s: not collected (%s)" % (label(cand), clean(exc)))
            continue
        print("%-17s %s -> %s%s" % (status, label(cand), show(name), note))
        if status == "collected":
            collected += 1
        else:
            already += 1
        for note in cand["state_notes"]:
            warnings.append("%s: %s" % (label(cand), note))
        sstatus = place_state(dest, name, cand, warnings)
        if sstatus:
            print("%-17s recorded answers: %s" % ("", sstatus))
            if sstatus == "collected":
                s_new += 1
            else:
                s_have += 1
    for line in warnings:
        print("WARNING: %s" % line)
    print("Recorded-answer files: %d collected, %d already present, %d warning(s)"
          % (s_new, s_have, len(warnings)))
    for line in problems:
        print("PROBLEM: %s" % line)
    print("Summary: %d collected, %d already collected, %d problem(s)" % (collected, already, len(problems)))
    return 3 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
