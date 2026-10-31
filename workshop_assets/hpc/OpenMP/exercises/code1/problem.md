# code1 — Why is there only one thread?

## Learning goal

Understand that requesting threads does not create a parallel region.
Identify where an OpenMP parallel directive belongs.

## Intended behaviour

When run with `--threads 2`, the corrected program should enter a
parallel region and print one greeting from each participating thread.

With a two-thread team, expect two greetings: one from thread 0 and
one from thread 1. Their order is not guaranteed.

## Observe the supplied program

    openmp_start code1
    openmp_start code1 --run --threads 2

The supplied program prints one greeting reporting a team size of 1.
It exits successfully, but does not demonstrate the intended parallelism.

## Investigate

1. What do `omp_get_thread_num()` and `omp_get_num_threads()` report?
2. Is the greeting currently inside an OpenMP parallel region?
3. Does setting `OMP_NUM_THREADS` create a parallel region by itself?
4. Which directive would make all team members execute this block?

## Propose and test a correction

Edit `exercises/code1/code.c` using the JupyterLab text editor.
Keep the braces and greeting; add the directive you believe is missing.

Then save the file and run:

    openmp_start code1 --run --threads 2
    openmp_start code1 --run --threads 4
    openmp_start code1 --run --threads 2 --repeat 3

Compare the reported team size and greeting count with your prediction.
Check correctness, not the order of the greetings.

## Compare with the reference

After making and testing your own correction:

    openmp_start code1 --solution

This displays the reference code and explanation without changing
your working file.

## Reflection

Explain the difference between requesting a team size and creating
a parallel region. Explain why changing greeting order is not a bug.

## Runtime qualification

The runner requests the thread count and disables dynamic adjustment.
The actual team size still depends on the program and runtime resources.
If the corrected program cannot create the requested team, ask the
organiser rather than reinstalling the environment.
