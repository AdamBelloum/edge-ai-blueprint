#!/usr/bin/env python3
"""Deterministic organiser-side grading for archived assessment submissions."""

import argparse
import ast
import csv
import hashlib
import io
import json
import math
import os
import re
import stat
import unicodedata
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML is required; activate the project virtual environment first.") from exc


QUESTION_ID = re.compile(r"^(qa|c|oq)\d+$")
QUESTION_TAG = re.compile(r"^question-(qa\d+|c\d+|oq\d+)$")
MODEL_HEADING = re.compile(r"^### `([^`]+)`\s*$", re.M)
MISSING = object()
MAX_NOTEBOOK_BYTES = 64 * 1024 * 1024
MAX_SIDECAR_BYTES = 16 * 1024 * 1024


class GradeError(Exception):
    pass


def read_json_file(path, limit):
    """Read a regular, non-symlink JSON file with a size limit."""
    path = Path(path)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError("not a regular file")
    if info.st_size > limit:
        raise ValueError("file exceeds size limit")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_model(path):
    text = Path(path).read_text(encoding="utf-8")
    headings = list(MODEL_HEADING.finditer(text))
    model = {}
    warnings = []

    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        block = text[heading.end():end]
        key_match = re.search(
            r"#### `answer_key`.*?```ya?ml\s*(.*?)```",
            block,
            re.S,
        )
        if not key_match:
            continue

        qid = heading.group(1).split("_", 1)[0]
        if not QUESTION_ID.fullmatch(qid):
            raise GradeError("Unrecognised graded question ID in answer model.")
        if qid in model:
            raise GradeError("Duplicate question ID in answer model: " + qid)

        type_match = re.search(
            r"(?m)^\s*-\s+\*\*type:\*\*\s*`?([A-Za-z]+)`?",
            block,
        )
        points_match = re.search(
            r"(?m)^\s*-\s+\*\*points:\*\*\s*`?(\d+)`?",
            block,
        )
        if not type_match or not points_match:
            raise GradeError("Missing type or points metadata for " + qid)

        try:
            answer_key = yaml.safe_load(key_match.group(1))
        except yaml.YAMLError as exc:
            raise GradeError("Invalid answer-key YAML for " + qid) from exc
        if not isinstance(answer_key, dict):
            raise GradeError("Answer key must be a YAML mapping for " + qid)

        qtype = type_match.group(1).lower()
        expected_type = "qa" if qid.startswith("qa") else (
            "code" if qid.startswith("c") else "cloze"
        )
        if qtype != expected_type:
            raise GradeError("Question type disagrees with ID for " + qid)

        model[qid] = {
            "id": qid,
            "type": qtype,
            "points": int(points_match.group(1)),
            "key": answer_key,
        }
        if qtype == "cloze" and re.search(r"(?m)^\s*-\s+\*\*points_per_blank:", block):
            note = "Cloze scoring is all-or-nothing; model points_per_blank metadata is ignored."
            if note not in warnings:
                warnings.append(note)

    if not model:
        raise GradeError("No graded answer-key blocks were found in the model.")
    return model, warnings


def literal_string_list(node):
    try:
        value = ast.literal_eval(node)
    except Exception:
        return None
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    return None


