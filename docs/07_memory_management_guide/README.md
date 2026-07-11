# Memory Management, Debugging & Profiling for Python on Linux, Docker & Kubernetes

> A practical, beginner-to-staff-engineer handbook. It starts with "what is a
> byte of RAM" and ends with debugging a Kubernetes pod that gets `OOMKilled`
> every 40 minutes in production. Every concept is explained with the same nine
> questions in mind: **what it is, why it exists, where it lives, when it grows,
> when it shrinks, whether it returns memory to the OS, how to inspect it,
> common misconceptions, and common production issues.**

This handbook is part of the **Python Debugging Dojo**. It is split into one
Markdown file per chapter (this folder). Build the whole repo — including this
guide — to browsable HTML with:

```bash
make docs      # render every .md to docs_html/ and serve at http://localhost:8000
make check     # validate all relative links + build (CI-friendly, no serve)
```

The "victim" programs in [`../../workloads/`](../../workloads/) and the runnable
demos in [`../03_memory_profiling/`](../03_memory_profiling/) are used throughout.

## How to read this book

- **Chapters 1–6** build your mental model: RAM, the process address space, the
  metrics everyone argues about (RSS/PSS/USS), how CPython allocates, how native
  libraries allocate, and how the Linux kernel manages pages.
- **Chapters 7–10** move into containers: cgroups, Docker, Kubernetes, shared
  memory, and a master table of "what grows, what shrinks, what returns to the
  OS, what counts against your pod."
- **Chapters 11–14** are diagnosis: leaks vs. retention vs. fragmentation, the
  full tool catalog, a Kubernetes debugging workflow, and real case studies.
- **Chapters 15–21** are mastery: optimization, cheat sheets, 100+ interview
  questions, hands-on labs, and production best practices.
- **Appendix** is glossary + decision trees + further reading.

## Chapters

| # | Chapter | Status |
|---|---|---|
| 1 | [Introduction — What Memory Actually Is](01_introduction.md) | ✅ |
| 2 | [Linux Process Memory](02_linux_process_memory.md) | ✅ |
| 3 | [Memory Metrics (RSS, PSS, USS, and friends)](03_memory_metrics.md) | ✅ |
| 4 | [Python Memory (CPython internals)](04_python_memory.md) | ✅ |
| 5 | [Native Memory (NumPy, PyTorch, malloc, jemalloc)](05_native_memory.md) | ✅ |
| 6 | [Linux Memory Internals (paging, faults, OOM killer)](06_linux_memory_internals.md) | ✅ |
| 7 | [Docker Memory (cgroups, namespaces, layers)](07_docker_memory.md) | ✅ |
| 8 | [Kubernetes Memory (requests, limits, QoS, eviction)](08_kubernetes_memory.md) | ✅ |
| 9 | [Shared Memory (/dev/shm, tmpfs, IPC)](09_shared_memory.md) | ✅ |
| 10 | [Memory Growth — The Master Table](10_memory_growth.md) | ✅ |
| 11 | [Memory Leaks vs. Retention vs. Fragmentation](11_memory_leaks.md) | ✅ |
| 12 | [Memory Profiling — The Complete Tool Catalog](12_memory_profiling.md) | ✅ |
| 13 | [Kubernetes Memory Debugging Workflow](13_kubernetes_debugging.md) | ✅ |
| 14 | [Case Studies from Production](14_case_studies.md) | ✅ |
| 15 | [Optimization Techniques](15_optimization.md) | ✅ |
| 16 | [Linux Commands Cheat Sheet](16_linux_cheatsheet.md) | ✅ |
| 17 | [Python Memory Cheat Sheet](17_python_cheatsheet.md) | ✅ |
| 18 | [Kubernetes Cheat Sheet](18_kubernetes_cheatsheet.md) | ✅ |
| 19 | [100+ Interview Questions](19_interview_questions.md) | ✅ |
| 20 | [Practical Labs](20_practical_labs.md) | ✅ |
| 21 | [Best Practices](21_best_practices.md) | ✅ |
| — | [Appendix — Glossary, Decision Trees, Further Reading](22_appendix.md) | ✅ |

You can read front to back to go from beginner to expert, or jump to a chapter
when you have a fire to put out. Cross-references point you to the prerequisite
concepts.

> **Status: complete** — all 21 chapters + appendix are written. Start at
> [Chapter 1](01_introduction.md) and read straight through, or jump to any
> chapter above. Build the browsable HTML site with `make docs`.
