# The Complete Guide to Memory Management, Debugging, and Profiling for Python on Linux, Docker, and Kubernetes

> **This handbook now lives as one file per chapter** under
> [`docs/07_memory_management_guide/`](docs/07_memory_management_guide/). This
> page is a top-level index. Build and browse everything with `make docs`
> (serves at http://localhost:8000) or validate links with `make check`.

A practical, beginner-to-staff-engineer handbook. It starts with "what is a byte
of RAM" and ends with debugging a Kubernetes pod that gets `OOMKilled` every
40 minutes in production. Every concept is explained with the same nine
questions in mind: **what it is, why it exists, where it lives, when it grows,
when it shrinks, whether it returns memory to the OS, how to inspect it, common
misconceptions, and common production issues.**

## Chapters

Start here → **[Memory Management Guide index](docs/07_memory_management_guide/README.md)**

| # | Chapter | Status |
|---|---|---|
| 1 | [Introduction — What Memory Actually Is](docs/07_memory_management_guide/01_introduction.md) | ✅ |
| 2 | [Linux Process Memory](docs/07_memory_management_guide/02_linux_process_memory.md) | ✅ |
| 3 | [Memory Metrics (RSS, PSS, USS, and friends)](docs/07_memory_management_guide/03_memory_metrics.md) | ✅ |
| 4 | [Python Memory (CPython internals)](docs/07_memory_management_guide/04_python_memory.md) | ✅ |
| 5 | [Native Memory (NumPy, PyTorch, malloc, jemalloc)](docs/07_memory_management_guide/05_native_memory.md) | ✅ |
| 6 | [Linux Memory Internals (paging, faults, OOM killer)](docs/07_memory_management_guide/06_linux_memory_internals.md) | ✅ |
| 7 | [Docker Memory (cgroups, namespaces, layers)](docs/07_memory_management_guide/07_docker_memory.md) | ✅ |
| 8 | [Kubernetes Memory (requests, limits, QoS, eviction)](docs/07_memory_management_guide/08_kubernetes_memory.md) | ✅ |
| 9 | [Shared Memory (/dev/shm, tmpfs, IPC)](docs/07_memory_management_guide/09_shared_memory.md) | ✅ |
| 10 | [Memory Growth — The Master Table](docs/07_memory_management_guide/10_memory_growth.md) | ✅ |
| 11 | [Memory Leaks vs. Retention vs. Fragmentation](docs/07_memory_management_guide/11_memory_leaks.md) | ✅ |
| 12 | [Memory Profiling — The Complete Tool Catalog](docs/07_memory_management_guide/12_memory_profiling.md) | ✅ |
| 13 | [Kubernetes Memory Debugging Workflow](docs/07_memory_management_guide/13_kubernetes_debugging.md) | ✅ |
| 14 | Case Studies from Production | ⏳ |
| 15 | Optimization Techniques | ⏳ |
| 16 | Linux Commands Cheat Sheet | ⏳ |
| 17 | Python Memory Cheat Sheet | ⏳ |
| 18 | Kubernetes Cheat Sheet | ⏳ |
| 19 | 100+ Interview Questions | ⏳ |
| 20 | Practical Labs | ⏳ |
| 21 | Best Practices | ⏳ |
| — | Appendix — Glossary, Decision Trees, Further Reading | ⏳ |

> **Progress note:** This handbook is being written one chapter at a time.
> Ask for "the next chapter" to continue.
