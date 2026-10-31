# An inconsistent broadcast

## Fix the buggy code

Broadcast one integer from rank 0. Check the count passed by each rank and the size of its receive buffer. Correct the count.

1. Inspect the source and predict its behaviour:

       mpi_start code7

2. Run it in the organiser-authorised participant environment:

       mpi_start code7 --run --processes 2 --timeout 10

3. Edit and save `exercises/code7/code.c`, then rerun the command.

## Check

Every rank prints value 23 after the broadcast. Before the broadcast, only rank 0 starts with 23.

A timeout, MPI error or wrong result can be part of a debugging exercise.
A successful exit alone does not establish correctness. Invalid MPI code
may behave differently across implementations.

## Reference

Only after your own correction, compare with the reference. Viewing never overwrites your source.

    mpi_start code7 --solution

Briefly record the bug, your change and the evidence that it works.

Use only authorised resources. Do not launch MPI on a cluster head node,
install software, or reset the shared OpenMP/MPI environment.

## Attribution

The C source retains its original author header. See `../../ADAPTATION.md`
for source revision and changes. This activity text is newly authored,
distributed under Apache-2.0; see `../../../LICENSE`.