def parse_exam(path, model):
    try:
        notebook = read_json_file(path, MAX_NOTEBOOK_BYTES)
    except Exception as exc:
        raise GradeError("Could not read the exam notebook: " + str(exc)) from exc

    cells = notebook.get("cells")
    if not isinstance(cells, list):
        raise GradeError("Exam notebook has no valid cells list.")

    selected = {}
    unknown_tags = set()

    for cell in cells:
        tags = cell.get("metadata", {}).get("tags", [])
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        if not isinstance(source, str):
            source = ""

        for tag in tags:
            match = QUESTION_TAG.fullmatch(str(tag))
            if match:
                qid = match.group(1)
                selected.setdefault(qid, {
                    "id": qid,
                    "cells": [],
                    "options": None,
                    "valid": None,
                    "blank_numbers": set(),
                    "has_probes": False,
                    "metadata_error": None,
                })
                selected[qid]["cells"].append((cell.get("cell_type"), source))
            elif str(tag).startswith("question-") and not str(tag).startswith("question-m"):
                unknown_tags.add(str(tag))

    if unknown_tags:
        raise GradeError("Exam notebook contains unrecognised question tags.")

    if not selected:
        raise GradeError("No graded question tags found in the exam notebook.")
    if set(selected) - set(model):
        raise GradeError("Exam notebook has question IDs absent from the answer model.")

    for qid, details in selected.items():
        qtype = model[qid]["type"]
        for cell_type, source in details["cells"]:
            if cell_type != "code":
                continue
            details["blank_numbers"].update(
                int(number)
                for number in re.findall(r"(?m)^\s*blank_(\d+)\s*=", source)
            )
            try:
                tree = ast.parse(source)
            except SyntaxError:
                details["metadata_error"] = "QUESTION_CELL_PARSE_ERROR"
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "valid":
                            values = literal_string_list(node.value)
                            if values is not None:
                                details["valid"] = values

                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue

                if node.func.id == "record_code":
                    if any(keyword.arg == "probes" for keyword in node.keywords):
                        details["has_probes"] = True

                if node.func.id == "record_choice" and node.args:
                    try:
                        first_arg = ast.literal_eval(node.args[0])
                    except Exception:
                        continue
                    if first_arg != qid:
                        continue
                    options_node = next(
                        (keyword.value for keyword in node.keywords
                         if keyword.arg == "options"),
                        None,
                    )
                    if options_node is not None:
                        options = literal_string_list(options_node)
                        if options is not None:
                            if details["options"] is not None and details["options"] != options:
                                details["metadata_error"] = "INCONSISTENT_OPTIONS"
                            details["options"] = options

        if qtype == "cloze":
            blanks = model[qid]["key"].get("blanks")
            if not isinstance(blanks, dict) or not blanks:
                details["metadata_error"] = "INVALID_MODEL_BLANKS"
            else:
                expected_numbers = set()
                for blank in blanks:
                    try:
                        expected_numbers.add(int(blank))
                    except (TypeError, ValueError):
                        details["metadata_error"] = "INVALID_MODEL_BLANKS"
                if details["blank_numbers"] != expected_numbers:
                    details["metadata_error"] = "BLANK_COUNT_MISMATCH"
                if not details["valid"]:
                    details["metadata_error"] = "WORD_BANK_NOT_FOUND"

        if qtype == "qa" and "correct_letter" in model[qid]["key"]:
            if not details["options"]:
                details["metadata_error"] = "OPTIONS_NOT_FOUND"

    return selected


def safe_identity(state, fallback):
    if isinstance(state, dict):
        for field in ("participant", "participant_slug"):
            value = state.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return fallback


def safe_participant_name(state):
    """Return only the explicitly supplied name, never an identity fallback."""
    if isinstance(state, dict):
        value = state.get("participant")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def safe_email(state):
    if isinstance(state, dict):
        value = state.get("participant_email")
        if isinstance(value, str):
            return value.strip()
    return ""


def stem_and_timestamp(path, state=None):
    """Parse finalize_collected.py's filename suffix; never infer order from sidecar time."""
    name = Path(path).name
    if name.endswith(".state.json"):
        name = name[:-len(".state.json")]
    if name.endswith(".ipynb"):
        name = name[:-len(".ipynb")]

    match = re.fullmatch(
        r"(?P<prefix>.+_)(?P<day>[0-9]{8})"
        r"(?:_(?P<hhmm>[0-9]{4})(?:_(?P<sequence>[0-9]{1,2}))?)?",
        name,
    )
    if not match:
        return name, ("", -1, -1), "UNRECOGNISED_FINALIZED_FILENAME"

    prefix = match.group("prefix")
    day = match.group("day")
    hhmm = match.group("hhmm")
    sequence_text = match.group("sequence")
    try:
        datetime.strptime(day, "%Y%m%d")
        if hhmm is None:
            return prefix, (day, -1, -1), None
        datetime.strptime(day + hhmm, "%Y%m%d%H%M")
        sequence = int(sequence_text) if sequence_text is not None else 1
        if not 1 <= sequence <= 99 or (sequence_text is not None and sequence < 2):
            raise ValueError("invalid filename sequence")
    except ValueError:
        return prefix, ("", -1, -1), "UNRECOGNISED_FINALIZED_FILENAME"

    return prefix, (day, int(hhmm), sequence), None


