# A message exchange that does not finish — reference

Both branches now use tag 0. A receive must match the sender, communicator and message tag. Originally rank 0 used tag 0 and rank 1 used tag 1, so their receives could not match the sends.

Both ranks report sending and receiving one character, and the program finishes.

Original C author headers are retained. See `../../ADAPTATION.md`.
This explanation is newly authored under Apache-2.0; see `../../../LICENSE`.
