# MPI source and adaptation record

Source: local `Tutorials` repository, revision `297aaf15cda80e5ced209a7f0edeeb940f5713d5`.
Paths below are relative to that repository. SHA-256 values are recorded
in `source-manifest.json` for both original inputs and distributed assets.
Participant edits are expected; do not overwrite them or reject them
because they differ from distributed checksums.

| Activity | Original source | Changes |
|---|---|---|
| `hello1` | `HPC/mpi/01-hello_world/mpi_hello_world_1.c` | No C code change; preserve the Wes Kendall header and redistribution notice. |
| `hello2` | `HPC/mpi/01-hello_world/mpi_hello_world_2.c` | No C code change; preserve the Wes Kendall header and redistribution notice. Correct the SPMD/MIMD terminology in teaching text. |
| `code1` | `HPC/mpi/02-debugging/mpi_bug1.c` | No baseline logic change. Reference: use tag 0 in both branches. |
| `code2` | `HPC/mpi/02-debugging/mpi_bug2.c` | No baseline logic change. Reference: receive and print an integer with matching MPI_INT. |
| `code3` | `HPC/mpi/02-debugging/mpi_bug3.c` | Baseline: ARRAYSIZE 16000000 -> 16000; use abort status 1. Reference: add MPI_Init and MPI_Finalize. |
| `code4` | `HPC/mpi/02-debugging/mpi_bug4.c` | Baseline: ARRAYSIZE 20000000 -> 20000; correct sample-output offsets when the root keeps leftover elements. Reference: add the root's MPI_Reduce. |
| `code5` | `HPC/mpi/02-debugging/mpi_bug5.c` | Baseline: receiver work bound 10000000000000000 -> 10000, avoiding int overflow; add completion reporting/counting. Reference: bound both communication loops to 20 messages. Objective changed from an unsupported buffer-overflow diagnosis to finite communication. |
| `code6` | `HPC/mpi/02-debugging/mpi_bug6.c` | Baseline: REPS 1000 -> 20; DISP 100 -> 10; rank 1 request offset -> 0; distinct receive buffer per outstanding receive; abort status -> 1. Reference: rank 2 nreqs -> 0. |
| `code7` | `HPC/mpi/02-debugging/mpi_bug7.c` | Baseline: initialise non-root buffers to -1 and print the value after broadcast. Reference: count -> 1 on every rank. |

CRLF line endings, if present, are normalised to LF. Replacement matching
accepts differing spaces/tabs, but still checks tokens and occurrence counts.

## Attribution and licence notices

Hello-world files retain the Wes Kendall copyright and redistribution
header, including the link to www.mpitutorial.com. Debugging files retain
the Blaise Barney author/source headers and original revision dates.
These C programs are adaptations of existing material, not newly authored
programs. This record does not replace any retained third-party notices.
The upstream root supplies Apache-2.0 licence text; the HPC root already
includes that text in `../LICENSE`. Check any additional upstream
third-party licensing obligations before public redistribution.
New activity descriptions, solution explanations, this record and the
manifest were authored for DIGITAfrica with AI assistance and are
provided under Apache-2.0.

The upstream PDF and Slurm scripts are not copied. MPI activities use the
existing prepared participant toolchain and local execution. No reset,
reinstallation, scheduler deployment or multi-node launch is introduced.

The MPI notebook and local helper are now present. Ansible staging and
participant-startup allowlists include the teaching assets, with executable
helper permissions and preserve-existing delivery. Documentation and
checksum inventories describe this repository baseline. Offline checks
do not prove live publication, participant-runtime readiness or successful
reference runs; record those results separately. Notebook narrative and
the helper were authored for DIGITAfrica with AI assistance under Apache-2.0.

## Whitespace normalisation

Bundled exercise C files had trailing spaces/tabs and extra blank lines
at EOF removed. The MPI helper had extra final blank lines removed.
No behavioural changes were intended by this formatting-only adaptation.
Author, copyright and redistribution notices remain present.

Original upstream-input checksum records are preserved. Generated-asset
and participant-seed checksums describe the whitespace-normalised files.
