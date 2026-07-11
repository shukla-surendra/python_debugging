<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Appendix — Glossary, Decision Trees, Further Reading

The reference back-matter: a glossary grouped by domain, quick-reference tables,
decision trees / troubleshooting flowcharts, and a curated further-reading list
(books, kernel docs, CPython source, Kubernetes docs, PEPs).

---

## A. Glossary

### A.1 General memory terms

- **Byte / word** — a byte is 8 bits; a word is the CPU's native integer size
  (8 bytes on 64-bit). (Ch 1.1)
- **Address space** — the set of virtual addresses a process can use (128 TiB on
  64-bit Linux). (Ch 1.5)
- **Virtual memory** — per-process private address space mapped to physical
  frames via page tables. (Ch 1.4)
- **Physical memory / RAM** — the actual DRAM; a finite resource. (Ch 1.2)
- **Page** — 4 KiB unit of virtual memory; **page frame** — the physical
  counterpart. (Ch 1.7)
- **Huge page** — 2 MiB / 1 GiB page reducing TLB pressure. (Ch 6.7)
- **`mmap`** — syscall mapping memory to a file (file-backed) or nothing
  (anonymous). (Ch 1.9)
- **Anonymous memory** — not file-backed; your data (heap/stack/objects),
  swap-backed. (Ch 1.10)
- **File-backed memory** — mirrors a file (code/`.so`/mmap'd data); reclaimable.
  (Ch 1.11)
- **GiB vs GB** — `GiB` = 2³⁰; `GB` = 10⁹; k8s uses binary `Gi/Mi/Ki`. (Ch 1.2)

### A.2 Metrics

- **RSS** — resident set size; memory in RAM, over-counts shared pages. (Ch 3.3)
- **VSZ/VSS** — virtual size; total reserved address space (a promise). (Ch 3.2)
- **PSS** — proportional set size; shared pages apportioned; sums correctly.
  (Ch 3.4)
- **USS** — unique set size; private-only; dies with the process. (Ch 3.5)
- **Working set** — non-reclaimable ≈ `memory.current − inactive_file`; the k8s
  OOM metric. (Ch 3.14)
- **Page cache** — cached file contents in RAM; reclaimable. (Ch 3.9)
- **Dirty pages** — modified-but-not-yet-written-back pages. (Ch 3.10)
- **Available** — RAM allocatable without swapping (`free` + reclaimable). (Ch
  3.12)
- **Committed_AS / CommitLimit** — total promised memory / the cap. (Ch 3.12)
- **Slab** — kernel's allocator for its own objects (dentry/inode/etc.). (Ch
  3.13)

### A.3 Python / CPython terms

- **CPython** — the reference C implementation of Python. (Ch 4.1)
- **PyObject** — the C struct every value starts with (refcount + type). (Ch 4.2)
- **Reference counting** — immediate, deterministic freeing when refcount → 0.
  (Ch 4.3)
- **Cyclic GC** — generational collector that frees reference cycles only. (Ch
  4.4–4.6)
- **Generation (gen0/1/2)** — GC age buckets; young scanned more often. (Ch 4.6)
- **pymalloc** — CPython's small-object (≤512 B) allocator. (Ch 4.7)
- **Arena / pool / block** — 256 KiB / 4 KiB / object-slot units of pymalloc.
  (Ch 4.7)
- **GIL** — global lock serializing bytecode, protecting refcounts. (Ch 4.3)
- **`__slots__`** — fixed-attribute storage replacing per-instance `__dict__`.
  (Ch 4.11)
- **Interning / free list** — cached singletons / reused type slots. (Ch 4.11)
- **tracemalloc** — built-in Python-allocation profiler (blind to native). (Ch
  12.3)

### A.4 Native / allocator terms

- **`malloc`/`free`** — the C allocator interface. (Ch 5.9)
- **glibc arena** — per-thread malloc region; up to 8×cores. (Ch 5.9)
- **`M_MMAP_THRESHOLD`** — size (128 KiB) above which malloc uses `mmap`. (Ch 5.9)
- **`MALLOC_ARENA_MAX`** — env var capping glibc arenas. (Ch 5.9)
- **jemalloc / tcmalloc** — drop-in allocators with less fragmentation. (Ch 5.10)
- **`malloc_trim`** — asks glibc to return free heap to the OS. (Ch 5.9)
- **`nbytes`** — a NumPy array's real buffer size. (Ch 5.3)
- **View vs copy** — shared-memory slice vs. new buffer. (Ch 5.3)
- **Caching allocator (PyTorch)** — holds freed GPU memory; `empty_cache()`
  returns it. (Ch 5.7)