def notebook_tags(path):
    notebook = read_json_file(path, MAX_NOTEBOOK_BYTES)
    ids = set()
    unknown = set()
    for cell in notebook.get("cells", []):
        for tag in cell.get("metadata", {}).get("tags", []):
            tag = str(tag)
            match = QUESTION_TAG.fullmatch(tag)
            if match:
                ids.add(match.group(1))
            elif tag.startswith("question-") and not tag.startswith("question-m"):
                unknown.add(tag)
    return ids, unknown


def make_candidate(root, notebook_path, sidecar_path):
    state = None
    sidecar_error = None
    notebook_error = None
    tags = None
    unknown_tags = set()

    if sidecar_path is None:
        sidecar_error = "NO_SIDECAR"
    else:
        try:
            state = read_json_file(sidecar_path, MAX_SIDECAR_BYTES)
            if not isinstance(state, dict):
                raise ValueError("sidecar root is not a mapping")
        except Exception:
            sidecar_error = "INVALID_SIDECAR"

    if notebook_path is None:
        notebook_error = "NO_NOTEBOOK"
        stem_path = sidecar_path
    else:
        stem_path = notebook_path
        try:
            tags, unknown_tags = notebook_tags(notebook_path)
        except Exception:
            notebook_error = "INVALID_NOTEBOOK"

    stem, order, filename_error = stem_and_timestamp(stem_path)
    identity = safe_identity(state, stem.rstrip("_") or "(unknown)")

    return {
        "notebook": notebook_path,
        "sidecar": sidecar_path,
        "state": state,
        "identity": identity,
        "stem": stem,
        "order": order,
        "filename_error": filename_error,
        "tags": tags,
        "unknown_tags": unknown_tags,
        "notebook_error": notebook_error,
        "sidecar_error": sidecar_error,
        "ambiguous": False,
        "older_count": 0,
        "missing_from_latest": set(),
    }


def discover_submissions(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise GradeError("Submission input must be an existing, non-symlink directory.")

    notebooks = sorted(root.glob("*.ipynb"))
    sidecars = sorted(root.glob("*.ipynb.state.json"))
    paired_sidecars = set()
    candidates = []

    for notebook in notebooks:
        sidecar = Path(str(notebook) + ".state.json")
        if sidecar.exists() or sidecar.is_symlink():
            paired_sidecars.add(sidecar)
        else:
            sidecar = None
        candidates.append(make_candidate(root, notebook, sidecar))

    for sidecar in sidecars:
        if sidecar in paired_sidecars:
            continue
        candidates.append(make_candidate(root, None, sidecar))

    if not candidates:
        raise GradeError("No notebook or sidecar submissions found.")
    return candidates


def candidate_fingerprint(candidate):
    digest = hashlib.sha256()
    for path in (candidate["notebook"], candidate["sidecar"]):
        if path is None:
            digest.update(b"<missing>")
            continue
        try:
            digest.update(Path(path).read_bytes())
        except OSError:
            digest.update(str(path).encode("utf-8", "replace"))
    return digest.hexdigest()


def expected_answer_keys(qid, question):
    if question["type"] == "cloze":
        return {qid + "." + str(blank) for blank in question["key"].get("blanks", {})}
    return {qid}


def sidecar_answer_ids(candidate):
    state = candidate.get("state")
    if not isinstance(state, dict):
        return set()
    answers = state.get("cell_answers")
    return set(answers) if isinstance(answers, dict) else set()


def choose_latest(candidates):
    groups = {}
    for candidate in candidates:
        # The finalized filename prefix is stable across snapshots. Do not let
        # a sidecar's editable identity field split one participant's snapshots.
        groups.setdefault(candidate["stem"], []).append(candidate)

    chosen = []
    for group in groups.values():
        newest_order = max(item["order"] for item in group)
        top = [item for item in group if item["order"] == newest_order]
        fingerprints = {candidate_fingerprint(item) for item in top}
        latest = top[0]
        if len(fingerprints) > 1:
            latest["ambiguous"] = True
        older = [item for item in group if item is not latest]
        latest["older_count"] = len(older)

        previous_ids = set()
        for item in older:
            previous_ids.update(sidecar_answer_ids(item))
        latest["previous_ids"] = previous_ids
        chosen.append(latest)

    return sorted(chosen, key=lambda item: (item["identity"], item["stem"]))


def normalize_text(value):
    text = unicodedata.normalize("NFKC", value).casefold().strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"`":
        text = text[1:-1].strip()
    text = re.sub(r"\s+", " ", text)
    return text.rstrip(".").strip()


def canonical(value):
    if value is None:
        return ("null",)
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int):
        return ("number", value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite number")
        return ("number", int(value) if value.is_integer() else value)
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, list):
        return ("list", tuple(canonical(item) for item in value))
    if isinstance(value, dict):
        return ("dict", tuple(
            sorted((str(key), canonical(item)) for key, item in value.items())
        ))
    raise ValueError("not a JSON value")


