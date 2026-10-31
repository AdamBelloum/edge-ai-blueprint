# MPI hello world: processes and ranks

## Observe the example

Run the example. Identify the rank and total process count in its output. No correction is required.

1. Inspect the source and predict its behaviour:

       mpi_start hello1

2. Run it in the organiser-authorised participant environment:

       mpi_start hello1 --run --processes 2 --timeout 10

3. Record what you observe.

## Check

With two processes, expect a greeting from ranks 0 and 1. Output order and line interleaving are not guaranteed.

A timeout, MPI error or wrong result can be part of a debugging exercise.
A successful exit alone does not establish correctness. Invalid MPI code
may behave differently across implementations.

## Reference

For these introductory examples, the reference is the same program. Viewing never overwrites your source.

    mpi_start hello1 --solution

Explain the rank-dependent output.

Use only authorised resources. Do not launch MPI on a cluster head node,
install software, or reset the shared OpenMP/MPI environment.

## Attribution

The C source retains its original author header. See `../../ADAPTATION.md`
for source revision and changes. This activity text is newly authored,
distributed under Apache-2.0; see `../../../LICENSE`.
