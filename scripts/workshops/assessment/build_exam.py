#!/usr/bin/env python3
"""
build_exam.py
=============
CLI tool that converts a declarative YAML question definition into a
fully-functional Jupyter notebook (.ipynb) ready for deployment on JupyterHub.

Usage
-----
    python3 build_exam.py <path/to/questions.yaml> [--output <out.ipynb>] [--config <cfg.json>]
                          [--num-questions N] [--seed S]

The generated notebook embeds:
  * A setup cell that imports assessment_tools and starts the session.
  * One or more cells per question (markdown + interactive cell).
  * A final submission cell.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import random
import sys
import textwrap
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    sys.exit("❌  Missing dependency: pip install pyyaml")

try:
    import nbformat
    from nbformat.v4 import new_notebook, new_markdown_cell, new_code_cell
except ImportError:
    sys.exit("❌  Missing dependency: pip install nbformat")


# ── ANSI helpers for CLI output ───────────────────────────────────────────────
_G  = "\033[32m"
_R  = "\033[31m"
_Y  = "\033[33m"
_B  = "\033[34m"
_RST = "\033[0m"

def ok(msg: str)   -> None: print(f"{_G}✔  {msg}{_RST}")
def err(msg: str)  -> None: print(f"{_R}✘  {msg}{_RST}", file=sys.stderr)
def warn(msg: str) -> None: print(f"{_Y}⚠  {msg}{_RST}")
def info(msg: str) -> None: print(f"{_B}ℹ  {msg}{_RST}")


# ═══════════════════════════════════════════════════════════════════════════════
# Schema validation
# ═══════════════════════════════════════════════════════════════════════════════

VALID_TYPES = {"markdown", "qa", "code", "open_question", "cloze"}

def _validate_cloze(q: Dict[str, Any], prefix: str, q_id: Any) -> List[str]:
    """Validate a 'cloze' item: 2-4 numbered blanks, lettered word bank."""
    import re
    errs: List[str] = []
    where = f"{prefix} (id={q_id})"
    bank = q.get("word_bank")
    blanks = q.get("blanks")

    if not isinstance(bank, list) or not bank:
        return [f"{where}: 'word_bank' must be a non-empty list."]
    texts = [str(b).strip() for b in bank]
    if any(not t for t in texts):
        errs.append(f"{where}: 'word_bank' contains an empty entry.")
    if len({t.lower() for t in texts}) != len(texts):
        errs.append(f"{where}: 'word_bank' entries must be unique.")
    if len(texts) > 26:
        errs.append(f"{where}: 'word_bank' has more than 26 entries.")

    if "answers" in q:
        errs.append(f"{where}: 'answers' is not allowed in a cloze; correct "
                    "letters belong only in the separate answer model.")
    if isinstance(blanks, bool) or not isinstance(blanks, int) or not 2 <= blanks <= 4:
        errs.append(f"{where}: 'blanks' must be an integer from 2 to 4.")
        return errs
    n = blanks
    if len(texts) < n + 2:
        errs.append(f"{where}: 'word_bank' needs at least 2 distractors "
                    f"(>= {n + 2} entries for {n} blanks).")

    markers = [int(m) for m in re.findall(r"\[(\d+)\]", str(q.get("content", "")))]
    if sorted(markers) != list(range(1, n + 1)):
        errs.append(f"{where}: 'content' must contain each marker [1]..[{n}] "
                    f"exactly once (found {markers}).")

    return errs


PROBE_MAX = 8


def _validate_probes(q: Dict[str, Any], prefix: str, q_id: Any, q_type: str) -> List[str]:
    """
    Validate the optional 'probes' / 'probe_setup' fields of a code question.

    Probes are visible, expression-only call examples; their observed results
    are recorded in the sidecar.  They must never carry an expected value.
    """
    has_probes = "probes" in q
    has_setup = "probe_setup" in q
    if not (has_probes or has_setup):
        return []
    where = f"{prefix} (id={q_id})"
    if q_type != "code":
        return [f"{where}: 'probes'/'probe_setup' are only allowed on type 'code'."]
    errs: List[str] = []
    if has_setup and not has_probes:
        errs.append(f"{where}: 'probe_setup' requires 'probes'.")
    if has_probes:
        probes = q["probes"]
        if not isinstance(probes, list) or not 1 <= len(probes) <= PROBE_MAX:
            errs.append(f"{where}: 'probes' must be a list of 1-{PROBE_MAX} expressions.")
        else:
            seen: set = set()
            for k, p in enumerate(probes, start=1):
                tag = f"{where}: probes[{k}]"
                if not isinstance(p, str) or not p or p != p.strip() or "\n" in p:
                    errs.append(f"{tag} must be a non-empty one-line string with no leading/trailing spaces.")
                    continue
                if p in seen:
                    errs.append(f"{tag} duplicates an earlier probe.")
                seen.add(p)
                try:
                    tree = ast.parse(p, mode="eval")
                except SyntaxError as exc:
                    errs.append(f"{tag} is not a valid Python expression: {exc.msg}.")
                    continue
                body = tree.body
                if isinstance(body, (ast.Compare, ast.BoolOp)) or (
                    isinstance(body, ast.UnaryOp) and isinstance(body.op, ast.Not)
                ):
                    errs.append(f"{tag} must not compare or combine values; expected values never appear in the notebook.")
                if not any(isinstance(n, ast.Call) for n in ast.walk(tree)):
                    errs.append(f"{tag} must contain a call to the participant's code.")
    if has_setup:
        setup = q["probe_setup"]
        if not isinstance(setup, str) or not setup.strip() or len(setup) > 2000:
            errs.append(f"{where}: 'probe_setup' must be a non-empty string of at most 2000 characters.")
        else:
            try:
                stree = ast.parse(setup)
            except SyntaxError as exc:
                errs.append(f"{where}: 'probe_setup' is not valid Python: {exc.msg}.")
            else:
                if any(isinstance(n, ast.Assert) for n in ast.walk(stree)):
                    errs.append(f"{where}: 'probe_setup' must not contain assert statements.")
    return errs


def _validate_definition(defn: Dict[str, Any]) -> List[str]:
    """
    Validate the parsed YAML structure.  Returns a list of human-readable
    error strings; empty list means the definition is valid.
    """
    errors: List[str] = []

    if "questions" not in defn:
        errors.append("Top-level key 'questions' is missing.")
        return errors  # can't proceed further

    ids_seen: set = set()
    for i, q in enumerate(defn["questions"], start=1):
        prefix = f"Question #{i}"

        if not isinstance(q, dict):
            errors.append(f"{prefix}: must be a mapping, got {type(q).__name__}.")
            continue

        # Required fields
        for field in ("id", "type", "content"):
            if field not in q:
                errors.append(f"{prefix}: required field '{field}' is missing.")

        q_id = q.get("id", f"<unknown-{i}>")
        if q_id in ids_seen:
            errors.append(f"{prefix}: duplicate id '{q_id}' — all ids must be unique.")
        ids_seen.add(q_id)

        q_type = q.get("type", "")
        if q_type not in VALID_TYPES:
            errors.append(
                f"{prefix} (id={q_id}): type '{q_type}' is invalid. "
                f"Must be one of: {sorted(VALID_TYPES)}."
            )

        if q_type != "markdown" and not str(q_id).isidentifier():
            errors.append(
                f"{prefix} (id={q_id}): id must be a valid Python identifier "
                "(letters, digits, underscore; not starting with a digit) "
                "because it is used in cell function names."
            )

        # Type-specific checks
        if q_type == "qa":
            if "correct_answer" not in q:
                errors.append(
                    f"{prefix} (id={q_id}): type 'qa' requires a 'correct_answer' field."
                )
            if "options" in q and not isinstance(q["options"], list):
                errors.append(
                    f"{prefix} (id={q_id}): 'options' must be a list."
                )

        if q_type == "cloze":
            errors.extend(_validate_cloze(q, prefix, q_id))

        if q_type == "code":
            if "initial_code" not in q:
                warn(f"{prefix} (id={q_id}): 'initial_code' not set — an empty stub will be used.")

        errors.extend(_validate_probes(q, prefix, q_id, q_type))

    return errors



# ═══════════════════════════════════════════════════════════════════════════════
# Question selection (--num-questions)
# ═══════════════════════════════════════════════════════════════════════════════

SELECTABLE_TYPES = ("qa", "code", "open_question", "cloze")


def _allocate_quotas(counts: Dict[str, int], n: int, rng: random.Random) -> Dict[str, int]:
    """
    Decide how many questions to take from each type.

    * n >= number of types: one per type first, the rest split in proportion
      to the remaining capacity of each type (largest-remainder rounding).
    * n <  number of types: n types are drawn at random (weighted by size),
      one question each.
    """
    types = list(counts)
    if n < len(types):
        remaining = list(types)
        quotas = {t: 0 for t in types}
        for _ in range(n):
            pick = rng.choices(remaining, weights=[counts[t] for t in remaining])[0]
            quotas[pick] = 1
            remaining.remove(pick)
        return quotas

    quotas = {t: 1 for t in types}
    extra = n - len(types)
    if extra == 0:
        return quotas

    caps = {t: counts[t] - 1 for t in types}
    cap_total = sum(caps.values())
    shares = {t: divmod(extra * caps[t], cap_total) for t in types}
    for t in types:
        quotas[t] += shares[t][0]
    leftover = extra - sum(s[0] for s in shares.values())
    order = sorted(types, key=lambda t: (-shares[t][1], rng.random()))
    for t in order[:leftover]:
        quotas[t] += 1
    return quotas


def select_questions(questions: List[Dict[str, Any]], n: int, seed: Optional[int]):
    """
    Return (selected_questions, seed_used, report) where report maps each
    question type to (selected_count, available_count).

    Markdown cells are always kept and are not counted.  The relative order
    of the original questions is preserved.
    """
    pool = {t: [q for q in questions if q.get("type") == t] for t in SELECTABLE_TYPES}
    pool = {t: qs for t, qs in pool.items() if qs}
    total = sum(len(qs) for qs in pool.values())

    if n < 1:
        raise ValueError("--num-questions must be at least 1.")
    if n > total:
        raise ValueError(
            f"--num-questions {n} exceeds the {total} available question(s) "
            "(markdown cells are not counted)."
        )

    if seed is None:
        seed = random.SystemRandom().randrange(2**32)
    rng = random.Random(seed)

    quotas = _allocate_quotas({t: len(qs) for t, qs in pool.items()}, n, rng)
    chosen = set()
    for t, qs in pool.items():
        for q in rng.sample(qs, quotas[t]):
            chosen.add(q["id"])

    selected = [q for q in questions if q.get("type") == "markdown" or q["id"] in chosen]
    report = {t: (quotas[t], len(pool[t])) for t in pool}
    return selected, seed, report


# ═══════════════════════════════════════════════════════════════════════════════
# Cell builders
# ═══════════════════════════════════════════════════════════════════════════════

def _setup_cell(config: Dict[str, Any]) -> Any:
    """
    The mandatory first code cell: imports assessment_tools and starts the session.
    Students must run this before any other cell.
    """
    scripts_dir  = config.get("scripts_dir",  "/opt/workshop-assessment/scripts")
    mode         = config.get("mode",          "manual")
    duration     = config.get("duration_minutes", "None")
    allow_manual = str(config.get("allow_manual_submit", True))
    title        = config.get("assessment_title", "Assessment")

    source = textwrap.dedent(f"""\
        # ══════════════════════════════════════════════════════════════
        # SETUP CELL — Run this cell FIRST to initialise your session.
        # ══════════════════════════════════════════════════════════════
        import sys, os

        _SCRIPTS_DIR = os.environ.get("ASSESSMENT_SCRIPTS_DIR", {scripts_dir!r})
        if _SCRIPTS_DIR not in sys.path:
            sys.path.insert(0, _SCRIPTS_DIR)

        from assessment_tools import AssessmentSession

        _session = AssessmentSession.start(
            duration_minutes={duration},
            mode={mode!r},
            allow_manual_submit={allow_manual},
        )
        print(_session.status_message())
    """)
    tags = ["assessment-setup"]
    if config.get("individual_copies", True):
        # Group workshops: each person works in a personal copy of this template.
        source = textwrap.dedent(f"""\
            # ══════════════════════════════════════════════════════════════
            # SETUP CELL — Run this cell FIRST.
            # It asks for your name and creates YOUR personal copy of this exam.
            # Then open that copy and run its first cell.
            # ══════════════════════════════════════════════════════════════
            import sys, os

            _SCRIPTS_DIR = os.environ.get("ASSESSMENT_SCRIPTS_DIR", {scripts_dir!r})
            if _SCRIPTS_DIR not in sys.path:
                sys.path.insert(0, _SCRIPTS_DIR)

            from assessment_tools import create_individual_copy

            _session = None
            create_individual_copy(
                scripts_dir=_SCRIPTS_DIR,
                duration_minutes={duration},
                mode={mode!r},
                allow_manual_submit={allow_manual},
            )
        """)
        tags.append("assessment-template")
    cell = new_code_cell(source)
    cell.metadata["editable"] = False
    cell.metadata["deletable"] = False
    cell.metadata["tags"] = tags
    return cell


def _header_cell(defn: Dict[str, Any], config: Dict[str, Any]) -> Any:
    """Top-of-notebook markdown banner."""
    title    = config.get("assessment_title", defn.get("assessment_title", "Assessment"))
    mode     = config.get("mode", defn.get("mode", "manual"))
    duration = config.get("duration_minutes", defn.get("duration_minutes"))
    retries  = config.get("max_cell_retries", defn.get("max_cell_retries", 3))

    duration_str = f"⏱ **Time limit:** {duration} minutes" if duration else "⏱ **Time limit:** Unlimited"
    mode_str     = "🕹 **Mode:** Timed (auto-submit on expiry)" if mode == "timed" else "🕹 **Mode:** Manual submit"

    md = textwrap.dedent(f"""\
        # 📋 {title}

        ---

        {duration_str}
        {mode_str}
        🔁 **Max retries per cell:** {retries}

        ---

        > **Instructions:**
        > 1. Run **Cell 1 (Setup)** first — this starts your timer and registers your session.
        > 2. Work through each question in order.
        > 3. For **Q&A cells**: set the `answer` variable and run the cell.
        > 4. For **Code cells**: edit the code inside the function and run it.
        > 5. For **Open questions**: replace the placeholder text in `answer_<id>` and call `save_text_answer(...)`.
        > 6. When done, run the **Submit** cell at the bottom.

        ---
    """)
    cell = new_markdown_cell(md)
    cell.metadata["editable"] = False
    cell.metadata["deletable"] = False
    return cell


def _markdown_question_cell(q: Dict[str, Any]) -> Any:
    """Pure markdown cell (type: markdown)."""
    cell = new_markdown_cell(q["content"])
    cell.metadata["editable"] = False
    cell.metadata["deletable"] = False
    cell.metadata["tags"] = [f"question-{q['id']}", "markdown-question"]
    return cell


FORBIDDEN_IN_CODE_CELLS = ("correct=", "check_answer", "validate_assertion")


def _flat(text: Any) -> str:
    """Collapse whitespace/newlines so a value is safe inside a one-line comment."""
    return " ".join(str(text).split())


def _verify_notebook(nb: Any) -> List[str]:
    """
    Safety net run before the notebook is written: every code cell must be
    valid Python and must not contain answer-revealing helpers.
    """
    problems: List[str] = []
    for idx, cell in enumerate(nb.cells):
        if cell.cell_type != "code":
            continue
        tags = ", ".join(cell.metadata.get("tags", [])) or "no tags"
        try:
            ast.parse(cell.source)
        except SyntaxError as exc:
            problems.append(f"cell {idx} ({tags}): syntax error: {exc.msg} (line {exc.lineno})")
        for token in FORBIDDEN_IN_CODE_CELLS:
            if token in cell.source:
                problems.append(
                    f"cell {idx} ({tags}): contains {token!r} (possible answer leak)"
                )
    return problems


def _qa_cell(q: Dict[str, Any], default_max_runs: int) -> List[Any]:
    """
    Returns [markdown prompt cell, code answer cell] for a Q&A question.

    Answer-free: the cell only records the participant's choice.  The expected
    answer stays in the (private) YAML and is used by the organiser-side
    grader only.
    """
    q_id     = q["id"]
    max_runs = q.get("max_runs", default_max_runs)
    options  = q.get("options", [])

    lines = [
        "from assessment_tools import limit_executions, record_choice",
        "",
        f'@limit_executions("{q_id}", max_runs={max_runs})',
        f"def answer_{q_id}():",
    ]
    if options:
        labels = [chr(65 + i) for i in range(len(options))]
        opts_md = "\n".join(f"  - **{lbl})** {opt}" for lbl, opt in zip(labels, options))
        lines.append("    # Options:")
        lines.extend(f"    #   {lbl}) {_flat(opt)}" for lbl, opt in zip(labels, options))
        lines.append(f'    answer = ""  # <-- Replace with your choice: {" / ".join(labels)}')
        options_arg = repr(labels)
    else:
        opts_md = ""
        lines.append('    answer = ""  # <-- Type your answer here')
        options_arg = "None"
    lines += [
        "",
        f'    return record_choice("{q_id}", answer, options={options_arg})',
        "",
        f"answer_{q_id}()",
        "",
    ]

    opts_section = f"\n{opts_md}" if opts_md else ""
    prompt_md = f"### Question `{q_id}`\n\n{q['content']}{opts_section}"
    md_cell = new_markdown_cell(prompt_md)
    md_cell.metadata["editable"] = False
    md_cell.metadata["deletable"] = False

    code_cell = new_code_cell("\n".join(lines))
    code_cell.metadata["tags"] = [f"question-{q_id}", "qa-cell"]
    return [md_cell, code_cell]


def _runtime_supports_probes() -> bool:
    """True if the sibling assessment_tools.py defines record_code(..., probes, probe_setup)."""
    from pathlib import Path
    tools = Path(__file__).with_name("assessment_tools.py")
    try:
        tree = ast.parse(tools.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "record_code":
            names = {a.arg for a in node.args.args + node.args.kwonlyargs}
            return {"probes", "probe_setup"} <= names
    return False


def _record_call(q: Dict[str, Any]) -> str:
    """Source of the final record_code(...) call; identical to the old form without probes."""
    q_id = q["id"]
    probes = q.get("probes")
    if not probes:
        return f'record_code("{q_id}", locals())'
    if not _runtime_supports_probes():
        raise ValueError(
            f"question {q_id}: 'probes' need an assessment_tools.record_code that accepts "
            "probes/probe_setup; refusing to build a notebook that the runtime cannot record."
        )
    lines = ["record_code(", f'        "{q_id}", locals(),', "        probes=["]
    lines += [f"            {p!r}," for p in probes]
    lines.append("        ],")
    if q.get("probe_setup"):
        lines.append(f"        probe_setup={q['probe_setup']!r},")
    lines.append("    )")
    return "\n".join(lines)


def _code_cell(q: Dict[str, Any], default_max_runs: int) -> List[Any]:
    """
    Returns [markdown prompt cell, code cell] for a practical coding question.

    Answer-free: the participant's code lives inside a function wrapped with
    @limit_executions and is only recorded, never validated in the notebook.
    """
    q_id     = q["id"]
    max_runs = q.get("max_runs", default_max_runs)
    stub     = textwrap.dedent(q.get("initial_code", "# Write your solution here\npass")).strip("\n")
    body     = textwrap.indent(stub, "    ") if stub else "    pass"
    record_call = _record_call(q)

    source = "\n".join([
        "from assessment_tools import limit_executions, record_code",
        "",
        f'@limit_executions("{q_id}", max_runs={max_runs})',
        f"def solve_{q_id}():",
        "    # ── Your code below — edit freely inside this function ──",
        body,
        "",
        f"    return {record_call}",
        "",
        f"solve_{q_id}()",
        "",
    ])

    prompt_md = f"### Question `{q_id}`\n\n{q['content']}"
    md_cell = new_markdown_cell(prompt_md)
    md_cell.metadata["editable"] = False
    md_cell.metadata["deletable"] = False

    code_cell_obj = new_code_cell(source)
    code_cell_obj.metadata["tags"] = [f"question-{q_id}", "code-cell"]
    return [md_cell, code_cell_obj]


def _cloze_cell(q: Dict[str, Any], default_max_runs: int) -> List[Any]:
    """
    Returns [markdown prompt cell, code answer cell] for a cloze item.

    Answer-free: the cell only records the chosen letter per blank as
    '<id>.<n>'.  All inputs are checked before anything is recorded, but the
    saves are separate calls, so this is not atomic.  Correct letters live only
    in the separate answer model used by the organiser-side grader.
    """
    q_id     = q["id"]
    max_runs = q.get("max_runs", default_max_runs)
    bank     = [str(b).strip() for b in q["word_bank"]]
    letters  = [chr(65 + i) for i in range(len(bank))]
    n        = int(q["blanks"])

    bank_md = "\n".join(f"- **{l})** {t}" for l, t in zip(letters, bank))
    prompt_md = (
        f"### Question `{q_id}` *(Fill in the blanks)*\n\n"
        f"{str(q['content']).strip()}\n\n"
        f"**Word bank**\n\n{bank_md}\n\n"
        "Choose one letter from the word bank for each blank. Your answers are "
        "recorded when you run the cell below; all blanks must be filled."
    )
    md_cell = new_markdown_cell(prompt_md)
    md_cell.metadata["editable"] = False
    md_cell.metadata["deletable"] = False

    picks = ", ".join(f'"{i}": blank_{i}' for i in range(1, n + 1))
    lines = [
        "from assessment_tools import limit_executions, record_choice",
        "",
        f'@limit_executions("{q_id}", max_runs={max_runs})',
        f"def answer_{q_id}():",
    ]
    for i in range(1, n + 1):
        lines.append(f'    blank_{i} = ""  # <-- letter for blank [{i}]')
    lines += [
        "",
        f"    picks = {{{picks}}}",
        f"    valid = {letters!r}",
        "    cleaned = {k: str(v).strip().upper() for k, v in picks.items()}",
        "    missing = [k for k, v in cleaned.items() if v not in valid]",
        "    if missing:",
        '        print("⚠️   Nothing recorded — choose a letter ({}) for blank(s): {}".format("/".join(valid), ", ".join("[" + k + "]" for k in missing)))',
        "        return None",
        "    for k, v in cleaned.items():",
        f'        record_choice("{q_id}." + k, v, options=valid)',
        "",
        f"answer_{q_id}()",
        "",
    ]
    code_cell = new_code_cell("\n".join(lines))
    code_cell.metadata["tags"] = [f"question-{q_id}", "cloze-cell"]
    return [md_cell, code_cell]


def _open_question_cell(q: Dict[str, Any]) -> List[Any]:
    """
    Returns [markdown prompt cell, code cell] for a free-text open question.
    The student assigns a multi-line string and calls save_text_answer().
    """
    q_id = q["id"]
    prompt_md = f"### Question `{q_id}` *(Open question — write your explanation below)*\n\n{q['content']}"
    md_cell = new_markdown_cell(prompt_md)
    md_cell.metadata["editable"] = False
    md_cell.metadata["deletable"] = False

    source = textwrap.dedent(f"""\
        from assessment_tools import save_text_answer

        # Write your answer between the triple quotes.
        # Do not change the variable name or the save_text_answer() call.
        answer_{q_id} = \"\"\"
        <Type your answer here>
        \"\"\"

        save_text_answer("{q_id}", answer_{q_id})
    """)
    code_cell_obj = new_code_cell(source)
    code_cell_obj.metadata["tags"] = [f"question-{q_id}", "open-question-cell"]
    return [md_cell, code_cell_obj]


def _submission_cell(config: Dict[str, Any]) -> Any:
    """Final cell that the participant runs (or that fires automatically) to submit."""
    source = textwrap.dedent("""\
        # ══════════════════════════════════════════════════════════════
        # SUBMIT — Run this cell when you have finished the exam.
        # This submits your answers and locks the notebook.
        # Run it only in YOUR personal copy, after its first cell.
        # ══════════════════════════════════════════════════════════════
        if globals().get("_session") is None:
            print("Nothing was submitted. Open your personal exam copy, run its first cell, then run this cell there.")
        else:
            _session.submit()
    """)
    cell = new_code_cell(source)
    cell.metadata["tags"] = ["assessment-submit"]
    cell.metadata["editable"] = False
    cell.metadata["deletable"] = False
    return cell


# ═══════════════════════════════════════════════════════════════════════════════
# Main builder
# ═══════════════════════════════════════════════════════════════════════════════

def build_notebook(defn: Dict[str, Any], config: Dict[str, Any]) -> nbformat.NotebookNode:
    """
    Compile a complete .ipynb notebook from the parsed definition and config.

    Parameters
    ----------
    defn:
        Parsed YAML definition dict.
    config:
        Merged configuration dict (file config overrides YAML top-level values).

    Returns
    -------
    nbformat.NotebookNode
        A fully-formed notebook ready to be written to disk.
    """
    # Merge YAML top-level keys as config defaults
    merged = {
        "assessment_title": defn.get("assessment_title", "Assessment"),
        "mode":             defn.get("mode", "manual"),
        "duration_minutes": defn.get("duration_minutes", None),
        "max_cell_retries": defn.get("max_cell_retries", 3),
        "allow_manual_submit": defn.get("allow_manual_submit", True),
    }
    merged.update({k: v for k, v in config.items() if v is not None})

    default_max_runs = int(merged.get("max_cell_retries", 3))

    cells = []

    # 1. Header banner
    cells.append(_header_cell(defn, merged))

    # 2. Setup cell
    cells.append(_setup_cell(merged))

    # 3. Question cells
    for q in defn.get("questions", []):
        q_type = q.get("type", "")
        if q_type == "markdown":
            cells.append(_markdown_question_cell(q))
        elif q_type == "qa":
            cells.extend(_qa_cell(q, default_max_runs))
        elif q_type == "code":
            cells.extend(_code_cell(q, default_max_runs))
        elif q_type == "open_question":
            cells.extend(_open_question_cell(q))
        elif q_type == "cloze":
            cells.extend(_cloze_cell(q, default_max_runs))
        else:
            warn(f"Unknown question type '{q_type}' for id='{q.get('id')}' — skipping.")

    # 4. Submission cell
    cells.append(_submission_cell(merged))

    # Build notebook
    nb = new_notebook(cells=cells)
    nb.metadata["assessment"] = {
        "title":           merged["assessment_title"],
        "mode":            merged["mode"],
        "duration_minutes": merged["duration_minutes"],
        "max_cell_retries": default_max_runs,
        "generator":       "build_exam.py",
    }
    nb.metadata["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    nb.metadata["language_info"] = {
        "name": "python",
        "version": "3.8.0",
    }
    return nb


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="build_exam.py",
        description="Convert a declarative YAML question file into a Jupyter notebook.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples
            --------
              python3 build_exam.py questions/exam.yaml
              python3 build_exam.py questions/exam.yaml --output dist/exam.ipynb
              python3 build_exam.py questions/exam.yaml --config assessment_config.json
        """),
    )
    parser.add_argument(
        "questions_file",
        metavar="<questions_file>",
        help="Path to the YAML question definition file (.yaml or .yml).",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="<output.ipynb>",
        default=None,
        help="Output path for the generated notebook.  "
             "Defaults to <questions_file_stem>.ipynb alongside the input file.",
    )
    parser.add_argument(
        "--config", "-c",
        metavar="<config.json>",
        default=None,
        help="Path to assessment_config.json (optional — YAML top-level keys are used as fallback).",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate the question file schema; do not generate the notebook.",
    )
    parser.add_argument(
        "--num-questions", "-n",
        metavar="<N>",
        type=int,
        default=None,
        help="Include only N questions (markdown cells are not counted), chosen at "
             "random per question type in proportion to each type's size. "
             "Default: all questions.",
    )
    parser.add_argument(
        "--seed",
        metavar="<S>",
        type=int,
        default=None,
        help="Seed for --num-questions so a selection can be reproduced. "
             "Default: random; the seed used is printed.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    # ── 1. Load question definition ──────────────────────────────────────────
    input_path = pathlib.Path(args.questions_file)
    if not input_path.exists():
        err(f"Question file not found: {input_path}")
        return 1
    if input_path.suffix.lower() not in {".yaml", ".yml"}:
        err(f"Question file must be .yaml or .yml, got: {input_path.suffix!r}")
        return 1

    info(f"Reading question definition: {input_path}")
    try:
        raw = input_path.read_text(encoding="utf-8")
        defn = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        err(f"YAML parse error:\n{exc}")
        return 1

    if not isinstance(defn, dict):
        err("Question file must be a YAML mapping at the top level.")
        return 1

    # ── 2. Validate schema ───────────────────────────────────────────────────
    info("Validating question schema …")
    errors = _validate_definition(defn)
    if errors:
        err(f"Schema validation failed with {len(errors)} error(s):")
        for e in errors:
            print(f"  • {e}", file=sys.stderr)
        return 1
    ok(f"Schema valid — {len(defn.get('questions', []))} question(s) found.")

    if args.validate_only:
        ok("Validation complete (--validate-only set, no notebook written).")
        return 0

    # ── 3. Load config ───────────────────────────────────────────────────────
    config: Dict[str, Any] = {}
    if args.config:
        cfg_path = pathlib.Path(args.config)
        if not cfg_path.exists():
            warn(f"Config file not found: {cfg_path} — using YAML defaults.")
        else:
            try:
                config = json.loads(cfg_path.read_text(encoding="utf-8"))
                ok(f"Config loaded: {cfg_path}")
            except json.JSONDecodeError as exc:
                warn(f"Config JSON parse error: {exc} — using YAML defaults.")

    # ── 4. Build notebook ────────────────────────────────────────────────────
    info("Generating notebook …")
    if args.num_questions is not None:
        try:
            selected, used_seed, report = select_questions(
                defn["questions"], args.num_questions, args.seed
            )
        except ValueError as exc:
            err(str(exc))
            return 1
        defn = dict(defn, questions=selected)
        ok(
            f"Selected {args.num_questions} question(s) (seed={used_seed}): "
            + ", ".join(f"{t} {k}/{avail}" for t, (k, avail) in report.items())
        )
        info("Selected ids: " + ", ".join(
            str(q["id"]) for q in selected if q.get("type") != "markdown"
        ))
    elif args.seed is not None:
        warn("--seed has no effect without --num-questions.")

    nb = build_notebook(defn, config)

    problems = _verify_notebook(nb)
    if problems:
        err("Generated notebook failed safety checks; nothing was written:")
        for p in problems:
            print(f"  • {p}", file=sys.stderr)
        return 1

    # ── 5. Determine output path ─────────────────────────────────────────────
    if args.output:
        out_path = pathlib.Path(args.output)
    else:
        out_path = input_path.with_suffix(".ipynb")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    nbformat.write(nb, str(out_path))
    ok(f"Notebook written: {out_path}")

    # ── 6. Summary ───────────────────────────────────────────────────────────
    q_count  = len(defn.get("questions", []))
    mode     = config.get("mode") or defn.get("mode", "manual")
    duration = config.get("duration_minutes") or defn.get("duration_minutes", "unlimited")
    print()
    print("┌─────────────────────────────────────────────────────┐")
    print(f"│  Generated: {out_path.name:<41}│")
    print(f"│  Questions: {q_count:<41}│")
    print(f"│  Mode     : {str(mode):<41}│")
    print(f"│  Duration : {str(duration):<41}│")
    print("└─────────────────────────────────────────────────────┘")
    return 0


if __name__ == "__main__":
    sys.exit(main())
