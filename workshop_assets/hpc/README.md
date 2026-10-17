# HPC — OpenMP basics

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
