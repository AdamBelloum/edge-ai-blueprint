# code2 — Why is the last array element unchanged?

## Learning goal

Separate loop coverage from parallel execution.
Understand the bounds of an OpenMP worksharing loop.

## Intended behaviour

Every array element should contain the square of its index.
The final coverage check should report PASS.

## Observe

    openmp_start code2
    openmp_start code2 --run --threads 2

The supplied program leaves the last element at -1.
It reports FAIL and returns exit status 1. This is an
intentional exercise failure, not an installation failure.

## Investigate and correct

1. List the valid indices of an array with 8 elements.
2. List the indices visited by the parallel loop.
3. Explain why requesting more threads cannot repair its bounds.
4. Edit and save `exercises/code2/code.c` to cover every index.

Test your correction with one and two requested threads:

    openmp_start code2 --run --threads 1
    openmp_start code2 --run --threads 2

## Compare and reflect

    openmp_start code2 --solution

Explain why concurrent writes are safe here: different loop
iterations write to different array elements.
Explain why the checks after the loop see completed writes.
