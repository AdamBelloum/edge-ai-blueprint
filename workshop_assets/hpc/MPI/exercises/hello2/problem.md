# Different behaviour by rank

## Observe the example

Run the example. Identify which branch each rank executes. No correction is required. This remains a single-program (SPMD) example, even though ranks take different branches.

1. Inspect the source and predict its behaviour:

       mpi_start hello2

2. Run it in the organiser-authorised participant environment:

       mpi_start hello2 --run --processes 4 --timeout 10

3. Record what you observe.

## Check

With four processes, rank 0 identifies itself, rank 1 prints Hello world, rank 2 prints Bye world, and rank 3 has no greeting. Output order is not guaranteed.

A timeout, MPI error or wrong result can be part of a debugging exercise.
A successful exit alone does not establish correctness. Invalid MPI code
may behave differently across implementations.

## Reference

For these introductory examples, the reference is the same program. Viewing never overwrites your source.

    mpi_start hello2 --solution

Explain the rank-dependent output.

Use only authorised resources. Do not launch MPI on a cluster head node,
install software, or reset the shared OpenMP/MPI environment.

## Attribution

The C source retains its original author header. See `../../ADAPTATION.md`
for source revision and changes. This activity text is newly authored,
distributed under Apache-2.0; see `../../../LICENSE`.
