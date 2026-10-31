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

The updated HPC README and MPI teaching documentation were also authored
for this workshop. Newly authored material is distributed under Apache-2.0.
The existing LICENSE supplies the licence text; no upstream authorship is
claimed for the new files.

Beginner reference solutions are intentionally delivered for on-demand viewing.
The organiser-controlled advanced solution-release workflow remains unimplemented.

## MPI adapted teaching material

MPI C programs were copied or adapted from Tutorials revision
`297aaf15cda80e5ced209a7f0edeeb940f5713d5`, distinct from the legacy
revision above. They are not newly authored C programs. See
`MPI/ADAPTATION.md` for source paths and changes, and
`MPI/source-manifest.json` for original-input and distributed hashes.

Hello-world sources retain Wes Kendall copyright and redistribution
notices; debugging sources retain Blaise Barney author/source headers.
These records do not establish clearance of all third-party obligations.
Check additional obligations before public redistribution.

MPI notebook narrative, helper, activity descriptions, solution explanations
and provenance documentation were authored for DIGITAfrica with AI
assistance under Apache-2.0. Runtime validation is separate from provenance.

The checksums below describe the distributed baseline. Participant edits are
expected and must not be rejected or overwritten because their checksums differ.

## Current participant seed SHA-256 checksums

```text
d5d2bc9b3dfe8cae138f5bc9d4cf88eddb94b87e61b4dca651a87bb6e98ecb47  README.md
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
054abf8269b32051ae23d1bcd06d0126d9339c87a0814f349a8928712bc2bb56  MPI/README.md
cb9bb730e3083149581cbd5876ef89bced4316d5a101d779ce1c6d4d97d12837  MPI/01-mpi-debugging.ipynb
2eae4a88426f486657e15734bb385c6d6d7eedbabba73b74b6a077c68a233853  MPI/ADAPTATION.md
aab2e582468b3ad8d4d9da5b11fd552c69b1c96d55773d0fd8a5bea79a8cffd4  MPI/source-manifest.json
bf81a1283df9cebd731230b229c5fb0abd6d4e9c93a0a0f2ce4225828cbf6ecf  MPI/helpers/mpi_start
90085ec593e30d57f6539dcc4ac652b61638487b846ed88863aa6af110079d57  MPI/exercises/hello1/code.c
b3f0dba1128e7590426a303b7c8c982985e874026eb5a332c93f9854dde031c5  MPI/exercises/hello1/problem.md
90085ec593e30d57f6539dcc4ac652b61638487b846ed88863aa6af110079d57  MPI/exercises/hello1/solution.c
7ee5bf1d46dea00f3c0f8935a55754ca458011d3d9f2f4e490a60ad69a295056  MPI/exercises/hello1/solution.md
f82b834127ed23ddb801e36600b0e5d52711a7e610b980f813212eff1be56f2d  MPI/exercises/hello2/code.c
417a29a6a36ed825c383a16cdccd3af06d340602a8c9202fdd8ad7273737ed43  MPI/exercises/hello2/problem.md
f82b834127ed23ddb801e36600b0e5d52711a7e610b980f813212eff1be56f2d  MPI/exercises/hello2/solution.c
71bd1c6fcd7d5237de3cd34c37f6d324643564e645524d07d2e0db0a0456c5f7  MPI/exercises/hello2/solution.md
f1b5a00bd3678176509fcf05a31d8aae8c3cbbd35a08c87ca5b3169e11a02742  MPI/exercises/code1/code.c
c6d0c03ab3c3279cbe44c087b28e3580e4a254148296e7867819450b9a5625d5  MPI/exercises/code1/problem.md
f41c71f42bfdb306dcbd9d389ee5fc5d0bdaf892f0c714cc88251b5dbf040181  MPI/exercises/code1/solution.c
8f5a3eea9927b71e210bd3fe913db099e9f86c3e6f4f39bce42d99bf4b786c7e  MPI/exercises/code1/solution.md
0dd418e60ab71eb4369654969665fbfbbe419b3bd318f1789a783841397bd724  MPI/exercises/code2/code.c
2999d611e2f9831415b83df1494590064130587501a6fd5a275d3500033a6152  MPI/exercises/code2/problem.md
e7ed74f1760a77bdcd92d633afd055dcefb92410ada63cb707e5a938f09a58f9  MPI/exercises/code2/solution.c
e6719f85df26c4d13264e5b86aa6a8b818df95084a43921b8eb35682b7ca14ce  MPI/exercises/code2/solution.md
e974ae63288fc793af3fb4698e9406484ce3cfe5c9e8cb16208c6de9e1a894a6  MPI/exercises/code3/code.c
b4539025619d299b1f029e7c3df9a24387474aa1233722a365887fd987e42329  MPI/exercises/code3/problem.md
59ae58dea17a6f043c9d5edf5237140fa012dd2482995f7b699f6e374ee7ad64  MPI/exercises/code3/solution.c
b58684a65cb2086df24ad2897c4a7a762971c1707229e756339cd9e1c2c67ba5  MPI/exercises/code3/solution.md
eebb650ae5c90c826d28bcfb3929fd7a11a15daebd270803dd34f150df5afde0  MPI/exercises/code4/code.c
31c40d7630d54d7325ff54ea9eaa631bc22a6554a1dcbce469dd9309ab3c5d87  MPI/exercises/code4/problem.md
145530767dc9f629c429a9311ea212ccac1ac5484dc97662a053a64cdedb45e6  MPI/exercises/code4/solution.c
004b65295b4b6a13da986b1b94f81625185e2721724854f1e362b007814d045a  MPI/exercises/code4/solution.md
b84115fcaa5bce6c65a2a87d998d8dbed9b25b68eaa52d29abb7f7aeb6d3ec1f  MPI/exercises/code5/code.c
2515b7e432855a7aa141f04268ec91469e0fff89e78ef4424ba90e6d063efaa4  MPI/exercises/code5/problem.md
7f3d4ad7193330c23d97516bccac3e9b6b0b5aeb260f21eddbdbb3b7de704579  MPI/exercises/code5/solution.c
c077ed917cbade3155513e4f23c722db7c71800555143a9b2d35f56894ed42b3  MPI/exercises/code5/solution.md
b5c6fcceab3d84d7a352b9238a08b061488c353bd5891da7b5293188481155e5  MPI/exercises/code6/code.c
c8d246d0820ca94597f860a1458e859e81b6dfbcb1caa7d0bff7500d73a552bf  MPI/exercises/code6/problem.md
c884841bb9735eddf34ac2bb1cbb5d98d0e205b969bb86b029befd5b71fefa60  MPI/exercises/code6/solution.c
f8bd77fceebddbd86c2db6539f9f5454173523fa16830c5733bad0c613812689  MPI/exercises/code6/solution.md
27259adb3b44f33ac7d2aabd6a87ce6ab1b58544233555c037c00ae6e3384f50  MPI/exercises/code7/code.c
f9c4c89ca2adeeef0eb32f18b148ed732777c173de66979f00873c986c6bc11e  MPI/exercises/code7/problem.md
5e2509f25376cdc966ca41db94a1aac0ab40fc4e102b62b022cf3ab6faf228c4  MPI/exercises/code7/solution.c
3291fe90f7bbf90d7543e68b0da48ab64ffcd304f682a14105349e7393322075  MPI/exercises/code7/solution.md
```