def canonical_equal(left, right):
    try:
        return canonical(left) == canonical(right)
    except (TypeError, ValueError, RecursionError):
        return False


def answer_value(state, key):
    answers = state.get("cell_answers") if isinstance(state, dict) else None
    if not isinstance(answers, dict):
        return MISSING, "INVALID_CELL_ANSWERS"
    if key not in answers:
        return MISSING, None
    record = answers[key]
    if isinstance(record, dict):
        if "answer" not in record:
            return MISSING, "INVALID_ANSWER_RECORD"
        return record["answer"], None
    return record, None


def item_result(qid, question, status, awarded=None, reason=None):
    return {
        "id": qid,
        "type": question["type"],
        "points": question["points"],
        "status": status,
        "awarded": awarded,
        "reason": reason,
    }


def manual(qid, question, reason):
    return item_result(qid, question, "MANUAL", None, reason)


def grade_question(qid, question, exam_question, candidate, selected_ids):
    if candidate["ambiguous"]:
        return manual(qid, question, "AMBIGUOUS_LATEST_SNAPSHOT")
    if candidate.get("filename_error"):
        return manual(qid, question, candidate["filename_error"])
    if candidate["notebook_error"]:
        return manual(qid, question, candidate["notebook_error"])
    if candidate["sidecar_error"]:
        return manual(qid, question, candidate["sidecar_error"])
    if candidate["tags"] != set(selected_ids):
        return manual(qid, question, "NOTEBOOK_TAG_MISMATCH")
    if candidate["unknown_tags"]:
        return manual(qid, question, "NOTEBOOK_TAG_MISMATCH")
    if exam_question.get("metadata_error"):
        return manual(qid, question, exam_question["metadata_error"])
    if expected_answer_keys(qid, question) & candidate["missing_from_latest"]:
        return manual(qid, question, "ANSWER_MISSING_FROM_LATEST_SNAPSHOT")

    state = candidate["state"]
    if question["type"] == "code" and not exam_question["has_probes"]:
        return manual(qid, question, "NOTEBOOK_HAS_NO_PROBES")

    if question["type"] == "cloze":
        blanks = question["key"].get("blanks", {})
        expected_keys = [qid + "." + str(blank) for blank in blanks]
        records = {}
        for key in expected_keys:
            value, error = answer_value(state, key)
            if error:
                return manual(qid, question, error)
            records[key] = value
        missing = [key for key, value in records.items() if value is MISSING]
        if missing:
            return manual(qid, question, "NO_ANSWER" if len(missing) == len(records) else "PARTIAL_CLOZE")

        expected_number_keys = {str(blank) for blank in blanks}
        extra = {
            key for key in state["cell_answers"]
            if key.startswith(qid + ".") and key.split(".", 1)[1] not in expected_number_keys
        }
        if extra:
            return manual(qid, question, "MODEL_MISMATCH")

        valid = set(exam_question["valid"] or [])
        all_correct = True
        for key, value in records.items():
            if not isinstance(value, str):
                return manual(qid, question, "INVALID_VALUE")
            cleaned = value.strip().upper()
            if cleaned not in valid:
                return manual(qid, question, "INVALID_VALUE")
            blank = key.split(".", 1)[1]
            correct = str(blanks.get(blank, blanks.get(int(blank), ""))).strip().upper()
            all_correct = all_correct and cleaned == correct

        if all_correct:
            return item_result(qid, question, "CORRECT", question["points"])
        return item_result(qid, question, "INCORRECT", 0)

    value, error = answer_value(state, qid)
    if error:
        return manual(qid, question, error)
    if value is MISSING:
        return manual(qid, question, "NO_ANSWER")

    if question["type"] == "qa":
        key = question["key"]
        if "correct_letter" in key:
            if not isinstance(value, str):
                return manual(qid, question, "INVALID_VALUE")
            given = value.strip().upper()
            if given not in set(exam_question["options"] or []):
                return manual(qid, question, "INVALID_VALUE")
            correct = str(key["correct_letter"]).strip().upper()
            if given == correct:
                return item_result(qid, question, "CORRECT", question["points"])
            return item_result(qid, question, "INCORRECT", 0)

        if key.get("match") != "normalized_text" or not isinstance(key.get("accepted"), list):
            return manual(qid, question, "MODEL_MISMATCH")
        if not isinstance(value, str):
            return manual(qid, question, "INVALID_VALUE")
        accepted = {normalize_text(item) for item in key["accepted"] if isinstance(item, str)}
        if normalize_text(value) in accepted:
            return item_result(qid, question, "CORRECT", question["points"])
        return item_result(qid, question, "INCORRECT", 0)

    if question["type"] == "code":
        if not isinstance(value, str):
            return manual(qid, question, "INVALID_CODE_PAYLOAD")
        try:
            payload = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return manual(qid, question, "INVALID_CODE_PAYLOAD")
        key = question["key"]
        if not isinstance(payload, dict) or type(payload.get("probe_format")) is not int or payload.get("probe_format") != 1:
            return manual(qid, question, "OLD_OR_UNSUPPORTED_CODE_FORMAT")
        if payload.get("setup_error"):
            return manual(qid, question, "PROBE_SETUP_ERROR")
        if payload.get("timeout_guard") is not True:
            return manual(qid, question, "TIMEOUT_GUARD_UNAVAILABLE")
        if key.get("compare") != "json_canonical":
            return manual(qid, question, "MODEL_MISMATCH")

        expected = key.get("probes")
        actual = payload.get("probes")
        if not isinstance(expected, list) or not expected or not isinstance(actual, list):
            return manual(qid, question, "PROBE_DATA_MISSING")

        expected_map = {}
        actual_map = {}
        try:
            for probe in expected:
                expr = probe["probe"]
                if not isinstance(expr, str) or expr in expected_map:
                    return manual(qid, question, "MODEL_PROBE_MISMATCH")
                expected_map[expr] = probe["expected"]
            for probe in actual:
                expr = probe["probe"]
                if not isinstance(expr, str) or expr in actual_map:
                    return manual(qid, question, "RECORDED_PROBE_MISMATCH")
                actual_map[expr] = probe
        except (KeyError, TypeError):
            return manual(qid, question, "MALFORMED_PROBE_DATA")

        if set(expected_map) != set(actual_map):
            return manual(qid, question, "RECORDED_PROBE_MISMATCH")

        failed = False
        for expr, expected_value in expected_map.items():
            result = actual_map[expr]
            status = result.get("status")
            if status in ("error", "timeout", "unserializable"):
                failed = True
            elif status == "ok":
                if "value" not in result:
                    return manual(qid, question, "MALFORMED_PROBE_DATA")
                if not canonical_equal(result["value"], expected_value):
                    failed = True
            else:
                return manual(qid, question, "MALFORMED_PROBE_DATA")

        if failed:
            return item_result(qid, question, "INCORRECT", 0)
        return item_result(qid, question, "CORRECT", question["points"])

    return manual(qid, question, "UNSUPPORTED_QUESTION_TYPE")


