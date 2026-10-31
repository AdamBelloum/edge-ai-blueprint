# An incomplete collective reduction — reference

Rank 0 now calls the same MPI_Reduce as the workers, before printing the final sum. A collective on MPI_COMM_WORLD requires matching participation by every rank. Workers alone cannot complete this reduction. Missing participation can hang the program, even if the root prints an initial sum.

With the workshop array size of 20000, the final sum is 399980000. The root must print the reduced updated total, not the initial array sum.

Original C author headers are retained. See `../../ADAPTATION.md`.
This explanation is newly authored under Apache-2.0; see `../../../LICENSE`.
