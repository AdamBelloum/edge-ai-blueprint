"""
assessment_tools.py
====================
Runtime helper module for the JupyterHub Workshop Assessment System.

Provides
--------
  AssessmentSession    Lifecycle manager: start, submit, lock, status.
  limit_executions     Decorator that caps per-cell execution retries.
  check_answer         Validate Q&A (multiple-choice / short-answer) with feedback.
  validate_assertion   Run a Python assertion against student code and give feedback.
  save_text_answer     Persist an open-question free-text response.
  record_choice        Record a Q&A answer without grading (exam mode).
  record_code          Record a code answer snapshot without grading (exam mode).

Environment variables (all optional — fall back to safe defaults)
-----------------------------------------------------------------
  ASSESSMENT_SCRIPTS_DIR   Where this module lives (default: /opt/workshop-assessment/scripts)
  ASSESSMENT_HARVEST_DIR   Where submissions are archived (default: /opt/workshop-assessment/submissions)
  ASSESSMENT_NOTEBOOK      Absolute path to the running notebook (auto-detected when possible)
  ASSESSMENT_USERNAME      Keycloak / JupyterHub username (auto-detected via getpass)
"""

from __future__ import annotations

import datetime
import functools
import getpass
import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional

# ── Path constants ────────────────────────────────────────────────────────────
SCRIPTS_DIR:  str = os.environ.get("ASSESSMENT_SCRIPTS_DIR", "/opt/workshop-assessment/scripts")
def _default_harvest_dir() -> str:
    """Legacy host folder if usable, otherwise a folder in the user's workspace."""
    legacy = "/opt/workshop-assessment/submissions"
    if os.path.isdir(legacy) and os.access(legacy, os.W_OK):
        return legacy
    return str(pathlib.Path.home() / ".assessment" / "submissions")


HARVEST_DIR:  str = os.environ.get("ASSESSMENT_HARVEST_DIR") or _default_harvest_dir()
STATE_DIR:    pathlib.Path = pathlib.Path.home() / ".assessment"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
_log_file = STATE_DIR / "assessment.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(_log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("assessment_tools")