def select_items(candidate, model):
    # Selected items come from the participant's own notebook.
    if candidate["notebook"] is None or candidate["notebook_error"]:
        return None, candidate["notebook_error"] or "NO_NOTEBOOK"
    try:
        return parse_exam(candidate["notebook"], model), None
    except Exception:
        return None, "NOTEBOOK_SELECTION_UNUSABLE"


def unusable_report(candidate, model_warnings, reason):
    warnings = list(model_warnings) + [
        "Selected items could not be determined (%s); the whole submission "
        "needs manual review." % reason
    ]
    if candidate["older_count"]:
        warnings.append(
            "Multiple finalized snapshots found; selected the newest by filename "
            "suffix order. Verify selection."
        )
    if candidate["ambiguous"]:
        warnings.append(
            "Newest snapshots share the same filename order but differ in content; "
            "verify selection."
        )
    whole = {
        "id": "(whole submission)", "status": "MANUAL", "reason": reason,
        "points": 0, "awarded": 0,
    }
    return {
        "identity": candidate["identity"],
        "participant_name": safe_participant_name(candidate.get("state")),
        "participant_email": safe_email(candidate.get("state")),
        "stem": candidate["stem"],
        "notebook": candidate["notebook"].name if candidate["notebook"] else "(missing)",
        "state": "INCOMPLETE",
        "outcome": "PENDING REVIEW",
        "correct_questions": 0,
        "gradable_questions": 0,
        "not_graded": True,
        "auto_score": 0,
        "auto_max": 0,
        "selected_max": 0,
        "manual_count": 1,
        "manual_items": [whole],
        "items": [whole],
        "warnings": warnings,
        "older_count": candidate["older_count"],
    }


