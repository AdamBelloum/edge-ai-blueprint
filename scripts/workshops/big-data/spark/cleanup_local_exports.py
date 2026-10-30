"""Scoped controller-side Spark SSH export cleanup.

No actions on import. Production root is derived from this module's repository.
All selected workers are preflighted before deletion. Unknown files, links,
unsafe ownership/permissions, mounts and identity changes cause refusal.
The directory lock serializes this helper, not credential generation: organisers
must exclude concurrent credential generation/staging throughout cleanup.
"""
import argparse
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys

FILES = frozenset({'login_key', 'host_key.pub', 'known_hosts'})
FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def protected(info, directory=False, public=False):
    require(info.st_uid == os.getuid(), 'Export must belong to the invoking user.')
    if public:
        # Historical fetch exports can be 0664. This exception applies only
        # to the public key within an independently validated 0700 directory.
        require(stat.S_IMODE(info.st_mode) in {0o644, 0o664},
                'Unexpected public-key export permissions.')
    else:
        require(not stat.S_IMODE(info.st_mode) & 0o022,
                'Group/world-writable export or managed directory refused.')
    if directory:
        require(stat.S_ISDIR(info.st_mode), 'Expected a managed directory.')
    else:
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                'Linked or special export file refused.')


def worker_names(names):
    require(isinstance(names, (list, tuple, set)) and bool(names),
            'An explicit non-empty worker selection is required.')
    require(all(isinstance(n, str) and NAME.fullmatch(n) for n in names),
            'Unsafe worker export directory name.')
    return sorted(set(names))


def inventory_workers(inventory, group):
    require(isinstance(inventory, dict) and isinstance(group, str)
            and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', group),
            'Invalid inventory or worker group.')
    def visit(name, ancestors):
        require(name not in ancestors, 'Cyclic inventory group hierarchy.')
        value = inventory.get(name)
        require(isinstance(value, dict), 'Selected inventory group is unavailable.')
        hosts, children = value.get('hosts', []), value.get('children', [])
        require(isinstance(hosts, list) and isinstance(children, list)
                and all(isinstance(c, str) for c in children),
                'Malformed inventory group membership.')
        result = list(hosts)
        for child in children:
            result.extend(visit(child, ancestors | {name}))
        return result
    return worker_names(visit(group, set()))


def mounts():
    result = set()
    with open('/proc/self/mountinfo', encoding='utf-8') as stream:
        for line in stream:
            fields = line.split()
            require(len(fields) >= 10 and '-' in fields, 'Invalid mount information.')
            result.add(re.sub(r'\\([0-7]{3})',
                             lambda m: chr(int(m[1], 8)), fields[4]))
    return result


def cleanup(repository, workers, *, execute=False):
    """Tests supply a temporary repository; CLI always uses its own repository."""
    workers = worker_names(workers)
    repository = Path(os.path.abspath(repository))
    root = repository / 'secrets' / 'big-data-spark-direct'
    require(repository != Path('/'), 'Filesystem root is not a repository.')
    require('..' not in repository.parts, 'Parent traversal refused.')
    result = {'selected_workers': workers, 'removed_paths': [],
              'candidate_paths': [], 'cleanup_verified': False}
    with ExitStack() as stack:
        def opened(name, parent=None):
            fd = os.open(name, FLAGS, dir_fd=parent)
            stack.callback(os.close, fd)
            return fd
        parent = opened('/')
        # Never follow symlinks in any ancestor. Require protected ownership
        # from the repository root onwards; shared system ancestors are allowed.
        components = root.parts[1:]
        repository_depth = len(repository.parts) - 1
        for index, component in enumerate(components, 1):
            try:
                parent = opened(component, parent)
            except FileNotFoundError:
                require(index > repository_depth, 'Repository is unavailable.')
                result['cleanup_verified'] = execute
                return result
            if index >= repository_depth:
                protected(os.fstat(parent), directory=True)
        root_fd = parent
        fcntl.flock(root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        mounted = mounts()
        device = os.fstat(root_fd).st_dev

        def scan(fd):
            protected(os.fstat(fd), directory=True)
            require(stat.S_IMODE(os.fstat(fd).st_mode) == 0o700,
                    'Worker export directory must remain mode 0700.')
            names = sorted(os.listdir(fd))
            require(set(names) <= FILES, 'Unknown file in selected worker export directory.')
            entries = {}
            for name in names:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                protected(info, public=(name == 'host_key.pub'))
                require(info.st_dev == device, 'Cross-device export refused.')
                if name in {'login_key', 'known_hosts'}:
                    require(stat.S_IMODE(info.st_mode) == 0o600,
                            'Private export must have mode 0600.')
                entries[name] = signature(info)
            return entries

        plans = []
        for worker in workers:
            path = str(root / worker)
            require(not any(m == path or m.startswith(path + '/') for m in mounted),
                    'Mounted worker export tree refused.')
            try:
                info = os.stat(worker, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            protected(info, directory=True)
            require(info.st_dev == device and stat.S_IMODE(info.st_mode) == 0o700,
                    'Worker export directory must be local and mode 0700.')
            fd = opened(worker, root_fd)
            require(signature(os.fstat(fd)) == signature(info),
                    'Worker export directory changed while opening.')
            entries = scan(fd)
            plans.append((worker, fd, signature(info), entries))
            result['candidate_paths'].extend(str(root / worker / n) for n in entries)

        # Complete preflight of all workers before the first deletion.
        for worker, fd, original, entries in plans:
            require(signature(os.stat(worker, dir_fd=root_fd, follow_symlinks=False))
                    == original and signature(os.fstat(fd)) == original
                    and scan(fd) == entries, 'Export identities changed after preflight.')
        if not execute:
            return result
        for worker, fd, original, entries in plans:
            # Recheck immediately before this worker's deletion as well.
            require(signature(os.stat(worker, dir_fd=root_fd, follow_symlinks=False))
                    == original and signature(os.fstat(fd)) == original
                    and scan(fd) == entries, 'Export identities changed before removal.')
            for name, expected in entries.items():
                require(signature(os.stat(name, dir_fd=fd, follow_symlinks=False))
                        == expected, 'Export file replaced before removal.')
                os.unlink(name, dir_fd=fd)
                result['removed_paths'].append(str(root / worker / name))
            require(not os.listdir(fd), 'Worker exports remain or appeared.')
            os.fsync(fd)
            linked = os.stat(worker, dir_fd=root_fd, follow_symlinks=False)
            require((linked.st_dev, linked.st_ino) == original[:2],
                    'Worker export directory replaced before removal.')
            os.rmdir(worker, dir_fd=root_fd)
        os.fsync(root_fd)
        for worker in workers:
            try:
                os.stat(worker, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise ValueError('Selected worker exports remain or were recreated.')
        result['cleanup_verified'] = True
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker-group', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    try:
        selected = inventory_workers(json.load(sys.stdin), args.worker_group)
        repository = Path(__file__).absolute().parents[4]
        result = cleanup(repository, selected, execute=args.execute)
        print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        print('ERROR: Local Spark export cleanup remains unverified: ' + str(error),
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
