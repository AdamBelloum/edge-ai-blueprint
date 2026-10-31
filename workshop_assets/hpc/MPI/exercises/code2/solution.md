# Unexpected received values — reference

The receiving variable is now int, MPI_Irecv uses MPI_INT, and printf uses %d. MPI communication does not implicitly convert an integer message into a floating-point message. The existing waits complete each nonblocking operation before its buffer is reused.

Rank 1 receives the integers 0, 10, 20, ..., 90 in order. Output from different ranks may interleave.

Original C author headers are retained. See `../../ADAPTATION.md`.
This explanation is newly authored under Apache-2.0; see `../../../LICENSE`.
