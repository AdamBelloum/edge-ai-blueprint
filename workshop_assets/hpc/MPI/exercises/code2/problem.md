# Unexpected received values

## Fix the buggy code

The received values do not reliably match the sent integers. Check both the C variable types and the MPI datatypes. Fix the mismatch.

1. Inspect the source and predict its behaviour:

       mpi_start code2

2. Run it in the organiser-authorised participant environment:

       mpi_start code2 --run --processes 2 --timeout 10

3. Edit and save `exercises/code2/code.c`, then rerun the command.

## Check

Rank 1 receives the integers 0, 10, 20, ..., 90 in order. Output from different ranks may interleave.

A timeout, MPI error or wrong result can be part of a debugging exercise.
A successful exit alone does not establish correctness. Invalid MPI code
may behave differently across implementations.

## Reference

Only after your own correction, compare with the reference. Viewing never overwrites your source.

    mpi_start code2 --solution

Briefly record the bug, your change and the evidence that it works.

Use only authorised resources. Do not launch MPI on a cluster head node,
install software, or reset the shared OpenMP/MPI environment.

## Attribution

The C source retains its original author header. See `../../ADAPTATION.md`
for source revision and changes. This activity text is newly authored,
distributed under Apache-2.0; see `../../../LICENSE`.
