# Waiting for requests that were not created — reference

Rank 2 sets nreqs to zero because blocking MPI_Send does not create request handles. MPI_Waitall with a count of zero is valid. The other ranks wait on exactly the nonblocking requests they created. Request indexing, separate receive buffers, workload size and abort status were corrected in the baseline to keep the student task focused.

All four ranks complete their communication and report timings. Timing differences are not a correctness test; inspect request creation and completion as well.

Original C author headers are retained. See `../../ADAPTATION.md`.
This explanation is newly authored under Apache-2.0; see `../../../LICENSE`.
