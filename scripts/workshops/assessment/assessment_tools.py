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
HARVEST_DIR:  str = os.environ.get("ASSESSMENT_HARVEST_DIR", "/opt/workshop-assessment/submissions")
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
        username = os.environ.get("ASSESSMENT_USERNAME") or getpass.getuser()

        state = _load_state(notebook_id)

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

            # Determine notebook path
            nb_path = os.environ.get("ASSESSMENT_NOTEBOOK") or self._detect_notebook_path()
            if nb_path:
                self._harvest(nb_path)
                self._lock_notebook(nb_path)

            tag = "AUTO" if auto else "MANUAL"
            logger.info("[%s] Submission complete for %s", tag, self._state["username"])
            print("\n✅  Submission recorded.  Your work has been saved securely.")
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

    def _harvest(self, nb_path: str) -> None:
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
        except PermissionError as exc:
            logger.error("Could not write to harvest dir %s: %s", dest_dir, exc)

    def _lock_notebook(self, nb_path: str) -> None:
        """Set notebook permissions to 000 (inaccessible) after submission."""
        try:
            os.chmod(nb_path, 0o000)
            logger.info("Notebook locked (chmod 000): %s", nb_path)
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
        candidates = sorted(home.glob("*.ipynb"), key=os.path.getmtime, reverse=True)
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


def record_code(cell_id: str, local_vars: Optional[Dict[str, Any]] = None) -> None:
    """
    Record a snapshot of the variables a participant's code produced, WITHOUT
    grading it (exam mode).  Values are stored as truncated ``repr`` strings.
    The submitted notebook itself (harvested at submission) holds the code.
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

    session = AssessmentSession.get_current()
    if session:
        session.record_answer(cell_id, json.dumps(snapshot, sort_keys=True, ensure_ascii=False))
    print(f"📝  Code for '{cell_id}' recorded ({len(snapshot)} variable(s)). "
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
