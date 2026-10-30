# HPC — OpenMP and MPI workshop

Open a JupyterLab terminal. Activate the prepared toolchain in each new terminal:

    hpc_prefix="$HOME/.local/share/digitafrica/runtime/hpc/environment"
    test -f "${hpc_prefix%/environment}/environment.sha256" &&
      eval "$(/opt/conda/bin/conda shell.bash hook)" &&
      conda activate "$hpc_prefix"

Continue only if activation succeeds. Verify the compiler:

    "$CC" --version

Use "$CC" rather than assuming that gcc selects this toolchain.
Activation applies to the current terminal, not existing notebook kernels.

If preparation or activation fails, ask the organiser.
Do not reinstall or remove the environment yourself.

The initial toolchain specification is not yet version-locked.

## Teaching layout

- `OpenMP/01-openmp-debugging.ipynb`: guided debugging activities.
- `OpenMP/helpers/openmp_start`: inspect, describe, run and show solutions.
- `OpenMP/exercises/code1` through `code4`: participant working C files.
- `MPI/README.md`: reserved module location; teaching content pending.

Start the OpenMP notebook from its directory. It checks the compiler and
adds the exercise helper to its own PATH without installing software.

For a separate terminal, activate the environment as above, then:

    cd "$HOME/HPC/OpenMP"
    export PATH="$PWD/helpers:$PATH"
    openmp_start code1 --problem

Both capabilities share preparation and validation. No reset or runtime
transition is needed between the teaching modules.

Participant startup copies only missing teaching files. Existing notebooks,
working code and notes are preserved; old teaching directories are not deleted.
This also means existing copies of documentation are not automatically updated.

Reference solutions are available on demand in the beginner activities.
This is separate from the unimplemented organiser-controlled advanced release.

The seed receipt records delivery, not runtime readiness or successful learning.
New workshop material is distributed under Apache-2.0; see LICENSE and PROVENANCE.md.
