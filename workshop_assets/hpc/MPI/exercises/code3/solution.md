# Missing MPI initialisation and shutdown — reference

MPI_Init is added before the first communicator query, and MPI_Finalize is added after all communication. The workload reduction and defined abort code were baseline adaptations, not student corrections.

The program starts MPI, processes the array, prints sample results and a final sum, and finishes. The mathematical total is 255984000; single-precision accumulation can introduce rounding differences. Finishing alone does not verify the numerical result.

Original C author headers are retained. See `../../ADAPTATION.md`.
This explanation is newly authored under Apache-2.0; see `../../../LICENSE`.
