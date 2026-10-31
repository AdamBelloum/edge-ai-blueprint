# Missing MPI initialisation and shutdown

## Fix the buggy code

Compare the MPI lifecycle with hello1. Add the missing initialisation and shutdown calls in the correct places.

1. Inspect the source and predict its behaviour:

       mpi_start code3

2. Run it in the organiser-authorised participant environment:

       mpi_start code3 --run --processes 4 --timeout 10

3. Edit and save `exercises/code3/code.c`, then rerun the command.

## Check

The program starts MPI, processes the array, prints sample results and a final sum, and finishes. The mathematical total is 255984000; single-precision accumulation can introduce rounding differences. Finishing alone does not verify the numerical result.

A timeout, MPI error or wrong result can be part of a debugging exercise.
A successful exit alone does not establish correctness. Invalid MPI code
may behave differently across implementations.

## Reference

Only after your own correction, compare with the reference. Viewing never overwrites your source.

    mpi_start code3 --solution

Briefly record the bug, your change and the evidence that it works.

Use only authorised resources. Do not launch MPI on a cluster head node,
install software, or reset the shared OpenMP/MPI environment.

## Attribution

The C source retains its original author header. See `../../ADAPTATION.md`
for source revision and changes. This activity text is newly authored,
distributed under Apache-2.0; see `../../../LICENSE`.
