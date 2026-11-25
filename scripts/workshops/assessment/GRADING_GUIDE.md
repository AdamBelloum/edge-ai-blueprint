# Assessment authoring and grading: organiser guide

**Organiser-only.** Keep the question list, answer model, generated exam notebook and grading reports private. Do not commit them to Git or share them with participants.

## The pieces and the workflow

The assessment has two authoring files and two main scripts. The participant notebook also uses the assessment runtime, and collection/finalization happens before grading.

| Piece | Purpose |
|---|---|
| Question list (`.yaml`) | Questions, options, word banks, code starters and visible probe expressions |
| Answer model | Expected answers, marks and expected results for code probes |
| `build_exam.py` | Builds a participant notebook from the question list |
| `grade_exam.py` | Grades finalized notebooks and sidecars against the answer model |
| `assessment_tools.py` | Runtime used by the notebook to record answers; normally not run by the organiser directly |

```text
Question list --build_exam.py--> participant notebook
                                      | answers recorded in sidecar
                                      v
                           collect/finalize submissions
                                      |
Answer model ------------------------+--> grade_exam.py --> reports and summary.csv
```

1. The organiser prepares and checks the question list and answer model.
2. `build_exam.py` creates the participant notebook. A fixed seed reproduces a selection when `-n` is used.
3. Participants answer in the notebook. The runtime records answers in a sidecar file.
4. Organiser collection/finalization tools gather each notebook with its sidecar.
5. `grade_exam.py` reads the finalized submissions and answer model, then writes private reports.

## Writing the question list

A question file is YAML. The builder requires a top-level `questions` list. Every item needs `id`, `type` and `content`. IDs must be unique; non-markdown IDs must be valid Python identifiers, such as `qa1` or `code_task_1`.

The builder accepts these types: `markdown`, `qa`, `code`, `open_question` and `cloze`. The Module 1 examples are the working reference for the exact formatting of question text and notebook cells.

### Multiple choice (`qa`)

The builder requires `correct_answer`; `options`, if present, must be a list. The current question file has entries like this:

```yaml
- id: qa_example
  type: qa
  content: "Which option best describes the concept?"
  options:
    - "A) First option"
    - "B) Second option"
    - "C) Third option"
  correct_answer: "A"
  max_runs: 2
```

**Important:** `correct_answer` is required by the question-file validator, while the grader reads expected answers from the separate answer model. Keep the two consistent. `--validate-only` does not check that they agree.

### Fill in the blanks (`cloze`)

Cloze is the deterministic replacement for free-text questions in the current Module 1 assessment. The question file contains the passage and word bank, not the correct letters. Put each numbered marker exactly once in `content`.

```yaml
- id: oq_example
  type: cloze
  content: "A [1] system can ... and may [2] responses."
  blanks: 2
  word_bank:
    - "first choice"
    - "second choice"
    - "third choice"
    - "fourth choice"
  max_runs: 2
```

The builder checks that `blanks` is 2–4, every marker from `[1]` through the blank count appears exactly once, word-bank entries are non-empty and unique, and there are at least two distractors. It rejects an `answers` field in a Cloze question: correct letters belong in the answer model. Cloze scores are all-or-nothing in the current grader.

### Code (`code`)

Give participants a clear task, a starter solution or function stub, and one or more probes that call the participant's code. Probe expressions are visible to participants; **do not put expected probe results in the question list or notebook**.

```yaml
- id: c_example
  type: code
  content: "Complete the function so it returns the requested result."
  initial_code: |
    def solve(value):
        # TODO: implement
        pass
  probes:
    - "solve(3)"
    - "solve(0)"
  max_runs: 2
```

The builder supports 1–8 unique, one-line Python expressions containing a call. Optional `probe_setup` is Python code used to prepare the probe environment; it requires `probes`. Use a working code question in the existing YAML as the template for more complex setup. The answer model must provide the expected result for each probe.

### Markdown and open questions

`markdown` items provide headings or instructions and need no answer. `open_question` is accepted by the builder, but the Module 1 grading workflow is designed around deterministic QA, Cloze and code checks. Do not assume free-text responses will be automatically graded; arrange human review or use a supported deterministic question type.

