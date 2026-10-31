# A message exchange that never stops — reference

Both infinite communication loops are replaced by loops of 20 iterations using a separate message counter. The receiver also counts completed messages. Both ranks can then reach MPI_Finalize. A faster sender is not by itself an MPI buffer-overflow bug: standard MPI_Send may block until the receiver can accept data.

Both ranks report completing 20 messages and the program finishes. The original infinite version is expected to reach the helper timeout.

Original C author headers are retained. See `../../ADAPTATION.md`.
This explanation is newly authored under Apache-2.0; see `../../../LICENSE`.
