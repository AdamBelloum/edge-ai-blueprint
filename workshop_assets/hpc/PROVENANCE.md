# HPC asset provenance

Source repository revision: `8879982c56276455d03b2e5e3b50c42eb1cdfbd2`.

Source paths are relative to the upstream Tutorials repository.

| Source | Bundled destination | Modification |
|---|---|---|
| `LICENSE` | `LICENSE` | None |
| `HPC/openmp-01-basics/01-beginner/hello.c` | `openmp-01-basics/01-beginner/hello.c` | None |
| `HPC/openmp-01-basics/02-intermediate/pi_serial.c` | `openmp-01-basics/02-intermediate/pi_serial.c` | None |

The upstream repository supplies the included Apache-2.0 licence.
This record covers only the files listed above; it makes no licensing claim about other HPC materials.

The legacy upstream subset above contains no solutions or PDFs.
It remains in the repository unchanged but is no longer part of the
participant teaching-file allowlist.

## Bundled file SHA-256 checksums

```text
c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4  LICENSE
b8f984c4119afc76f8cc30dd9e25df4f32446e31454f9485c4d7930276c4cb5c  openmp-01-basics/01-beginner/hello.c
d59fd3cdbaba2e5a65f85894930c64fe0a1bae8b478b70f2d7949a0cc6ecf654  openmp-01-basics/02-intermediate/pi_serial.c
```

## Newly authored debugging workshop

The `OpenMP/` debugging notebook, helper, exercise descriptions, buggy C
programs, reference corrections and explanations were newly authored during
this implementation sprint with AI assistance. They are not copies of the
upstream Tutorials files listed above.

The updated HPC README and MPI placeholder documentation were also authored
for this workshop. New material is distributed under Apache-2.0.
The existing LICENSE supplies the licence text; no upstream authorship is
claimed for the new files.

Beginner reference solutions are intentionally delivered for on-demand viewing.
The organiser-controlled advanced solution-release workflow remains unimplemented.
No MPI teaching notebook or exercises are included.

The checksums below describe the distributed baseline. Participant edits are
expected and must not be rejected or overwritten because their checksums differ.

## Current participant seed SHA-256 checksums

```text
915c65e0bef9651ef91f23deec23403fb05be15ce5044e2d74446744b3d256b8  README.md
c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4  LICENSE
3f64adf15af52e8c41db4e5a804f84d691cb2d5d6a2749397c118e900eeb5c7e  OpenMP/README.md
065de417e96dabdf2c322a73247a7a0a383800665c39e92517bd9524eeb3de5a  OpenMP/01-openmp-debugging.ipynb
778c5ab969de4d2817a76726bed5ab3900014ae5596a772cc56349c27dc54e9d  OpenMP/helpers/openmp_start
58c7050e569ed672baa1afcb3661f026c7461a96909fc16beaae3a485c74989a  OpenMP/exercises/code1/code.c
a49832a4b471a4a5de33be058f727d16bf53759e209b90efb6300c904846d936  OpenMP/exercises/code1/problem.md
a4c7216a840a58398ef34c96ab3f03017d7b80757d6336cfadd4481f9a596be5  OpenMP/exercises/code1/solution.c
c8b9d7604be874c1a0bb2180e47129d03bdf8e8ca29406bec7e515a62b7fd286  OpenMP/exercises/code1/solution.md
686ce49ae9dc12ac186431b84659a8895c131cd5aa584fde1933713ab49e6c69  OpenMP/exercises/code2/code.c
c3486cf1a211ab3f139a7a0cf43d95757375396990d27df6d38e82978ffaaa54  OpenMP/exercises/code2/problem.md
919f52f3f998f80213e13c644f1abcff669aa4d0665b04a0401a7b4a58822724  OpenMP/exercises/code2/solution.c
094f1e785cf2c21429226ca1b488159067d6a64d708b95ba299fb403ab02aef4  OpenMP/exercises/code2/solution.md
942fb207aea1b59ca49ee785381ee4fec665c1bfe0f1595435fe3914a029bf14  OpenMP/exercises/code3/code.c
34f2dde7cbef895e5a46a77c9ca9d7d5a8d28666611fcce349df3811c93b316e  OpenMP/exercises/code3/problem.md
3140cdb0a0f4d72972fc0e5bebe14ab9823dd75853dd2df9d063320d969c9eea  OpenMP/exercises/code3/solution.c
727312315c8fa2ba1ebbfddf95543649abee1bd07ef0b0601607831ec64ec47b  OpenMP/exercises/code3/solution.md
24f5604cac4b3b3ce0ce8145a444c7dbf24e809b1fda77fb7b80fb91d94e8a3c  OpenMP/exercises/code4/code.c
e471a3c3f7209be733d1d5fc8f1eaab4aeb410a9f0751d6c319f522551b2595a  OpenMP/exercises/code4/problem.md
0ded4f879e4311bfc531bcd91bcacd2a840cd7743307f0405bfb5cb3863ff66f  OpenMP/exercises/code4/solution.c
bd88131bed38902f6d5aad4ad5e50474dfe4ea21aa92b633bd2960b686732c26  OpenMP/exercises/code4/solution.md
77fe4af7ae5019b903d1f2a04cc96c7cd2fb7dd29460d8e028ce67c387601cd2  MPI/README.md
```
