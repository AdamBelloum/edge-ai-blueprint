# Spark teaching material: text-only review

## Evidence, scope and status

- Material: `workshop_assets/big_data/spark/docs/spark-DA.pdf`.
- SHA-256: `ca219fab04451bc614d9f2722d49a3b26897b73803d698d39d380eb083fa6c22`.
- Reviewed evidence: supplied extracted text from all **32 physical PDF pages**.
- Completed: text-level conceptual, pedagogical and managed-workshop alignment review.
- Pending: visual/diagram checks, editable-source confirmation, example execution,
  reference/benchmark verification and slide revisions.

Physical pages below differ from printed slide numbers. Text extraction may alter
indentation, punctuation and reading order. Confirm apparent code problems against
the visible slide and editable source before changing them.

**Disposition:** retain the unchanged PDF as conceptual/historical background,
not executable managed-workshop instructions. Use the prepared DataFrame notebook
and terminal script for participant execution. This review does not establish
that the PDF is fully validated or the workshop is operationally ready.

## Findings and targeted revisions

| Physical pages | Finding and action |
|---|---|
| 2–7 | Label the ecosystem timeline and early research framing as historical. Add objectives and an introduction tied to the CSV exercise. |
| 4, 7, 13, 18, 20 | Qualify latency, speedup, scaling and maturity claims with workload, hardware, version and source evidence. Historical benchmark results are not workshop guarantees. The 5,000-row exercise is not a performance benchmark. |
| 8–11 | Retain RDD partitioning, immutability, lineage and lazy transformations as foundations. Bridge to `SparkSession`, schema-aware DataFrames and the managed exercise. Lineage can support recovery of lost partitions when inputs remain available, not recovery from every possible failure. |
| 5, 10, 12, 16–17, 27–28 | Diagram-heavy content requires visual checking of labels, arrows, consistency, readability and attribution. Extraction alone is insufficient. |
| 11, 14–17 | The word counts match the extracted phrase. Page 15's pipeline ends with a transformation; add an explicit action and expected output if used as runnable material. Connect DataFrame `select`/`filter` to transformations and `show`/`count`/bounded collection to actions. |
| 13 | Extracted Scala includes `spark.textfiles`, `startswith` and inconsistent `messages`/`message` names. Confirm the source; correct API case, entry point and variable names. Explain when caching is materialised and verify benchmark claims separately. |
| 18 | Separate MapReduce stages, shuffle/spill and final output rather than using Spark action terminology for them. Spark also performs disk I/O; memory residency and performance superiority are not guaranteed. |
| 19–24, 27–30 | Label DStream/micro-batch/window material as legacy background and optional follow-on content, outside the beginner batch exercise. Introduce its relationship to Structured Streaming in a future module and verify APIs for the chosen release. This review makes no release-specific API-removal claim. |
| 25 | `SparkContext("local[2]", ...)` is local execution, not the prepared remote cluster. The socket source and stream startup/waiting are not fully specified in the extracted example. Keep it out of the managed notebook; a separate exercise needs a complete source, lifecycle and cleanup. |
| 26 | Check `Count()` versus `count()` and other signatures. Two tasks are not a universal local-mode default; explain configuration-dependent parallelism and checkpoint requirements for stateful examples. |
| 29 | Extracted text duplicates `window(...)` and leaves `countByWindow(...)` incomplete. Confirm visually and verify full signatures for the selected release. |
| 31 | The snippet computes `windowedWordCounts` but prints `wordCounts`. Check source indentation, print the intended result, add checkpoint setup for inverse window reduction and complete startup/waiting. Execute an independent end-to-end test before presenting it as runnable. |
| 1, 3, 9, 12, 32 | Check reference links, original benchmark/figure attribution and reuse permissions. Preserve the approved funding disclaimer; distinguish extraction artifacts from actual slide errors. |

## Required bridge to the managed beginner exercise

Explain the descriptive-analysis task, prepared kernel/interpreter, driver and
executor roles, driver callback connectivity, dataset access, schema inference,
lazy transformations, actions, bounded output and session cleanup.

Local and distributed paths may differ while referring to the same dataset.
Executors need driver connectivity and input access; these are organiser
responsibilities. Not every available worker is guaranteed to run tasks for every
small job. Stopping an application session does not stop cluster containers.

The extracted text did not supply bank-loan field definitions or dataset licence
evidence; image-only content remains unchecked. Use the workspace README for
verified local facts: 5,000 records, `Age > 30` count 4,376, raw loan-code counts
4,520/480 and 52 negative `Experience` values. Units, category mappings, provenance
and redistribution permission remain unverified. Do not clean the input silently.

## Editable-source search and next steps

A tracked-file search for `.pptx`, `.ppt`, `.odp`, `.key`, `.tex`, `.qmd` and `.Rmd`
returned no matching files. The Spark Markdown matches were the archived tutorial,
phase-one planning document, workspace README and participant guide. No editable
slide source was established by that search; one may exist elsewhere or untracked.

1. Preserve the current PDF and place participant warnings alongside it.
2. Obtain the editable slide source before attempting slide repairs.
3. Add the managed-workshop bridge; retain history/streaming as optional context.
4. Confirm apparent code issues visually and repair the source examples.
5. Test runnable examples independently in their intended runtime.
6. Check diagrams, readability, attribution, benchmark context and reuse permissions.
7. Export a revised PDF, record its checksum and repeat text/visual checks.
8. Validate the notebook and terminal routes against the live cluster separately.

This checkpoint records findings only. No PDF replacement, slide repair, code
execution, visual validation, rights clearance or deployment is implied.
