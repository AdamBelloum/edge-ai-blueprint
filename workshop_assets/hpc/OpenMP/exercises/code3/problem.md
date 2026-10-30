# code3 — Why does a parallel sum sometimes lose updates?

## Learning goal

Identify a data race and use an OpenMP reduction.

## Intended behaviour

Add the integers from 1 through 10000.
The expected sum is 50005000.

## Observe

    openmp_start code3
    openmp_start code3 --run --threads 1
    openmp_start code3 --run --threads 2 --repeat 5

Compare the printed result with the expected sum.
A mismatch may appear, but it is not guaranteed.

## Investigate and correct

1. Is `sum` shared by the threads?
2. Does `sum += i` perform an indivisible update?
3. Explain how two updates can interfere.
4. Find the OpenMP clause for combining partial sums.
5. Edit and save `exercises/code3/code.c`, then repeat the runs.

## Important limitation

The original program contains a data race. Its result is not
reliably defined; a MATCH in any number of runs does not
establish correctness. Do not treat an observed wrong value
as the only evidence of the bug.

The program deliberately returns exit status 0 so the runner
can repeat observations. Judge the code and printed comparison,
not exit status alone.

## Compare and reflect

    openmp_start code3 --solution

Explain what each thread accumulates and how OpenMP combines
those partial results.