### A.5 Linux kernel terms

- **Demand paging** — frames allocated on first touch. (Ch 6.1)
- **Page fault (minor/major)** — map-in-RAM (fast) vs. fetch-from-disk (slow).
  (Ch 6.3)
- **Page table / MMU** — the virtual→physical map and the hardware that walks it.
  (Ch 6.2)
- **TLB** — CPU cache of translations. (Ch 6.5)
- **THP** — Transparent Huge Pages; auto 2 MiB promotion. (Ch 6.7)
- **Copy-on-write (COW)** — share pages until written. (Ch 6.8)
- **NUMA** — non-uniform memory access on multi-socket nodes. (Ch 6.9)
- **Overcommit** — promising more memory than exists. (Ch 6.10)
- **OOM killer / `oom_score` / `oom_score_adj`** — victim selection under memory
  exhaustion. (Ch 6.11)
- **kswapd / reclaim** — background/direct memory reclamation. (Ch 6.12)
- **Swappiness** — kernel bias toward swapping anon vs. dropping cache. (Ch 6.6)

### A.6 Docker / container terms

- **Namespace** — isolated *view* (PID/mnt/net/IPC/…). (Ch 7.2)
- **cgroup (v1/v2)** — resource *limits* & accounting. (Ch 7.3)
- **`memory.max` / `memory.current` / `memory.stat` / `memory.events`** — v2
  limit / usage / breakdown / counters. (Ch 7.6)
- **tmpfs / `/dev/shm`** — RAM-backed filesystem / shared-memory mount. (Ch 7.8,
  9.2)
- **`--shm-size`** — Docker `/dev/shm` size. (Ch 7.8)
- **Overlay fs / writable layer** — union filesystem; per-container disk layer.
  (Ch 7.9)
- **Ephemeral storage** — disk-backed, not memory (writable layer, default
  `emptyDir`). (Ch 7.10)

### A.7 Kubernetes terms

- **Requests / limits** — scheduling reservation / hard cgroup cap. (Ch 8.2)
- **QoS (Guaranteed/Burstable/BestEffort)** — derived from requests/limits; sets
  eviction order + `oom_score_adj`. (Ch 8.3)
- **OOMKilled (137)** — container exceeded its own limit; kernel SIGKILL. (Ch 8.4)
- **Eviction / MemoryPressure** — kubelet reclaims pods under node pressure. (Ch
  8.5)
- **`kubectl top`** — shows working set (not RSS). (Ch 8.6)
- **`emptyDir` (medium: Memory)** — disk scratch / RAM tmpfs (counts as memory).
  (Ch 8.7)
- **PersistentVolume / CSI / hostPath** — external / driver / node-path storage.
  (Ch 8.7)
- **Downward API** — inject limits/requests as env vars. (Ch 8.6)
- **`kubectl debug --target`** — ephemeral container sharing the PID namespace.
  (Ch 18.9)

---

## B. Quick-reference tables

### B.1 Metric at a glance

| Metric | Counts shared? | Sums across procs? | k8s uses? | Alert? |
|---|---|---|---|---|
| VSZ | reserved | no | no | ❌ |
| RSS | full | double-counts | per-container-ish | ⚠️ vs limit |
| PSS | apportioned | ✅ | no | ✅ fleets |
| USS | no | ✅ | no | ✅ leaks |
| Working set | active only | per cgroup | ✅ **OOM** | ✅ |

### B.2 Does it count toward the pod limit?

| Memory | Non-reclaimable? | Counts / OOMs you? |
|---|---|---|
| Anonymous (heap/objects/arrays) | yes | ✅ |
| Native buffers (NumPy/Torch) | yes | ✅ |
| tmpfs / `/dev/shm` | yes | ✅ |
| Thread stacks (touched) | yes | ✅ (small) |
| Kernel/slab (fds/sockets) | mostly | ✅ (rare) |
| Page cache (clean) | no | counts, reclaimable |
| Shared libraries | no | shared, cheap |
| Writable layer / PV | disk | ❌ (except cache) |

