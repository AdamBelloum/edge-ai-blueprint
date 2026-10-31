# code2 — Reference explanation

Change the parallel loop condition from `i < N - 1` to `i < N`.

The valid indices are 0 through N-1. The original condition
excludes N-1, leaving that element at its initial value.

OpenMP distributes the iterations that the loop specifies.
It does not invent a missing iteration.

Each iteration writes a distinct array element, so these
writes do not require an atomic operation or a reduction.

The combined `parallel for` finishes before execution reaches
the serial checking loop. The corrected output ends with PASS
and exit status 0, regardless of the requested thread count.

Viewing this solution does not modify your working file.
