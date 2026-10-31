# Different behaviour by rank — reference

This is an introductory example, not buggy code. The reference reproduces the supplied example. Rank-based branching assigns different roles within a single SPMD program; it does not require separate executables.

With four processes, rank 0 identifies itself, rank 1 prints Hello world, rank 2 prints Bye world, and rank 3 has no greeting. Output order is not guaranteed.

Original C author headers are retained. See `../../ADAPTATION.md`.
This explanation is newly authored under Apache-2.0; see `../../../LICENSE`.
