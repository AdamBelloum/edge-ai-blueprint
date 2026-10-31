# An incomplete collective reduction

## Fix the buggy code

Check which ranks call MPI_Reduce. Make every rank participate in the matching reduction before the root prints its final sum.

1. Inspect the source and predict its behaviour:

       mpi_start code4

2. Run it in the organiser-authorised participant environment:

       mpi_start code4 --run --processes 4 --timeout 10

3. Edit and save `exercises/code4/code.c`, then rerun the command.

## Check

With the workshop array size of 20000, the final sum is 399980000. The root must print the reduced updated total, not the initial array sum.

A timeout, MPI error or wrong result can be part of a debugging exercise.
A successful exit alone does not establish correctness. Invalid MPI code
may behave differently across implementations.

## Reference

Only after your own correction, compare with the reference. Viewing never overwrites your source.

    mpi_start code4 --solution

Briefly record the bug, your change and the evidence that it works.

Use only authorised resources. Do not launch MPI on a cluster head node,
install software, or reset the shared OpenMP/MPI environment.

## Attribution

The C source retains its original author header. See `../../ADAPTATION.md`
for source revision and changes. This activity text is newly authored,
distributed under Apache-2.0; see `../../../LICENSE`.