### B.3 `memory.stat` → diagnosis

| Counter | Means | Go to |
|---|---|---|
| `anon` | Python or native data | tracemalloc vs memray |
| `shmem` | `/dev/shm` / tmpfs | Ch 9 |
| `file` | page cache | usually fine |
| `slab` / `kernel_stack` | fds/sockets/threads | lsof, Ch 3.13 |

### B.4 Exit codes & symptoms

| Signal | Meaning |
|---|---|
| Exit 137 | SIGKILL (OOMKilled) |
| `Bus error` | `/dev/shm` too small (Ch 9.6) |
| `MemoryError` | Python alloc failed (RLIMIT/overcommit off) |
| `resource_tracker: leaked shared_memory` | missing `unlink()` (Ch 9.5) |
| pod `Evicted` | node MemoryPressure (Ch 8.5) |

---

## C. Decision trees & flowcharts

### C.1 Master: "memory is climbing / OOMKilled"

```
   Is it memory? (OOMKilled/137, not liveness/CPU/disk)         -> Ch 13.1
        |
   Working set vs limit; memory.events oom_kill?                -> Ch 13.2
        |
   memory.stat kind:
     anon  --> Python? (gc_objects grows -> tracemalloc/objgraph)
               native? (RSS grows, objects flat -> memray)      -> Ch 5, 13.5
     shmem --> /dev/shm / shared_memory leak (du, ipcs)         -> Ch 9
     file  --> page cache (usually reclaimable, not the cause)  -> Ch 3
     slab  --> fd/socket/thread leak (lsof, slabtop)            -> Ch 3.13
        |
   Shape: climb=leak/retention · plateau=caching · sawtooth-floor=frag -> Ch 11
        |
   Node pressure? (MemoryPressure/Evicted) vs your own limit    -> Ch 8.5
        |
   Fix (Ch 15) + VERIFY shape changed + oom_kill stops          -> Ch 13.7
```

### C.2 "RSS won't drop after freeing"

```
   Freed objects but RSS flat?
     small objects?  -> pymalloc arenas retained (Ch 4.9) -> recycle/jemalloc
     large mmap?     -> should munmap; if not, refs remain -> find the reference
     native buffer?  -> allocator hoarding -> MALLOC_ARENA_MAX / jemalloc / trim
     none freed?     -> retention: something still references them (Ch 11.4)
```

### C.3 "tracemalloc flat but RSS grows" (phantom OOM)

```
   -> It's NOT Python objects. Candidates:
        native buffers (NumPy/Torch/cv2/PIL)   -> memray --native
        /dev/shm / shared memory               -> du /dev/shm, memory.stat shmem
        thread stacks (many threads)           -> /proc/status Threads, VSZ
        kernel/slab (fds/sockets)              -> lsof | wc -l, slabtop
        THP inflation                          -> AnonHugePages in smaps_rollup
```

### C.4 "Container OOMs but app heap is small"

```
   -> Check memory.stat: shmem (/dev/shm), slab (fds), or native anon (Ch 5)
   -> Check /dev/shm size vs limit (Ch 9.8); fd count (Ch 13.5e)
   -> Check THP AnonHugePages (Ch 6.7); MALLOC_ARENA_MAX on many-core (Ch 5.9)
```

---

## D. Further reading

### D.1 Books

- Brendan Gregg, *Systems Performance* (2nd ed.) — the definitive performance +
  memory/OS reference.
- Robert Love, *Linux Kernel Development* — pages, VM, the memory subsystem.
- Mel Gorman, *Understanding the Linux Virtual Memory Manager* — deep VM (classic,
  free online).
- Julia Evans, *Linux Debugging Tools* / *Bite Size Linux* zines — approachable
  `/proc`, strace, memory.
- Luciano Ramalho, *Fluent Python* (2nd ed.) — CPython object model, refcounting,
  weakrefs.

### D.2 Kernel documentation

- `Documentation/admin-guide/mm/` (transhuge, concepts, numa) —
  https://www.kernel.org/doc/html/latest/admin-guide/mm/
- cgroup v2 memory controller —
  https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html
- `proc(5)` man page (`/proc/<pid>/{status,smaps,maps}`) — `man 5 proc`
- OOM killer / overcommit — `Documentation/vm/overcommit-accounting`,
  `Documentation/filesystems/proc.rst`