def grade_candidate(candidate, model, model_warnings):
    selected, selection_error = select_items(candidate, model)
    if selected is None:
        return unusable_report(candidate, model_warnings, selection_error)
    selected_ids = set(selected)
    expected_keys = set()
    for qid in selected:
        expected_keys.update(expected_answer_keys(qid, model[qid]))
    candidate["missing_from_latest"] = (
        candidate.get("previous_ids", set()) - sidecar_answer_ids(candidate)
    ) & expected_keys

    results = [
        grade_question(qid, model[qid], selected[qid], candidate, selected_ids)
        for qid in sorted(selected)
    ]
    selected_max = sum(item["points"] for item in results)
    automatic = [item for item in results if item["status"] in ("CORRECT", "INCORRECT")]
    auto_score = sum(item["awarded"] for item in automatic)
    auto_max = sum(item["points"] for item in automatic)
    manual_items = [item for item in results if item["status"] == "MANUAL"]
    correct_questions = sum(item["status"] == "CORRECT" for item in automatic)
    gradable_questions = len(automatic)
    if manual_items or gradable_questions == 0:
        outcome = "PENDING REVIEW"
    elif 2 * correct_questions >= gradable_questions:
        outcome = "PASS"
    else:
        outcome = "NO PASS"
    warnings = list(model_warnings)

    if candidate["older_count"]:
        warnings.append(
            "Multiple finalized snapshots found; selected the newest by filename "
            "suffix order. Verify selection."
        )
    answer_ids = sidecar_answer_ids(candidate)
    expected = set()
    for qid in selected:
        expected.update(expected_answer_keys(qid, model[qid]))
    unknown = sorted(answer_ids - expected)
    if unknown:
        warnings.append("Unrecognised answer IDs in sidecar: " + ", ".join(unknown))
    if "c4" in selected:
        warnings.append(
            "c4 caveat: the model splits one four-row assertion into three probes; "
            "this may differ for participant code that handles rows jointly."
        )
    if any(model[qid]["type"] == "code" for qid in selected):
        warnings.append(
            "Code probes are visible in notebooks and sidecars are not tamper-proof."
        )

    return {
        "identity": candidate["identity"],
        "participant_name": safe_participant_name(candidate.get("state")),
        "participant_email": safe_email(candidate.get("state")),
        "stem": candidate["stem"],
        "notebook": candidate["notebook"].name if candidate["notebook"] else "(missing)",
        "state": "INCOMPLETE" if manual_items else "COMPLETE",
        "outcome": outcome,
        "correct_questions": correct_questions,
        "gradable_questions": gradable_questions,
        "auto_score": auto_score,
        "auto_max": auto_max,
        "selected_max": selected_max,
        "manual_count": len(manual_items),
        "manual_items": manual_items,
        "items": results,
        "warnings": warnings,
        "older_count": candidate["older_count"],
    }


