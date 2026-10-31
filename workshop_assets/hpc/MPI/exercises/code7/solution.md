# An inconsistent broadcast — reference

Every rank now passes count 1 and MPI_INT, with the same root and communicator. The original rank-dependent count produced incompatible broadcast type signatures; ranks above 1 also specified more integers than the scalar buffer could hold. Invalid MPI arguments need not produce a predictable hang.

Every rank prints value 23 after the broadcast. Before the broadcast, only rank 0 starts with 23.

Original C author headers are retained. See `../../ADAPTATION.md`.
This explanation is newly authored under Apache-2.0; see `../../../LICENSE`.
