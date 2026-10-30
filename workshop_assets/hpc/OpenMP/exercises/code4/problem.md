# code4 — Why does the shared counter miss increments?

## Learning goal

Recognise a read-modify-write race and protect a single update
with an OpenMP atomic directive.

## Intended behaviour

Perform 100000 increments. The final counter should be 100000.

## Observe

    openmp_start code4
    openmp_start code4 --run --threads 1
    openmp_start code4 --run --threads 2 --repeat 5

A multi-threaded run may show a mismatch. A mismatch is not
guaranteed: the original code has a data race, and a MATCH
does not prove correctness.

## Investigate and correct

1. Which variable is shared?
2. Explain the read, addition and write involved in an increment.
3. Explain how two increments could lose an update.
4. Find the directive that protects one shared-memory update.
5. Edit and save `exercises/code4/code.c`, then repeat the runs.

The program returns exit status 0 to allow repeated observations.
Inspect the printed comparison and reason about synchronisation.

## Compare and reflect

    openmp_start code4 --solution

Explain why the atomic directive applies to the increment,
not the entire loop. Could a reduction also solve this example?
Which approach would you choose if only the final total matters?