def private_write(path, text):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def safe_label(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def render_report(report):
    lines = [
        "# Organiser grading report",
        "",
        "Participant: " + safe_label(report["identity"]),
        "Email: " + safe_label(report["participant_email"] or "(not provided)"),
        "Outcome: **" + report["outcome"] + "**",
        "Correct gradable questions: "
        + str(report["correct_questions"]) + " / "
        + str(report["gradable_questions"]),
        "Notebook: " + safe_label(report["notebook"]),
        "Assessment stem: " + safe_label(report["stem"]),
        "Status: **" + report["state"] + "**",
        ("Automatic score: not graded (manual review required)"
         if report.get("not_graded") else
         "Automatic score: " + str(report["auto_score"]) + " / " + str(report["auto_max"])),
        ("Selected maximum: unknown" if report.get("not_graded")
         else "Selected maximum: " + str(report["selected_max"])),
        "",
        "| Item | Result | Points |",
        "|---|---|---:|",
    ]
    for item in report["items"]:
        if item["status"] == "MANUAL":
            result = "MANUAL — " + item["reason"]
            points = ("n/a" if report.get("not_graded")
                      else "excluded (" + str(item["points"]) + " possible)")
        else:
            result = item["status"]
            points = str(item["awarded"]) + " / " + str(item["points"])
        lines.append(
            "| " + item["id"] + " | " + safe_label(result) + " | " + points + " |"
        )

    if report["warnings"]:
        lines.extend(["", "## Warnings"])
        lines.extend("- " + safe_label(warning) for warning in report["warnings"])
    lines.extend([
        "",
        "Expected answers and participant answer values are intentionally omitted.",
        "Sidecars are audit evidence, not tamper-proof records.",
        "",
    ])
    return "\n".join(lines)


def prepare_output(path, harvest):
    path = Path(path).expanduser()
    harvest_real = Path(harvest).resolve()
    output_real = path.resolve()
    try:
        if os.path.commonpath([str(harvest_real), str(output_real)]) == str(harvest_real):
            raise GradeError("Report output must be outside the submission directory.")
    except ValueError:
        pass

    if path.is_symlink():
        raise GradeError("Report output path must not be a symlink.")
    if path.exists():
        if not path.is_dir():
            raise GradeError("Report output exists and is not a directory.")
        if any(path.iterdir()):
            raise GradeError("Report output directory must be empty; refusing to overwrite files.")
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise GradeError("Existing report directory must be private (permissions 0700).")
    else:
        path.mkdir(parents=True, mode=0o700)
        os.chmod(path, 0o700)
    return path


def write_reports(reports, output_dir):
    buffer = io.StringIO(newline="")
    fields = [
        "participant", "participant_name", "participant_email",
        "assessment_stem", "notebook", "status",
        "outcome", "correct_questions", "gradable_questions",
        "auto_score", "auto_max", "selected_max", "manual_count",
        "manual_items", "warnings",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()

    for report in reports:
        manual_text = "; ".join(
            item["id"] + ":" + item["reason"] for item in report["manual_items"]
        )
        writer.writerow({
            "participant": report["identity"],
            "participant_name": report["participant_name"],
            "participant_email": report["participant_email"],
            "assessment_stem": report["stem"],
            "notebook": report["notebook"],
            "status": report["state"],
            "outcome": report["outcome"],
            "correct_questions": report["correct_questions"],
            "gradable_questions": report["gradable_questions"],
            "auto_score": report["auto_score"],
            "auto_max": report["auto_max"],
            "selected_max": report["selected_max"],
            "manual_count": report["manual_count"],
            "manual_items": manual_text,
            "warnings": "; ".join(report["warnings"]),
        })

        key = report["identity"] + "\0" + report["stem"]
        suffix = hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()[:16]
        private_write(output_dir / ("report-" + suffix + ".md"), render_report(report))

    private_write(output_dir / "summary.csv", buffer.getvalue())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="private answer-model file")
    parser.add_argument("--harvest", required=True, help="collected submissions directory")
    parser.add_argument("--out", required=True, help="new, private report directory outside --harvest")
    parser.add_argument("--user", help="grade only the exact self-entered participant identifier")
    args = parser.parse_args()

    try:
        model, model_warnings = parse_model(args.model)
        candidates = discover_submissions(args.harvest)
        candidates = choose_latest(candidates)
        if args.user:
            # Filter after choosing each submission's latest snapshot, so a changed
            # sidecar identity cannot cause an older snapshot to be graded instead.
            candidates = [item for item in candidates if item["identity"] == args.user]
            if not candidates:
                raise GradeError("No matching submission found for --user.")
        reports = [
            grade_candidate(candidate, model, model_warnings)
            for candidate in candidates
        ]
        output_dir = prepare_output(args.out, args.harvest)
        write_reports(reports, output_dir)
    except (GradeError, OSError, ValueError, yaml.YAMLError) as exc:
        parser.error(str(exc))

    complete = sum(report["state"] == "COMPLETE" for report in reports)
    incomplete = len(reports) - complete
    print("Graded submission records: %d" % len(reports))
    print("Complete: %d; incomplete/manual review required: %d" % (complete, incomplete))
    print("Private reports written to: %s" % output_dir)


if __name__ == "__main__":
    main()