### D.3 CPython source & docs

- `Objects/obmalloc.c` — pymalloc (arenas/pools/blocks). (Ch 4.7)
- `Modules/gcmodule.c` / `Python/gc.c` — the cyclic GC. (Ch 4.4)
- `Include/object.h` — `PyObject`, refcount macros. (Ch 4.2)
- `gc`, `sys`, `tracemalloc`, `resource` module docs —
  https://docs.python.org/3/library/
- `devguide.python.org` — "Garbage collector design", memory management.

### D.4 Tool documentation

- **memray** — https://bloomberg.github.io/memray/ (Ch 12.3)
- **scalene** — https://github.com/plasma-umass/scalene
- **py-spy** — https://github.com/benfred/py-spy
- **Pyroscope** (continuous profiling) — https://grafana.com/oss/pyroscope/
- **smem** — `man smem`; **pmap** — `man pmap`; **pidstat/sar** — sysstat docs.

### D.5 Kubernetes / container docs

- Managing resources (requests/limits) —
  https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
- Pod QoS classes —
  https://kubernetes.io/docs/concepts/workloads/pods/pod-qos/
- Node-pressure eviction —
  https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/
- Ephemeral containers / `kubectl debug` —
  https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/
- Docker resource constraints —
  https://docs.docker.com/config/containers/resource_constraints/

### D.6 PEPs (Python Enhancement Proposals)

- **PEP 442** — Safe object finalization (cycles with `__del__`). (Ch 4.5)
- **PEP 445** — Customizable memory allocators (`PyMem_*`). (Ch 5.2)
- **PEP 454** — `tracemalloc`. (Ch 12.3)
- **PEP 683** — Immortal objects (refcount avoidance). (Ch 4.3)
- **PEP 703** — Making the GIL optional / free-threaded CPython. (Ch 4.3)

### D.7 This repo

- Runnable memory demos: [`../03_memory_profiling/`](../03_memory_profiling/)
- Victim programs: [`../../workloads/`](../../workloads/)
- Production k8s debugging:
  [`../05_production_playbook/04_kubernetes_debugging.md`](../05_production_playbook/04_kubernetes_debugging.md)
- Build this handbook to HTML: `make docs` · validate links: `make check`

---

## Key takeaways

- **The glossary and tables are your fast lookup** — when a term or metric comes
  up mid-incident, this is where to check its exact meaning and whether it counts
  toward the pod.
- **The decision trees (C.1–C.4) are the book compressed to one page each** — the
  master OOM flow, "RSS won't drop," the phantom OOM, and small-heap container
  OOMs.
- **Go to primary sources for depth:** `obmalloc.c`/`gcmodule.c` for CPython, the
  kernel mm docs for VM/cgroups, and the k8s docs for QoS/eviction.

## Practice exercises

1. From memory, reconstruct table B.2 (what counts toward the pod limit); check
   against the appendix.
2. Trace one past incident through decision tree C.1 and note where each step's
   evidence came from.
3. Pick one primary source (e.g. `obmalloc.c` or the cgroup v2 doc) and read the
   section behind a concept you found hard; write a two-line summary.

## Quiz questions

1. Define working set in one sentence and give its formula.
2. Which four `memory.stat` counters route your diagnosis, and to where?
3. Name the PEP behind `tracemalloc` and the one behind the free-threaded GIL.
4. Which CPython source file implements pymalloc, and which implements the cyclic
   GC?
5. From table B.4, match each symptom (`Bus error`, exit 137, `Evicted`,
   `resource_tracker` warning) to its cause.

## Suggested experiments

- Print tables B.1–B.4 as a one-page "memory card" and keep it at your desk.
- Turn decision trees C.1–C.4 into runbook diagrams for your team's wiki.
- Read `Objects/obmalloc.c`'s arena/pool logic and reconcile it with Chapter 4.7
  and Lab 6.

---

**This completes the handbook.** You've gone from "what is a byte of RAM" to
designing memory budgets and debugging production OOMs across Python, Linux,
Docker, and Kubernetes. Return to the [index](README.md) any time, and keep the
decision trees (C) and the ten commandments (Ch 21.10) close.

[← Chapter 21](21_best_practices.md) · [Back to index](README.md)
