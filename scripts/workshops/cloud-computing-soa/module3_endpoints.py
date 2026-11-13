#!/usr/bin/env python3
"""Maintain the Module 3 participant endpoint reference file (TSV).

Default path: ${XDG_STATE_HOME:-$HOME/.local/state}/digitafrica/module3-runtime/endpoints.tsv

Schema (tab-separated, header required, one record per line):
    inventory  group  worker_alias  auth_endpoint  shortener_endpoint

Record identity is (inventory, group, worker_alias). Within one inventory,
each group and each worker_alias may appear in at most one record.
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

HEADER = ("inventory", "group", "worker_alias", "auth_endpoint", "shortener_endpoint")
AUTH_PORT = 5001
SHORTENER_PORT = 5000
GROUP_RE = re.compile(r"group_[0-9]{2,}")
ALIAS_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
MAX_INVENTORY_LEN = 512


class StoreError(Exception):
    """Invalid input or malformed store. Nothing is written when raised."""


def default_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "digitafrica" / "module3-runtime" / "endpoints.tsv"


def _check_text(name: str, value: str) -> str:
    if not value or any(ch in value for ch in "\t\r\n"):
        raise StoreError(f"{name} must be non-empty and contain no tabs or newlines")
    if len(value) > MAX_INVENTORY_LEN:
        raise StoreError(f"{name} is too long")
    return value


def _check_ipv4(name: str, text: str) -> str:
    try:
        addr = ipaddress.IPv4Address(text)
    except ValueError:
        raise StoreError(f"{name}: not a valid IPv4 address: {text!r}") from None
    if addr.is_unspecified or addr.is_loopback or addr.is_multicast or addr.is_reserved:
        raise StoreError(f"{name}: unusable host address: {text!r}")
    return str(addr)


def _check_endpoint(name: str, text: str, port: int) -> str:
    host, sep, port_text = text.rpartition(":")
    if not sep or port_text != str(port):
        raise StoreError(f"{name} must be <IPv4>:{port}, got {text!r}")
    return f"{_check_ipv4(name, host)}:{port}"


def check_identity(inventory: str, group: str, alias: str) -> tuple[str, str, str]:
    inventory = _check_text("inventory", inventory)
    if not GROUP_RE.fullmatch(group):
        raise StoreError(f"group must look like group_01, got {group!r}")
    if not ALIAS_RE.fullmatch(alias):
        raise StoreError(f"invalid worker alias: {alias!r}")
    return inventory, group, alias


def make_record(inventory, group, alias, auth, shortener) -> tuple[str, ...]:
    inventory, group, alias = check_identity(inventory, group, alias)
    return (
        inventory,
        group,
        alias,
        _check_endpoint("auth endpoint", auth, AUTH_PORT),
        _check_endpoint("shortener endpoint", shortener, SHORTENER_PORT),
    )


def check_consistent(records: list[tuple[str, ...]]) -> None:
    identities: set[tuple[str, str, str]] = set()
    groups: set[tuple[str, str]] = set()
    aliases: set[tuple[str, str]] = set()
    for inventory, group, alias, _auth, _shortener in records:
        if (inventory, group, alias) in identities:
            raise StoreError(f"duplicate record for {group}/{alias} in inventory {inventory}")
        if (inventory, group) in groups:
            raise StoreError(f"group {group} appears twice in inventory {inventory}")
        if (inventory, alias) in aliases:
            raise StoreError(f"worker alias {alias} appears twice in inventory {inventory}")
        identities.add((inventory, group, alias))
        groups.add((inventory, group))
        aliases.add((inventory, alias))


def read_store(path: Path) -> list[tuple[str, ...]]:
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise StoreError(f"cannot inspect {path}: {exc}") from None
    if not stat.S_ISREG(mode):
        raise StoreError(f"{path} is not a regular file; refusing to modify it")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise StoreError(f"cannot read {path}: {exc}") from None
    if text == "":
        return []
    if not text.endswith("\n"):
        raise StoreError(f"{path}: last line is missing its newline")
    lines = text[:-1].split("\n")
    if tuple(lines[0].split("\t")) != HEADER:
        raise StoreError(f"{path}: unexpected header; refusing to modify it")
    records: list[tuple[str, ...]] = []
    for number, line in enumerate(lines[1:], start=2):
        fields = tuple(line.split("\t"))
        if len(fields) != 5:
            raise StoreError(f"{path}: line {number} has {len(fields)} columns, expected 5")
        try:
            record = make_record(*fields)
        except StoreError as exc:
            raise StoreError(f"{path}: line {number}: {exc}") from None
        if record != fields:
            raise StoreError(f"{path}: line {number} is not in normalised form")
        records.append(record)
    check_consistent(records)
    return records


def write_store(path: Path, records: list[tuple[str, ...]]) -> None:
    check_consistent(records)
    if not records:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise StoreError(f"cannot remove {path}: {exc}") from None
        return

    directory = path.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    lines = ["\t".join(HEADER)] + ["\t".join(r) for r in sorted(records)]
    data = "\n".join(lines) + "\n"

    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=".endpoints.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def save_record(path: Path, record: tuple[str, ...]) -> list[tuple[str, ...]]:
    """Insert or replace a record. Conflicting records (same inventory, same
    group or same alias, different identity) are removed and returned."""
    records = read_store(path)
    inventory, group, alias = record[:3]
    replaced = [r for r in records if r[0] == inventory and (r[1] == group or r[2] == alias)]
    kept = [r for r in records if r not in replaced]
    kept.append(record)
    write_store(path, kept)
    return replaced


def forget_records(path: Path, identities: list[tuple[str, str, str]]) -> int:
    """Remove exact identities only. Returns the number of removed records."""
    records = read_store(path)
    wanted = set(identities)
    kept = [r for r in records if r[:3] not in wanted]
    removed = len(records) - len(kept)
    if removed:
        write_store(path, kept)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Module 3 endpoint reference file")
    parser.add_argument("--path", type=Path, default=None, help="override store path (tests)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("path")
    sub.add_parser("list")
    save = sub.add_parser("save")
    for name in ("inventory", "group", "alias", "auth", "shortener"):
        save.add_argument(name)
    forget = sub.add_parser("forget", help="INVENTORY GROUP ALIAS [...] triples")
    forget.add_argument("triples", nargs="+")
    args = parser.parse_args(argv)
    path = args.path or default_path()

    try:
        if args.command == "path":
            print(path)
        elif args.command == "list":
            print("\t".join(HEADER))
            for record in read_store(path):
                print("\t".join(record))
        elif args.command == "save":
            record = make_record(args.inventory, args.group, args.alias, args.auth, args.shortener)
            replaced = save_record(path, record)
            for old in replaced:
                print(f"replaced conflicting record: {old[1]}/{old[2]} in {old[0]}", file=sys.stderr)
            print(f"saved {record[1]}/{record[2]}")
        elif args.command == "forget":
            if len(args.triples) % 3:
                raise StoreError("forget needs INVENTORY GROUP ALIAS triples")
            identities = [
                check_identity(*args.triples[i:i + 3]) for i in range(0, len(args.triples), 3)
            ]
            removed = forget_records(path, identities)
            print(f"removed {removed} record(s)")
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
