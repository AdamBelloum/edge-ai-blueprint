# Big Data workshop: educational proof of concept

## Scope statement

This workshop provides a limited, fixed-size Spark and Livy proof of concept for educational use. It demonstrates selected distributed-processing concepts within a controlled teaching environment. It is not a complete, production-ready Big Data infrastructure, and the current implementation does not provide dynamic scaling.

Running Spark does not itself establish Big Data capacity. Any capacity statement must be tied to the actual hardware, dataset sizes and workloads tested.

## Current architecture

The tested deployment inventory selects two group VMs. Each VM is configured for its own private Spark runtime consisting of:

- One Spark master container.
- One Spark worker container.
- One optional Livy container for REST-based submission.
- Read-only dataset mounts.

The two group VMs are not, by this configuration alone, a single Spark cluster spanning both VMs. They provide separate teaching runtimes. The inspected Compose configuration publishes no Livy host port; participant access requires separate, restricted integration and validation.

The configuration supports selecting one or two Spark worker containers per VM, but this is a fixed preparation-time choice, not dynamic scaling. The current Livy pilot uses one worker per VM.

## Hardware requirements and configured limits

The following values describe the current implementation's validation thresholds and container limits. They are not guarantees of capacity or performance.

| Item | Current requirement or limit | Interpretation |
|---|---|---|
| VM platform | Linux on x86_64/amd64 | Other platforms have not been validated by this workflow. |
| CPU per group VM | At least 4 vCPUs | Build/preflight validation threshold, not an exclusive CPU reservation. |
| RAM per group VM, one Spark worker plus Livy | At least 7 GiB reported by Ansible | Preparation/build threshold. Additional headroom may be required for the OS, Kubernetes, participant notebooks and concurrent workloads. |
| RAM per group VM, two Spark workers plus Livy | At least 9 GiB reported by Ansible | Alternative configuration threshold; not evidence that this configuration has passed the final workshop workload test. |
| Spark master container memory | 512 MiB | Configured container limit. |
| Each Spark worker container memory | 2 GiB | Configured container limit; not equivalent to usable executor heap. |
| Livy container memory | 2 GiB | Shared by the Livy service and any client-mode Spark drivers running in that container. |
| Livy service CPU | 1 CPU | Compose CPU limit. |
| Livy server Java heap | Maximum 512 MiB; initial heap 128 MiB | Runtime configuration. This does not cap all server process memory or driver memory. |
| Disk capacity | No validated minimum established yet | Must accommodate images, archives, datasets, build cache, temporary files and Spark spill. Record actual free space and workload disk usage after testing. |
| Host placement and network | Record actual placement and connectivity | Two VMs do not necessarily represent two independent physical machines. VM-local Docker networking is not evidence of a multi-host Spark cluster. |

Report the actual VM specifications alongside these thresholds. If the VMs share physical hardware, report that fact. Do not describe the sum of VM allocations as dedicated physical capacity without evidence.

The summed container memory limits are 4.5 GiB per VM for the one-worker Livy configuration and 6.5 GiB for the two-worker Livy configuration. These sums are not memory reservations, do not include all host services, and do not demonstrate safe participant concurrency.

## Evidence available before the final runtime test

| Capability | Current evidence |
|---|---|
| Preparation on both group VMs | Successful: locked Livy archives downloaded and checksum-verified; configuration staged and Compose validated. |
| Spark base image | Successful: local Linux/amd64 image and pinned repository digest verified on both VMs. |
| Livy image build | Successful on both VMs: archive, build inputs and resulting image metadata verified. |
| Private Livy service definition | Present in the inspected Compose configuration; no Livy host port is published. Runtime isolation still requires validation. |
| Explicit Livy server heap setting | Added to the local Compose template. Remote restaging and runtime verification remain to be confirmed. |
| Livy startup and REST response | Not yet verified in the current test sequence. |
| Spark worker registration | Not yet verified for the newly staged one-worker Livy configuration. |
| Spark computation submitted through Livy | Not yet verified. |
| Participant notebook access to Livy | Not implemented or verified in the current test sequence. |
| Safe concurrent participant sessions | Not established. |
| Resource capacity under workshop load | Not established. |

A built image or successful Compose validation is not proof of an operational workshop runtime.

## Educational activities to validate

The final capability list should include only activities demonstrated successfully in this exact setting. Candidate activities are:

- Observe Spark master/worker roles and explain task distribution.
- Create a controlled PySpark session through Livy and inspect its lifecycle.
- Submit simple Spark computations against the assigned read-only dataset.
- Demonstrate partitioning, transformations, actions and basic aggregations using a dataset small enough for the tested limits.
- Observe selected job and resource behavior during a guided exercise.
- Compare a local computation with the fixed-size Spark demonstration, without claiming a general performance benefit.

Until tested, these are intended activities, not validated capabilities. A master and worker running as containers on one VM demonstrate software roles and scheduling concepts, not scale-out across independent machines.

## Explicit limitations

The current implementation does not establish:

- Dynamic scaling or elastic resource provisioning.
- A Spark cluster spanning the two group VMs.
- A production-scale distributed storage platform.
- Capacity for arbitrary large datasets or unrestricted jobs.
- High availability, automatic failover or disaster recovery.
- Production-grade participant isolation, authentication or admission control for Livy.
- A safe number of concurrent active sessions.
- Performance, throughput or service-level guarantees.
- Suitability for production or sensitive-data processing.

Private networking, read-only mounts and container limits are useful controls, but are not a complete security or multi-tenancy model.

## Final test evidence to record

Before issuing the final workshop capability statement, record:

1. Actual vCPUs, reported RAM, free disk space and physical host placement for each VM.
2. Relevant software versions, pinned source inputs and built image identities.
3. Services and worker count actually running on each VM.
4. REST readiness, Spark worker registration and a completed computation with a checked result.
5. Whether submission was organiser-controlled or performed from a participant notebook.
6. Dataset identity, size, record count and relevant partition settings.
7. The tested driver/executor memory and core settings.
8. Active session count and participant count used in the test.
9. Observed runtime, memory use, disk/spill behavior and any failures or OOM events.
10. What was not tested.

If only one organiser-controlled session is tested, state that explicitly. Do not extrapolate to an entire workshop cohort.

## Wording for the post-test report

Use this scope statement unchanged:

> The Big Data workshop uses a limited, fixed-size Spark/Livy proof of concept for educational purposes. It is not a complete Big Data infrastructure and does not provide dynamic scaling. Each selected group VM hosts a private teaching runtime. Supported exercises and capacity claims are limited to the hardware, datasets, resource settings and concurrency actually validated in the workshop tests.

Follow it with the recorded hardware specifications and a table of activities marked **verified**, **not verified**, or **unsupported**. Include observed limits and failures rather than claiming general scalability.
