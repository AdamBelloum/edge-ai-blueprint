# code1 — Reference explanation

The missing statement is:

    #pragma omp parallel

It applies to the following structured block. On entering that block,
the OpenMP runtime forms a team, and each thread executes the greeting.

Without the directive, the block is ordinary serial C code.
Outside a parallel region, `omp_get_thread_num()` reports 0 and
`omp_get_num_threads()` reports 1.

`OMP_NUM_THREADS` supplies the requested team size for parallel regions;
it does not make ordinary code parallel.

For a two-thread team, a possible output is:

    Hello from thread 0 of 2
    Hello from thread 1 of 2

The reverse order is also valid. Do not use print order to identify
thread identity or to judge correctness.

The runner compiles with `-fopenmp`, which enables the compiler's OpenMP
support and links the appropriate runtime.

Viewing this solution does not apply it to your working file.
Edit and save `exercises/code1/code.c`, then use `--run` to test it.
