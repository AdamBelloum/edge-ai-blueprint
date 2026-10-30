# OpenMP — Guided debugging workshop

Open `01-openmp-debugging.ipynb` in JupyterLab and run cells individually.
The notebook checks the prepared environment and configures its own PATH.

Inspect each exercise, predict its behaviour, run it, edit and save its
`exercises/codeN/code.c`, then test your correction. Compare with
`--solution` only after making your own attempt.

Viewing code, a problem or a solution never modifies your working source.
Startup delivery preserves existing participant files.

## Using a separate terminal

Follow the environment activation instructions in `../README.md`.
Then, from this OpenMP directory:

    export PATH="$PWD/helpers:$PATH"
    openmp_start code1 --problem
    openmp_start code1 --run --threads 2

Notebook PATH changes do not configure separately opened terminals.

## Exercises

- code1: missing parallel region.
- code2: incomplete loop coverage.
- code3: shared sum requiring a reduction.
- code4: shared counter requiring synchronisation.

The buggy code2 intentionally exits with status 1.
The race exercises can produce correct-looking results despite being unsafe.
Neither exit status 0 nor repeated matching outputs prove race freedom.

Use only the resources authorised by the organiser.
Move to MPI when instructed; do not reinstall or reset the environment.

## Licence and provenance

New workshop material is distributed under Apache-2.0; see `../LICENSE`.
See `../PROVENANCE.md` for its origin and baseline checksums.
Checksums describe distributed originals, not participant-edited files.
