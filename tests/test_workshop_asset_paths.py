"""Repository paths read by deployment code, organiser scripts and tests exist.

Workshop material is only safe to move when every repository path that reads
it still resolves. This is a static check: no Ansible run and no cluster.
"""
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK_DIR = ROOT / "playbooks"
COPY_MODULES = {
    "copy",
    "ansible.builtin.copy",
    "template",
    "ansible.builtin.template",
}
ASSET_PATH = re.compile(r"workshop_assets/[A-Za-z0-9_.\-/]*")
JINJA_NAME = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def code_files():
    """Files whose literal workshop_assets paths are read at run time."""
    for pattern in ("roles/**/*.yml", "roles/**/*.j2", "playbooks/**/*.yml"):
        yield from ROOT.glob(pattern)
    for pattern in ("scripts/**/*.sh", "scripts/**/*.py"):
        yield from ROOT.glob(pattern)
    for path in ROOT.glob("tests/*.py"):
        if path.name != Path(__file__).name:
            yield path


def iter_tasks(tasks):
    """Yield tasks, including those nested in block/rescue/always."""
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        yield task
        for key in ("block", "rescue", "always"):
            yield from iter_tasks(task.get(key))


def role_tasks():
    """Yield (role directory, role defaults, task) for every role task."""
    for tasks_file in sorted(ROOT.glob("roles/*/tasks/*.yml")):
        role = tasks_file.parents[1]
        defaults_file = role / "defaults" / "main.yml"
        defaults = {}
        if defaults_file.is_file():
            defaults = yaml.safe_load(defaults_file.read_text(encoding="utf-8")) or {}
        tasks = yaml.safe_load(tasks_file.read_text(encoding="utf-8"))
        for task in iter_tasks(tasks):
            yield role, defaults, task


def copy_source(task):
    """Return the src argument of a copy/template task, if any."""
    for module in COPY_MODULES:
        arguments = task.get(module)
        if isinstance(arguments, dict) and isinstance(arguments.get("src"), str):
            return arguments["src"]
    return None


def render(template, variables, depth=0):
    """Resolve playbook_dir and simple role-default variables."""
    if depth > 5:
        raise ValueError(f"variable nesting too deep: {template}")

    def substitute(match):
        name = match.group(1)
        if name == "playbook_dir":
            return str(PLAYBOOK_DIR)
        if name in variables and isinstance(variables[name], str):
            return render(variables[name], variables, depth + 1)
        raise KeyError(name)

    return JINJA_NAME.sub(substitute, template)


class WorkshopAssetPathTests(unittest.TestCase):
    maxDiff = None

    def test_literal_workshop_asset_paths_exist(self):
        missing = []
        for path in code_files():
            text = path.read_text(encoding="utf-8")
            for match in ASSET_PATH.finditer(text):
                relative = match.group(0).rstrip("./")
                if not (ROOT / relative).exists():
                    line = text.count("\n", 0, match.start()) + 1
                    missing.append(f"{path.relative_to(ROOT)}:{line}: {relative}")
        self.assertEqual([], missing)

    def test_role_relative_copy_sources_exist(self):
        missing = []
        for role, _defaults, task in role_tasks():
            source = copy_source(task)
            if source is None or "{{" in source or source.startswith("/"):
                continue
            candidates = [role / "files" / source, role / "templates" / source, role / source]
            if not any(candidate.exists() for candidate in candidates):
                missing.append(f"{role.relative_to(ROOT)}: {source}")
        self.assertEqual([], missing)

    def test_looped_copy_sources_exist(self):
        missing = []
        checked = 0
        for role, defaults, task in role_tasks():
            source = copy_source(task)
            if source is None or "item" not in source or "item." in source:
                continue
            items = task.get("loop", task.get("with_items"))
            if isinstance(items, str):
                name = JINJA_NAME.fullmatch(items.strip())
                items = defaults.get(name.group(1)) if name else None
            if not isinstance(items, list):
                continue
            for item in items:
                if "{{" in str(item):
                    # Deployment-supplied files (for example TLS material) are not
                    # repository files.
                    continue
                variables = dict(defaults, item=str(item))
                resolved = Path(render(source, variables))
                if not resolved.is_absolute():
                    resolved = role / "files" / resolved
                checked += 1
                if not resolved.exists():
                    missing.append(f"{role.relative_to(ROOT)}: {source} [{item}]")
        self.assertGreater(checked, 0)
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
