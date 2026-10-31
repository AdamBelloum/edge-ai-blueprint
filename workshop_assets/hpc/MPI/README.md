# MPI — introductory and debugging activities

Open `01-mpi-debugging.ipynb` from `HPC/MPI/`.
Follow the organiser's instructions before running MPI programs.

Activities `hello1` and `hello2` introduce MPI; `code1` through `code7`
are debugging activities. Each includes participant `code.c`, problem
instructions, reference `solution.c` and a solution explanation.

The notebook adds the helper and prepared MPI tools to its own PATH.
For a separate terminal, activate the environment as described in
`../README.md`, then:

    cd "$HOME/HPC/MPI"
    export PATH="$PWD/helpers:$PATH"
    mpi_start hello1 --problem
    mpi_start hello1 --run --processes 2 --timeout 10

OpenMP and MPI share the prepared HPC environment. Do not reset, reinstall
or remove it between modules. Run as the participant user, not as root.
No scheduler or remote-worker launch is introduced.

The helper uses prepared mpicc/mpirun, temporary builds, localhost launches
and activity-specific process counts of at most four. Use only organiser-
authorised resources; process counts do not imply dedicated CPU cores.
Tool-file checks and receipts do not prove runtime readiness.

Faulty debugging programs may fail, time out or behave differently across
MPI implementations. Read the problem, correct your working code.c and
rerun it. View references only after your attempt. The --solution action
displays references; it does not execute or apply them. Successful exit
alone does not prove MPI correctness.

Startup copies missing files and preserves existing notebooks, code and
notes. Existing documentation and receipts are not automatically refreshed.
Distributed checksums must not be used to reject or overwrite participant edits.

See ADAPTATION.md and source-manifest.json for source records and checksums.
Retained third-party notices apply to adapted C programs; additional
redistribution obligations must be checked before public redistribution.

This documentation is not evidence of live participant-runtime validation.
This newly authored README is distributed under Apache-2.0; see ../LICENSE.