### Basic validation and notebook build

Run the builder's schema check before generating an exam:

```bash
python3 scripts/workshops/assessment/build_exam.py /private/path/questions.yaml --validate-only
```

Generate an exam notebook in a private location:

```bash
python3 scripts/workshops/assessment/build_exam.py /private/path/questions.yaml \
  -o /private/path/exam.ipynb \
  -n 15 --seed 3
```

`-n` counts gradable questions, not markdown cells. The builder samples across question types; `--seed` makes that selection reproducible. Use the same seed to recreate the same selection.

After building, inspect the notebook before distributing it. Check that the question text and code starters are correct, all selected items have the intended IDs, and no answers or expected probe results are present. The builder validates question structure; it does **not** validate the answer model or confirm that the two files agree.

## Writing the answer model

The answer model is a separate private file. The grader expects a section for each gradable question, with its ID, type, points and a fenced YAML mapping under `#### `answer_key``. The model is not the question list and is not passed to `build_exam.py`.

Use the existing Module 1 answer-model section of the same question type as the template. Preserve its heading and fenced-block structure, changing the question ID, points and answer-key content. This is especially important for code questions, where the model's expected values must line up with the visible probe expressions in the question list. The grader currently has no standalone answer-model validation command; a valid-looking model can still be mismatched or score incorrectly.

At minimum, before a new assessment is used:

- Include an answer-model entry for every question that should be graded.
- Use the same ID and type as in the question list.
- Check that points add up to the intended total.
- For QA, ensure the model's accepted answer agrees with `correct_answer` in the question YAML.
- For Cloze, provide the expected letter for every numbered blank, and verify each letter identifies the intended word-bank entry.
- For code, match every model probe to the corresponding question probe and verify expected values by running the reference solution.
- Ensure no reference solution or expected result is included in the participant notebook.

The Module 1 question list and answer model are examples, not generic templates to distribute. Copy only the structure of an entry; do not copy its question text or answers into another assessment.

## Grading submissions

`grade_exam.py` needs explicit paths; it has no built-in default locations. Finalized notebook and sidecar pairs must be directly inside the harvest folder; the grader does not search subfolders.

```bash
python3 scripts/workshops/assessment/grade_exam.py \
  --model /private/path/answer_model \
  --harvest /private/path/finalized_submissions \
  --out /private/path/new_reports
```

`--out` must be a new directory outside the harvest folder. Optionally add `--user NAME` to grade only the exact matching sidecar username/participant identifier.

The notebook shows which questions were selected. The sidecar contains recorded answers. The grader uses only selected questions. It does not edit the input files.

## Reading results

- `summary.csv` gives each participant's status, automatic score, automatic maximum, selected maximum, items needing manual review and warnings.
- `COMPLETE` means every selected item was automatically graded.
- `INCOMPLETE` means one or more items need a human decision. Such items are excluded from the automatic score; check the report and compare the automatic maximum with the selected maximum.
- A wrong QA answer earns zero for that item. Cloze is all-or-nothing. Code earns points only when all its probes match.
- Participant code that errors, times out or produces an unusable result is treated as a failed code check. Runtime/infrastructure errors may need human review.
- If multiple finalized snapshots exist, the grader selects one by filename ordering and warns you. Verify the selected snapshot; the ordering is not authoritative evidence of when a participant last worked.

## Limitations to keep in mind

- The sidecar is not tamper-proof, and probe expressions are visible in the notebook. Treat automatic results as evidence, not proof of authorship or integrity.
- In Module 1, code question `c4` splits a multi-row check into three probes. Participant code that handles rows jointly may need a human look.
- The current workflow has been tested on synthetic submissions and a sandboxed runtime-to-grader integration, not on real exam submissions or deployed participant kernels. Verify deployment and the collection/finalization path before using it for a real assessment.
- Keep the answer model, question YAML, participant notebooks and reports in private locations. Check `git status` and `git check-ignore` before committing anything.

## Module 1 working examples

The private Module 1 YAML and answer model under `workshop_assets/cloud-computing-soa/module1-rest-api/assessment/` are the current examples for all supported question types. The question file can be schema-checked with `--validate-only`; that check does not validate the answer model.
