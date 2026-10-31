# A message exchange that never stops

## Fix the buggy code

Make both ranks exchange exactly 20 messages, then reach MPI_Finalize. Keep the receiver's small work loop. Use a separate counter for the communication loop.

1. Inspect the source and predict its behaviour:

       mpi_start code5

2. Run it in the organiser-authorised participant environment:

       mpi_start code5 --run --processes 2 --timeout 10

3. Edit and save `exercises/code5/code.c`, then rerun the command.

## Check

Both ranks report completing 20 messages and the program finishes. The original infinite version is expected to reach the helper timeout.

A timeout, MPI error or wrong result can be part of a debugging exercise.
A successful exit alone does not establish correctness. Invalid MPI code
may behave differently across implementations.

## Reference

Only after your own correction, compare with the reference. Viewing never overwrites your source.

    mpi_start code5 --solution

Briefly record the bug, your change and the evidence that it works.

Use only authorised resources. Do not launch MPI on a cluster head node,
install software, or reset the shared OpenMP/MPI environment.

## Attribution

The C source retains its original author header. See `../../ADAPTATION.md`
for source revision and changes. This activity text is newly authored,
distributed under Apache-2.0; see `../../../LICENSE`.
