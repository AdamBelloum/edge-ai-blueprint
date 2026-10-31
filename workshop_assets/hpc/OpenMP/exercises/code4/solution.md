# code4 — Reference explanation

Place `#pragma omp atomic update` immediately before
`counter += 1`.

This makes each counter update atomic with respect to the
other atomic updates of that location. The updates no longer
interfere through an unsynchronised read-modify-write race.

The parallel-for construct completes before the final print,
so the expected final count is 100000.

This exercise teaches atomic updates, not performance tuning.
If only the final total matters, a reduction on `counter`
is another correct approach and can avoid contention on a
shared counter. An atomic directive protects a supported
single update; it does not protect an arbitrary multi-statement
operation. Such operations may require another mechanism,
such as a critical region.

Viewing this solution does not modify your working file.