# ═══════════════════════════════════════════════════════════════════════════════
# State persistence helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _state_path(notebook_id: str) -> pathlib.Path:
    """Return the JSON state file path for a given notebook identifier."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in notebook_id)
    return STATE_DIR / f"{safe}_state.json"


def _load_state(notebook_id: str) -> Dict[str, Any]:
    path = _state_path(notebook_id)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            logger.warning("Corrupt state file; resetting.")
    return {
        "notebook_id": notebook_id,
        "username": "",
        "start_time": None,
        "mode": "manual",
        "duration_minutes": None,
        "cell_runs": {},
        "cell_answers": {},
        "submitted": False,
        "submission_time": None,
        "locked": False,
    }


def _save_state(notebook_id: str, state: Dict[str, Any]) -> None:
    _state_path(notebook_id).write_text(json.dumps(state, indent=2))


# ═══════════════════════════════════════════════════════════════════════════════
# AssessmentSession
# ═══════════════════════════════════════════════════════════════════════════════

def participant_slug(name: str, max_bytes: int = 80) -> str:
    """
    Filesystem-safe, Unicode-preserving slug for a participant name.

    Letters/digits of any script and combining marks are kept (case-folded);
    every other run of characters becomes one hyphen.  Returns "" when nothing
    usable remains.
    """
    import unicodedata
    text = unicodedata.normalize(
        "NFKC", unicodedata.normalize("NFKC", str(name)).strip().casefold())
    out = []
    for ch in text:
        if ch.isalnum() or unicodedata.category(ch).startswith("M"):
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    slug = "".join(out).strip("-")
    while len(slug.encode("utf-8")) > max_bytes:
        slug = slug[:-1]
    return slug.strip("-")


def _individual_setup_source(notebook_path, participant_name, scripts_dir,
                             duration_minutes, mode, allow_manual_submit) -> str:
    return "\n".join([
        "# " + "=" * 62,
        "# SETUP CELL - personal exam copy. Run this cell FIRST.",
        "# " + "=" * 62,
        "import sys, os",
        "",
        f'_SCRIPTS_DIR = os.environ.get("ASSESSMENT_SCRIPTS_DIR", {str(scripts_dir)!r})',
        "if _SCRIPTS_DIR not in sys.path:",
        "    sys.path.insert(0, _SCRIPTS_DIR)",
        "",
        "from assessment_tools import AssessmentSession",
        "",
        "_session = AssessmentSession.start(",
        f"    notebook_path={str(notebook_path)!r},",
        f"    participant_name={str(participant_name)!r},",
        f"    duration_minutes={duration_minutes!r},",
        f"    mode={mode!r},",
        f"    allow_manual_submit={allow_manual_submit!r},",
        ")",
        "print(_session.status_message())",
        "",
    ])


def _find_exam_templates(directory):
    """Notebooks in *directory* whose setup cell is tagged 'assessment-template'."""
    found = []
    for p in sorted(pathlib.Path(directory).glob("*.ipynb")):
        try:
            nb = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for c in nb.get("cells", []):
            if "assessment-template" in c.get("metadata", {}).get("tags", []):
                found.append(p)
                break
    return found


def create_individual_copy(template_name=None, scripts_dir=None, duration_minutes=None,
                           mode="manual", allow_manual_submit=True, directory=None):
    """
    Ask for the participant's name and create a personal copy of the exam
    template next to it.  Never overwrites an existing copy.  Returns the copy
    path (str) or None.
    """
    from urllib.parse import quote

    directory = pathlib.Path(directory or os.getcwd())
    if template_name is None:
        found = _find_exam_templates(directory)
        if len(found) != 1:
            print("WARNING: expected exactly one exam template in %s, found %d." % (directory, len(found)))
            print("Open this notebook from the folder where the exam was delivered; "
                  "if this persists, tell the organiser. Nothing was created.")
            return None
        template_name = found[0].name
    template = directory / template_name
    if not template.is_file():
        print(f"WARNING: exam template '{template_name}' not found in {directory}.")
        print("Open the exam from its original location and run this cell again.")
        return None
    scripts_dir = scripts_dir or SCRIPTS_DIR

    name = slug = ""
    for _ in range(3):
        raw = input("Enter your full name (this creates your personal copy of the exam): ")
        name = " ".join("".join(c for c in raw if c.isprintable() or c.isspace()).split())[:80]
        slug = participant_slug(name)
        if slug:
            break
        print("Please enter a name containing at least one letter or digit.")
    else:
        print("No valid name entered. Run this cell again.")
        return None

    def _taken(stem):
        return ((directory / f"{stem}.ipynb").exists()
                or _state_path(f"{stem}.ipynb").exists())

    base = f"{template.stem}_{slug}"
    stem = base

    def _show_link(path):
        print(f"Your personal exam copy: {path}")
        try:
            rel = os.path.relpath(path, pathlib.Path.home())
            if not rel.startswith(".."):
                prefix = os.environ.get("JUPYTERHUB_SERVICE_PREFIX", "/").rstrip("/") + "/"
                url = prefix + "lab/tree/" + quote(rel)
                from IPython.display import HTML, display
                display(HTML(f'<a href="{url}" target="_blank">Open your personal exam copy</a>'))
        except Exception:
            pass

    def _copy_status(stem_):
        sp = pathlib.Path(_state_path(f"{stem_}.ipynb"))
        if not sp.exists():
            return "not opened yet"
        try:
            st = json.loads(sp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "in progress"
        return "already SUBMITTED (locked)" if st.get("submitted") else "in progress"

    def _ask(prompt, valid, hint):
        for _ in range(3):
            reply = input(prompt).strip().lower()
            if reply in valid:
                return reply
            print(f"'{reply}' is not a valid answer. {hint}")
        return None

    if _taken(base):
        copies = [base]
        k = 2
        while _taken(f"{base}-{k}"):
            copies.append(f"{base}-{k}")
            k += 1
        print(f"A personal copy already exists for the name '{name}'.")
        print("(Names that differ only in capitals, spaces or hyphens count as the same name.)")
        print("Existing copies:")
        for idx, s in enumerate(copies, 1):
            print(f"  {idx}. {s}.ipynb - {_copy_status(s)}")
        print("Do NOT type your name again. Answer with ONE of:")
        print("  a number from the list : continue that copy - it is yours")
        print("  N : you are a different person with the same name - create a new copy")
        print("  C : cancel, nothing is created")
        valid = {str(x) for x in range(1, len(copies) + 1)} | {"n", "c"}
        choice = _ask("Your answer (number, N or C): ", valid,
                      "Type a number from the list, N or C (not your name).")
        if choice is None:
            print("No valid answer. Nothing was created. Run this cell again.")
            return None
        if choice == "c":
            print("Cancelled. Nothing was created.")
            return None
        if choice != "n":
            chosen = copies[int(choice) - 1]
            existing = directory / f"{chosen}.ipynb"
            if not existing.exists():
                print("The copy file is missing. Tell the organiser; nothing was changed.")
                return None
            if _copy_status(chosen).startswith("already SUBMITTED"):
                print("This copy was already submitted and is locked; it cannot be edited.")
                print("If you need another attempt, tell the organiser.")
            else:
                print("Resuming your existing copy. Open it and run its first cell.")
            _show_link(str(existing))
            return str(existing)
        stem = f"{base}-{k}"

    target = directory / f"{stem}.ipynb"
    nb = json.loads(template.read_text(encoding="utf-8"))
    src = _individual_setup_source(target, name, scripts_dir, duration_minutes,
                                   mode, allow_manual_submit)
    replaced = 0
    for cell in nb.get("cells", []):
        if (cell.get("cell_type") == "code"
                and "assessment-setup" in cell.get("metadata", {}).get("tags", [])):
            cell["source"] = src.splitlines(keepends=True)
            cell["metadata"]["tags"] = ["assessment-setup"]
            cell["outputs"] = []
            cell["execution_count"] = None
            replaced += 1
    if replaced != 1:
        print("Template has no unique setup cell; nothing was created. Tell the organiser.")
        return None
    nb.setdefault("metadata", {})["assessment_individual"] = {
        "name": name,
        "slug": stem[len(template.stem) + 1:],
        "template": template_name,
        "created": datetime.datetime.utcnow().isoformat(),
        "account": os.environ.get("JUPYTERHUB_USER") or getpass.getuser(),
    }
    try:
        with open(target, "x", encoding="utf-8") as fh:
            json.dump(nb, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    except FileExistsError:
        print("A file with that name appeared meanwhile; nothing overwritten. Run the cell again.")
        return None
    except OSError as exc:
        try:
            target.unlink()
        except OSError:
            pass
        print(f"Could not create your copy: {exc}")
        return None

    print(f"Created your personal copy for: {name}")
    print("Open it, run its FIRST cell, and do the exam there (not in this template).")
    _show_link(str(target))
    return str(target)


_CURRENT_SESSION: Optional["AssessmentSession"] = None


class AssessmentSession:
    """
    Manages the full lifecycle of a single participant's assessment session.

    Typical usage (injected into the notebook's setup cell)::

        from assessment_tools import AssessmentSession
        _session = AssessmentSession.start(
            notebook_path="/home/jovyan/assessment_ml.ipynb",
            duration_minutes=30,
            mode="timed",
        )
    """

    def __init__(self, notebook_id: str, state: Dict[str, Any]):
        self.notebook_id = notebook_id
        self._state = state
        self._lock = threading.Lock()
        self._timer_thread: Optional[threading.Thread] = None

    # ── Class-level registry ─────────────────────────────────────────────────

    @classmethod
    def get_current(cls) -> Optional["AssessmentSession"]:
        """Return the session that is active in this kernel, or None."""
        return _CURRENT_SESSION

    @classmethod
    def start(
        cls,
        notebook_path: Optional[str] = None,
        duration_minutes: Optional[int] = None,
        mode: str = "manual",
        allow_manual_submit: bool = True,
        participant_name: Optional[str] = None,
    ) -> "AssessmentSession":
        """
        Initialise (or resume) a session for the current user.

        Parameters
        ----------
        notebook_path:
            Absolute path to the running ``.ipynb`` file.  When omitted the
            value of the ``ASSESSMENT_NOTEBOOK`` env-var is used, then a best-
            effort auto-detection via ``ipykernel``.
        duration_minutes:
            Exam time-limit in minutes.  ``None`` means unlimited.
        mode:
            ``"timed"`` – background countdown; ``"manual"`` – explicit submit.
        allow_manual_submit:
            When ``True`` the participant can call ``_session.submit()`` before
            the timer fires.
        """
        global _CURRENT_SESSION

        # Resolve notebook path
        if notebook_path is None:
            notebook_path = os.environ.get("ASSESSMENT_NOTEBOOK")
        if notebook_path is None:
            notebook_path = cls._detect_notebook_path()

        notebook_id = pathlib.Path(notebook_path).name if notebook_path else "unknown_notebook"
        username = (os.environ.get("ASSESSMENT_USERNAME")
                    or os.environ.get("JUPYTERHUB_USER")
                    or getpass.getuser())

        state = _load_state(notebook_id)

        # Per-individual copies: remember exactly which file belongs to this
        # session so that submit() never has to guess the notebook.
        if notebook_path:
            state["notebook_path"] = os.path.abspath(os.path.expanduser(notebook_path))
        if participant_name and not state.get("participant"):
            state["participant"] = participant_name
            state["participant_slug"] = participant_slug(participant_name)
        if (participant_name or state.get("participant")) and not state.get("participant_email"):
            state["participant_email"] = input(
                "Enter your email address for your personal assessment record: "
            ).strip()
        if notebook_path or participant_name:
            _save_state(notebook_id, state)

        # First-time initialisation
        if state["start_time"] is None:
            state["username"] = username
            state["start_time"] = datetime.datetime.utcnow().isoformat()
            state["mode"] = mode
            state["duration_minutes"] = duration_minutes
            _save_state(notebook_id, state)
            logger.info("Session started for %s | notebook=%s | mode=%s | duration=%s min",
                        username, notebook_id, mode, duration_minutes)
        else:
            logger.info("Session resumed for %s | notebook=%s", username, notebook_id)

        session = cls(notebook_id, state)
        _CURRENT_SESSION = session

        # Launch in-process timer for timed mode
        if mode == "timed" and duration_minutes and not state["submitted"]:
            session._start_timer()

        # Also fork the external watchdog daemon (belt-and-suspenders)
        cls._spawn_watchdog(notebook_path or "", username)

        return session

    # ── Timer ────────────────────────────────────────────────────────────────

    def _start_timer(self) -> None:
        """Start a background thread that fires when the exam time expires."""
        elapsed = self._elapsed_seconds()
        limit = (self._state["duration_minutes"] or 0) * 60
        remaining = max(0, limit - elapsed)
        if remaining == 0:
            self._on_time_expired()
            return

        def _run():
            time.sleep(remaining)
            self._on_time_expired()

        self._timer_thread = threading.Thread(target=_run, daemon=True, name="assessment-timer")
        self._timer_thread.start()
        logger.info("Timer armed: %.0f seconds remaining.", remaining)

    def _on_time_expired(self) -> None:
        """Callback when the countdown reaches zero."""
        if self._state.get("submitted"):
            return
        logger.warning("⏰  Time expired for %s — triggering auto-submission.", self._state["username"])
        print("\n" + "═" * 60)
        print("⏰  TIME'S UP — Your exam is being submitted automatically.")
        print("═" * 60 + "\n")
        self.submit(auto=True)

    # ── Public API ───────────────────────────────────────────────────────────

    def submit(self, auto: bool = False) -> None:
        """
        Finalise the assessment: save state, harvest notebook to the submissions
        directory, and lock the file so it cannot be edited further.
        """
        with self._lock:
            if self._state.get("submitted"):
                print("ℹ️  Your exam has already been submitted.")
                return

            self._state["submitted"] = True
            self._state["submission_time"] = datetime.datetime.utcnow().isoformat()
            _save_state(self.notebook_id, self._state)

            # Determine notebook path.  Individual copies use the path recorded
            # at start(); never fall back to "newest notebook" for them.
            nb_path = self._state.get("notebook_path")
            if not (nb_path and os.path.exists(nb_path)):
                if self._state.get("participant"):
                    nb_path = None
                else:
                    nb_path = os.environ.get("ASSESSMENT_NOTEBOOK") or self._detect_notebook_path()
            harvested = False
            if nb_path:
                harvested = self._harvest(nb_path)
                self._lock_notebook(nb_path)

            tag = "AUTO" if auto else "MANUAL"
            logger.info("[%s] Submission complete for %s", tag, self._state["username"])
            print("\n✅  " + ("Submission recorded.  Your work has been saved securely." if harvested else "Submission recorded locally, but the archive copy failed - tell the organiser."))
            print(f"    Username  : {self._state['username']}")
            print(f"    Submitted : {self._state['submission_time']} UTC")

    def status_message(self) -> str:
        """Return a human-readable status banner for display in the notebook."""
        state = self._state
        lines = [
            "╔══════════════════════════════════════════════════════╗",
            f"║  Assessment Session Active                           ║",
            f"║  User     : {state['username']:<40}║",
            f"║  Mode     : {state['mode']:<40}║",
        ]
        if state["duration_minutes"]:
            rem = self._remaining_minutes()
            lines.append(f"║  Time left: {rem:>3} min of {state['duration_minutes']:<30}║")
        lines.append("╚══════════════════════════════════════════════════════╝")
        return "\n".join(lines)

    def get_run_count(self, cell_id: str) -> int:
        """Return how many times *cell_id* has been executed so far."""
        with self._lock:
            state = _load_state(self.notebook_id)   # always re-read to stay current
            self._state = state
            return state["cell_runs"].get(cell_id, 0)

    def increment_run_count(self, cell_id: str) -> int:
        """Increment the execution counter for *cell_id* and persist it."""
        with self._lock:
            state = _load_state(self.notebook_id)
            state["cell_runs"][cell_id] = state["cell_runs"].get(cell_id, 0) + 1
            _save_state(self.notebook_id, state)
            self._state = state
            return state["cell_runs"][cell_id]

    def record_answer(self, cell_id: str, answer: Any) -> None:
        """Persist a participant's answer for a Q&A or open-question cell."""
        with self._lock:
            state = _load_state(self.notebook_id)
            state["cell_answers"][cell_id] = {
                "answer": str(answer),
                "timestamp": datetime.datetime.utcnow().isoformat(),
            }
            _save_state(self.notebook_id, state)
            self._state = state

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _elapsed_seconds(self) -> float:
        start = self._state.get("start_time")
        if not start:
            return 0.0
        t = datetime.datetime.fromisoformat(start)
        return (datetime.datetime.utcnow() - t).total_seconds()

    def _remaining_minutes(self) -> int:
        dur = (self._state.get("duration_minutes") or 0) * 60
        return max(0, int((dur - self._elapsed_seconds()) / 60))

    def _harvest(self, nb_path: str) -> bool:
        """Copy the notebook to the instructor's submission harvest directory."""
        username = self._state["username"]
        dest_dir = pathlib.Path(HARVEST_DIR) / username
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
            dest_name = f"{pathlib.Path(nb_path).stem}_{timestamp}.ipynb"
            shutil.copy2(nb_path, dest_dir / dest_name)
            # Also copy the state file for auditing
            shutil.copy2(str(_state_path(self.notebook_id)), dest_dir / f"{dest_name}.state.json")
            logger.info("Notebook harvested to %s", dest_dir / dest_name)
            return True
        except OSError as exc:
            logger.error("Could not write to harvest dir %s: %s", dest_dir, exc)
            return False

    def _lock_notebook(self, nb_path: str) -> None:
        """Make the notebook read-only (chmod 444) after submission."""
        try:
            os.chmod(nb_path, 0o444)
            logger.info("Notebook locked read-only (chmod 444): %s", nb_path)
        except PermissionError as exc:
            logger.error("Could not lock notebook %s: %s", nb_path, exc)

    @staticmethod
    def _detect_notebook_path() -> Optional[str]:
        """
        Best-effort detection of the current notebook path.
        Works with ipykernel ≥ 6 and the ``__session__`` variable
        injected by recent JupyterLab / JupyterHub builds.
        """
        # 1. ipykernel connection-file heuristic
        try:
            import ipykernel
            conn = ipykernel.get_connection_file()
            # connection files are like: kernel-<UUID>.json
            # we can't directly get the .ipynb from them, so fall through
        except Exception:
            pass

        # 2. Environment variable set by our generator at notebook-open time
        nb = os.environ.get("ASSESSMENT_NOTEBOOK")
        if nb and pathlib.Path(nb).exists():
            return nb

        # 3. Scan the user's home for the most recently modified .ipynb
        home = pathlib.Path.home()
        exam_dir = home / "assessment"
        search_dir = exam_dir if exam_dir.is_dir() else home
        candidates = sorted(search_dir.glob("*.ipynb"), key=os.path.getmtime, reverse=True)
        return str(candidates[0]) if candidates else None

    @staticmethod
    def _spawn_watchdog(notebook_path: str, username: str) -> None:
        """Fork the external watchdog daemon if available (non-blocking)."""
        watchdog = pathlib.Path(SCRIPTS_DIR) / "exam_watchdog.py"
        if not watchdog.exists():
            return
        try:
            subprocess.Popen(
                [sys.executable, str(watchdog),
                 "--notebook", notebook_path,
                 "--username", username],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.debug("Watchdog daemon spawned for %s", username)
        except Exception as exc:
            logger.debug("Could not spawn watchdog: %s", exc)


# ═══════════════════════════════════════════════════════════════════════════════
# @limit_executions decorator
# ═══════════════════════════════════════════════════════════════════════════════

def limit_executions(cell_id: str, max_runs: int) -> Callable:
    """
    Decorator factory that caps how many times a cell's function may execute.

    Usage::

        @limit_executions("q3", max_runs=3)
        def solve_q3():
            features = ["X1", "X2", "X1_sq"]   # student code
            return validate_assertion("q3", '"X1_sq" in features', locals())

        solve_q3()

    Parameters
    ----------
    cell_id:
        Unique identifier for the cell (matches the ``id`` in the YAML definition).
    max_runs:
        Maximum number of times the wrapped function may be called.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            session = AssessmentSession.get_current()
            if session is None:
                print("⚠️  No active session found.  Please run the setup cell first (Cell 1).")
                return None

            if session._state.get("submitted"):
                print("🔒  Your exam has been submitted.  This cell is now locked.")
                return None

            runs = session.get_run_count(cell_id)
            if runs >= max_runs:
                print(f"🚫  Cell '{cell_id}' has reached its limit of {max_runs} run(s).")
                print(f"    Your most recent recorded answer stands.")
                return None

            result = func(*args, **kwargs)
            new_count = session.increment_run_count(cell_id)
            remaining = max_runs - new_count
            if remaining > 0:
                print(f"ℹ️   Runs used for '{cell_id}': {new_count}/{max_runs}  "
                      f"({remaining} remaining)")
            else:
                print(f"⚠️   '{cell_id}': All {max_runs} run(s) used — this cell is now locked.")
            return result

        return wrapper
    return decorator


# ═══════════════════════════════════════════════════════════════════════════════
# Cell-type helpers
# ═══════════════════════════════════════════════════════════════════════════════

def check_answer(
    cell_id: str,
    given: str,
    correct: str,
    options: Optional[list] = None,
    case_sensitive: bool = False,
) -> bool:
    """
    Validate a Q&A answer, print feedback, and log the response.

    Parameters
    ----------
    cell_id:
        Cell identifier used for state logging.
    given:
        The participant's answer string.
    correct:
        The expected correct answer.
    options:
        When provided, checks that *given* is one of the allowed options.
    case_sensitive:
        Default ``False`` — comparisons are case-folded.

    Returns
    -------
    bool
        ``True`` if the answer is correct.
    """
    session = AssessmentSession.get_current()

    # Normalise
    g = given.strip() if case_sensitive else given.strip().lower()
    c = correct.strip() if case_sensitive else correct.strip().lower()

    # Option validation
    if options:
        normalised_options = [o.strip() if case_sensitive else o.strip().lower() for o in options]
        if g not in normalised_options:
            print(f"❌  '{given}' is not one of the allowed options: {options}")
            if session:
                session.record_answer(cell_id, given)
            return False

    if g == c:
        print(f"✅  Correct!  Your answer '{given}' is right.")
        logger.info("[%s] Correct answer recorded for cell %s.", getpass.getuser(), cell_id)
        if session:
            session.record_answer(cell_id, given)
        return True
    else:
        print(f"❌  Incorrect.  Your answer '{given}' was recorded.")
        logger.info("[%s] Incorrect answer for cell %s: '%s'.", getpass.getuser(), cell_id, given)
        if session:
            session.record_answer(cell_id, given)
        return False


def validate_assertion(
    cell_id: str,
    assertion: str,
    local_vars: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Evaluate a Python assertion string against the current local scope.

    Parameters
    ----------
    cell_id:
        Cell identifier for logging.
    assertion:
        A Python expression string that should evaluate to truthy, e.g.
        ``'"X1_sq" in features'``.
    local_vars:
        ``locals()`` from the calling scope, so variables are accessible.

    Returns
    -------
    bool
        ``True`` if the assertion passes.
    """
    session = AssessmentSession.get_current()
    ns = dict(local_vars or {})
    try:
        result = bool(eval(assertion, {}, ns))  # noqa: S307 — controlled input from YAML
    except Exception as exc:
        print(f"⚠️   Assertion error — could not evaluate: {assertion!r}")
        print(f"    Details: {exc}")
        if session:
            session.record_answer(cell_id, f"ERROR: {exc}")
        return False

    if result:
        print(f"✅  Assertion passed: {assertion}")
        logger.info("[%s] Assertion passed for cell %s.", getpass.getuser(), cell_id)
    else:
        print(f"❌  Assertion failed: {assertion}")
        logger.info("[%s] Assertion failed for cell %s.", getpass.getuser(), cell_id)

    if session:
        session.record_answer(cell_id, f"assertion={'PASS' if result else 'FAIL'}")
    return result


def record_choice(
    cell_id: str,
    given: Any,
    options: Optional[list] = None,
) -> None:
    """
    Record a Q&A answer WITHOUT grading it (exam mode).

    No correct/incorrect feedback and no expected value are shown or returned;
    grading happens later on the organiser side.  When *options* is given,
    the answer must be one of them (case-insensitive) or it is not recorded.
    """
    text = "" if given is None else str(given).strip()
    if not text:
        print("⚠️   No answer recorded — please set the `answer` variable first.")
        return None

    if options:
        allowed = {str(o).strip().lower(): str(o).strip() for o in options}
        if text.lower() not in allowed:
            print(f"⚠️   '{text}' is not one of the allowed options: {list(allowed.values())}. "
                  "Nothing was recorded.")
            return None
        text = allowed[text.lower()]

    session = AssessmentSession.get_current()
    if session:
        session.record_answer(cell_id, text)
    print(f"📝  Answer '{text}' recorded for '{cell_id}'. Answers are not graded during the exam.")
    logger.info("[%s] Answer recorded for cell %s.", getpass.getuser(), cell_id)
    return None


_PROBE_TIMEOUT_SEC = 2
_PROBE_FORMAT = 1


class _ProbeTimeout(BaseException):
    """Raised by the SIGALRM guard when a probe runs too long."""


def _json_native(value: Any):
    """Return (ok, converted).  Only JSON-native data is accepted (tuples become lists)."""
    import math
    if value is None or isinstance(value, (bool, int, str)):
        return True, value
    if isinstance(value, float):
        return (True, value) if math.isfinite(value) else (False, None)
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            ok, conv = _json_native(item)
            if not ok:
                return False, None
            out.append(conv)
        return True, out
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                return False, None
            ok, conv = _json_native(item)
            if not ok:
                return False, None
            out[key] = conv
        return True, out
    return False, None


def _run_probes(local_vars, probes, probe_setup):
    """
    Evaluate each probe expression against a copy of the participant's cell
    locals, in order.  Results are data only; nothing is judged here.
    """
    import contextlib
    import io
    import signal

    namespace = {k: v for k, v in (local_vars or {}).items() if not k.startswith("__")}
    can_alarm = (hasattr(signal, "setitimer")
                 and threading.current_thread() is threading.main_thread())

    def _on_alarm(signum, frame):
        raise _ProbeTimeout()

    def _guarded(fn):
        previous = None
        if can_alarm:
            previous = signal.signal(signal.SIGALRM, _on_alarm)
            signal.setitimer(signal.ITIMER_REAL, _PROBE_TIMEOUT_SEC)
        try:
            return fn()
        finally:
            if can_alarm:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, previous)

    results = []
    setup_error = None
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        if probe_setup:
            try:
                _guarded(lambda: exec(compile(probe_setup, "<probe_setup>", "exec"), namespace))
            except (Exception, _ProbeTimeout) as exc:
                setup_error = type(exc).__name__
        for expr in probes:
            entry = {"probe": expr}
            if setup_error:
                entry["status"] = "setup_error"
            else:
                try:
                    value = _guarded(lambda: eval(compile(expr, "<probe>", "eval"), namespace))
                    try:
                        ok, conv = _json_native(value)
                    except RecursionError:
                        ok, conv = False, None
                    if ok:
                        entry["status"] = "ok"
                        entry["value"] = conv
                    else:
                        entry["status"] = "unserializable"
                        entry["type"] = type(value).__name__
                except _ProbeTimeout:
                    entry["status"] = "timeout"
                except Exception as exc:
                    entry["status"] = "error"
                    entry["error"] = type(exc).__name__
            results.append(entry)
    return {"results": results, "setup_error": setup_error, "timeout_guard": can_alarm}


def record_code(cell_id: str, local_vars: Optional[Dict[str, Any]] = None,
                probes: Optional[list] = None, probe_setup: Optional[str] = None) -> None:
    """
    Record what a participant's code produced, WITHOUT grading it (exam mode).

    Without ``probes`` (old exams): a snapshot of truncated ``repr`` strings.
    With ``probes``: the snapshot plus the recorded outputs of each probe
    expression evaluated against the participant's cell locals.  The expected
    values live only in the organiser's answer model; the grader compares
    recorded outputs there.  Nothing about correctness is shown here.
    """
    snapshot: Dict[str, str] = {}
    for name, value in (local_vars or {}).items():
        if name.startswith("_"):
            continue
        try:
            text = repr(value)
        except Exception:
            text = "<unrepresentable>"
        snapshot[name] = text if len(text) <= 300 else text[:300] + "…"

    payload: Any = snapshot
    n_checks = 0
    if probes:
        outcome = _run_probes(local_vars, list(probes), probe_setup)
        n_checks = len(outcome["results"])
        payload = {"probe_format": _PROBE_FORMAT, "snapshot": snapshot,
                   "probes": outcome["results"], "setup_error": outcome["setup_error"],
                   "timeout_guard": outcome["timeout_guard"]}

    session = AssessmentSession.get_current()
    if session:
        session.record_answer(cell_id, json.dumps(payload, sort_keys=True, ensure_ascii=False))
    extra = f", {n_checks} check(s) run" if n_checks else ""
    print(f"📝  Code for '{cell_id}' recorded ({len(snapshot)} variable(s){extra}). "
          "Answers are not graded during the exam.")
    logger.info("[%s] Code answer recorded for cell %s.", getpass.getuser(), cell_id)
    return None


def save_text_answer(cell_id: str, text: str) -> None:
    """
    Persist a free-text open-question answer to the session state.

    Parameters
    ----------
    cell_id:
        Cell identifier matching the YAML definition ``id``.
    text:
        The participant's written response string.
    """
    if not text or text.strip() in ("", "<Type your answer here>"):
        print("⚠️   No answer recorded — please replace the placeholder text.")
        return

    session = AssessmentSession.get_current()
    if session:
        session.record_answer(cell_id, text)

    print(f"📝  Open answer for '{cell_id}' saved ({len(text.strip())} characters).")
    logger.info("[%s] Open answer recorded for cell %s.", getpass.getuser(), cell_id)
