# Waiting for requests that were not created

## Fix the buggy code

Check which calls create MPI_Request handles. Correct the number of requests rank 2 passes to MPI_Waitall.

1. Inspect the source and predict its behaviour:

       mpi_start code6

2. Run it in the organiser-authorised participant environment:

       mpi_start code6 --run --processes 4 --timeout 10

3. Edit and save `exercises/code6/code.c`, then rerun the command.

## Check

All four ranks complete their communication and report timings. Timing differences are not a correctness test; inspect request creation and completion as well.

A timeout, MPI error or wrong result can be part of a debugging exercise.
A successful exit alone does not establish correctness. Invalid MPI code
may behave differently across implementations.

## Reference

Only after your own correction, compare with the reference. Viewing never overwrites your source.

    mpi_start code6 --solution

Briefly record the bug, your change and the evidence that it works.

Use only authorised resources. Do not launch MPI on a cluster head node,
install software, or reset the shared OpenMP/MPI environment.

## Attribution

The C source retains its original author header. See `../../ADAPTATION.md`
for source revision and changes. This activity text is newly authored,
distributed under Apache-2.0; see `../../../LICENSE`.
