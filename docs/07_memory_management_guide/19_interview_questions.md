<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 19 — 100+ Interview Questions

A graded question bank covering everything in this book, from "what is RSS" to
"design memory limits for a fleet." Each answer is a few sentences with a chapter
pointer so you can go deeper. Use it to self-test (cover the answers) or to run
interviews.

Grades: **Beginner** (fundamentals) → **Intermediate** (Python/Linux internals)
→ **Advanced** (containers, native, diagnosis) → **Staff** (design, trade-offs,
production judgment).

---

## Beginner (1–25)

**1. What is the difference between memory and storage?**
Memory (RAM) is fast, volatile, byte-addressable working space; storage (disk) is
slower, persistent, not directly addressable by the CPU. (Ch 1.1)

**2. What is virtual memory?**
A per-process private address space that the kernel maps to physical frames via
page tables, giving isolation, relocation, and overcommit. (Ch 1.4)

**3. What is a page? Default size on Linux?**
The fixed-size unit of memory management; 4 KiB on x86-64/ARM64. (Ch 1.7–1.8)

**4. What is the difference between a page and a page frame?**
A page is a chunk of *virtual* address space; a frame is the same-size chunk of
*physical* RAM the page maps to. (Ch 1.7)

**5. What is RSS?**
Resident Set Size — the amount of a process's memory currently in physical RAM.
(Ch 3.3)

**6. What is VSZ and why shouldn't you alert on it?**
Virtual Set Size — total virtual address space reserved, mostly untouched; it's a
promise, not a cost. (Ch 3.2)

**7. Anonymous vs. file-backed memory?**
Anonymous = your data (heap/stack/objects), swap-backed; file-backed = code /
mmap'd files, recoverable from disk. (Ch 1.10–1.11)

**8. Why is low `free` memory normal on Linux?**
Linux uses spare RAM for reclaimable page cache; look at `available`, not `free`.
(Ch 3.12)

**9. What is swap?**
Disk-backed overflow for anonymous pages when RAM is tight. (Ch 3.7)

**10. What is the page cache?**
The kernel's in-RAM cache of file contents; reclaimable under pressure. (Ch 3.9)

**11. What does OOMKilled mean and what's the exit code?**
The kernel SIGKILLed the process for exceeding available memory; exit code 137
(128 + 9). (Ch 6.11, 8.4)

**12. What is the heap? The stack?**
Heap = dynamic allocation region (grows up via `brk`); stack = per-thread call
frames (grows down). (Ch 2.5–2.6)

**13. Does `del x` free memory immediately?**
It drops a reference; if the refcount hits zero the object is freed to the
allocator — but not necessarily back to the OS. (Ch 4.3, 4.9)

**14. Why doesn't RSS drop after freeing objects?**
Memory returns to pymalloc/glibc, not the OS; arenas only release when fully
empty. (Ch 4.9)

**15. What is `sys.getsizeof`? Its limitation?**
Shallow size of one object; ignores referenced objects and native buffers.
(Ch 4.2, 17.1)

**16. Roughly how big is a Python `int`? Why?**
~28 bytes — every value is a boxed `PyObject` with a header. (Ch 4.2)

**17. What is a memory leak?**
Memory allocated but never released and unbounded over time. (Ch 11.1)

**18. Difference between a leak and high-but-stable memory?**
A leak grows without bound; stable-high is allocator caching/retention that
plateaus. (Ch 11.1, 11.3)

**19. What tool shows live per-process memory quickly?**
`top`/`htop` (RES), or `ps --sort=-rss`. (Ch 12.2, 16.2)

**20. What's the first thing to check when a node looks "out of memory"?**
The `available` column of `free`, not `free`. (Ch 3.12)

**21. What is a container, simply?**
A normal Linux process wrapped in namespaces (isolation of view) and cgroups
(resource limits). (Ch 7.1)

**22. What sets a container's memory limit?**
The cgroup `memory.max` (from `docker -m` / k8s `limits.memory`). (Ch 7.4, 8.2)

**23. What is `/dev/shm` and its default size in Docker?**
A RAM-backed tmpfs for shared memory; 64 MiB by default. (Ch 7.8, 9.2)

**24. Threads vs. processes for memory?**
Threads share one address space (cheap, no isolation); processes are separate
(isolated, guaranteed release on exit). (Ch 15.14)

**25. What does `gc.collect()` do?**
Runs the cyclic garbage collector to free reference cycles; it doesn't free
normal objects (refcounting already did) and rarely lowers RSS. (Ch 4.4, 4.8)

## Intermediate (26–55)

**26. How does CPython manage memory?**
Primarily reference counting (immediate/deterministic), plus a generational
cyclic GC for reference cycles. (Ch 4.3–4.6)

**27. Why does CPython need a cyclic GC if it has refcounting?**
Refcounting can't collect cycles (A↔B keep each other's count >0). (Ch 4.5)

**28. What is `pymalloc`? Arenas, pools, blocks?**
CPython's small-object (≤512B) allocator: arenas (256 KiB) → pools (4 KiB, one
size class) → blocks (object slots). (Ch 4.7)

**29. Why does the generational GC scan gen0 more often?**
Generational hypothesis: most objects die young, so scan young ones cheaply and
often. (Ch 4.6)

**30. Which objects does the GC track?**
Only container-like objects that can form cycles; atomic types (int, str, float)
are never tracked. (Ch 4.6)

**31. RSS vs. PSS vs. USS?**
RSS counts shared pages fully (over-counts); PSS apportions shared pages (sums
correctly); USS is private-only (dies with the process). (Ch 3.3–3.5)

**32. Why is summing `top`'s RES across workers wrong?**
It double-counts shared library pages; use PSS (`smem`). (Ch 3.3–3.4, 12.2)

**33. What is demand paging?**
Physical frames are allocated on first *touch*, not on allocation — why RSS grows
as you write, not as you `malloc`. (Ch 6.1)

**34. Minor vs. major page fault?**
Minor = page in RAM, just map it (fast); major = must fetch from disk/swap (slow,
latency killer). (Ch 6.3–6.4)

**35. What is the TLB and why do huge pages help?**
A CPU cache of virtual→physical translations; 2 MiB huge pages let one entry
cover more memory, cutting TLB misses. (Ch 6.5, 6.7)

**36. Why can THP inflate RSS?**
It rounds allocations up to 2 MiB, so lightly-touched regions consume full huge
pages. (Ch 6.7)

**37. What is copy-on-write in `fork()`?**
Child shares parent frames read-only; a page is copied only on write. (Ch 6.8)

**38. Why do pre-fork servers' memory savings erode in CPython?**
Refcount writes on object access trigger COW, privatizing "shared" pages over
time. (Ch 6.8)

**39. What is memory overcommit?**
The kernel promises more memory than exists, betting most won't be touched; when
promises are cashed, the OOM killer fires. (Ch 6.10–6.11)

**40. How does the OOM killer choose a victim?**
Highest `oom_score` (roughly memory share ± `oom_score_adj`) — possibly an
innocent hog, not the allocator that tipped it over. (Ch 6.11)

**41. Why is `tracemalloc` blind to NumPy memory?**
It hooks CPython's allocator; NumPy buffers use system `malloc`/`mmap` directly.
(Ch 5.2)

**42. NumPy view vs. copy?**
Slicing returns a view (shares memory); fancy/boolean indexing and dtype casts
copy. Check with `np.shares_memory`/`.base`. (Ch 5.3)

**43. Why is `sys.getsizeof(ndarray)` ~112 bytes?**
It's the wrapper size; the data buffer is a separate native allocation
(`arr.nbytes`). (Ch 5.3)

**44. The pandas `object`-dtype string trap?**
Strings as `object` store pointers to individual `str` objects — 10–20× the
Arrow-backed size. (Ch 5.4)

**45. What does `df.memory_usage(deep=True)` add?**
It counts the actual string/object payloads, not just the pointer array. (Ch 5.4)

**46. Why does a 3 MB JPEG cause a big RSS spike?**
Decoded pixels = W×H×channels×bytes (e.g. 72 MiB), independent of file size.
(Ch 5.5, 14.1)

**47. `__slots__` — what and why?**
Replaces per-instance `__dict__` with a fixed C array; big savings for millions
of instances. (Ch 4.11, 15.3)

**48. When does `gc.collect()` genuinely help?**
Reclaiming a just-dropped large cyclic structure, or pre-fork with `gc.freeze()`,
or batch boundaries. (Ch 4.8)

**49. Why doesn't `del` on a big list lower RSS but a big NumPy array might?**
Small objects sit in pinned pymalloc arenas; a large array is mmap-backed and
`munmap`s on free. (Ch 4.9, 5.3)

**50. What is `smaps_rollup` and why use it?**
Aggregated per-process Rss/Pss/Private/Anonymous/Swap — fast PSS/USS without
`smem`. (Ch 2.11, 3.16)

**51. What is a reference cycle and how do you find it?**
Objects referencing each other; `gc.DEBUG_SAVEALL`+`gc.garbage`, `objgraph`
backrefs. (Ch 4.5, 11.5)

**52. What is fragmentation in this context?**
Free memory trapped in half-used arenas pinned by survivors; RSS won't return.
(Ch 4.10, 11.7)

**53. `vmstat` si/so — what do they tell you?**
Swap in/out rates; sustained nonzero = thrashing (working set > RAM). (Ch 6.6,
16.6)

**54. How do you find *which line* leaks Python memory?**
`tracemalloc` snapshot diff (`compare_to`). (Ch 12.3, 17.3)

**55. How do you find *who retains* a leaked object?**
`objgraph.show_backrefs` / `gc.get_referrers`. (Ch 11.4, 17.7)

## Advanced (56–85)

**56. cgroups v1 vs v2 — key memory files?**
v1: `memory.limit_in_bytes`/`usage_in_bytes`; v2: `memory.max`/`current`/`stat`/
`events`. (Ch 7.3)

**57. Inside a container, why does `free` show host RAM?**
`/proc/meminfo` and CPU count aren't namespaced; only cgroup files reflect your
limit. (Ch 7.7)

**58. What memory counts toward a cgroup limit?**
Anonymous, tmpfs/`shmem`, non-reclaimable cache, and (v2) kernel/slab/socket
memory. (Ch 7.4, 3.14)

**59. What metric does Kubernetes use for OOM/eviction?**
Working set ≈ `memory.current − inactive_file` (non-reclaimable), not RSS/VSZ.
(Ch 3.14, 8.4)

**60. Requests vs. limits?**
Requests = scheduling reservation + eviction ranking; limits = hard cgroup cap
(exceed → OOMKilled). (Ch 8.2)

**61. QoS classes and how they're derived?**
Guaranteed (requests==limits), Burstable (some set), BestEffort (none) — sets
eviction order and `oom_score_adj`. (Ch 8.3)

**62. OOMKilled vs. Evicted — difference and fix?**
OOMKilled = you exceeded your own limit (kernel SIGKILL); Evicted = node pressure
(kubelet, graceful, QoS-ordered). Different fixes. (Ch 8.4–8.5)

**63. Why memory OOMs but CPU only throttles when you exceed limits?**
Memory is incompressible (can't reclaim what's in use → kill); CPU is
compressible (just slow you down). (Ch 8.2)

**64. Does `emptyDir` count as pod memory?**
Default (disk) no; `medium: Memory` (tmpfs) yes — charged to the cgroup. Always
`sizeLimit` it. (Ch 8.7)

**65. Why does a PyTorch DataLoader throw `Bus error`?**
Workers pass tensors via `/dev/shm`; the 64 MiB default is exhausted. (Ch 9.6)

**66. How do you enlarge `/dev/shm` in k8s (no `--shm-size`)?**
Mount a memory `emptyDir` at `/dev/shm`, sized inside `limits.memory`. (Ch 8.8,
9.8)

**67. `SharedMemory.close()` vs `.unlink()`?**
`close()` detaches this process; `unlink()` destroys the segment and frees RAM —
must be called once. (Ch 9.5)

**68. Signature of a shared-memory leak?**
Large `shmem` in `memory.stat`, flat RSS/tracemalloc, stale files in `/dev/shm`.
(Ch 9.7)

**69. RSS climbs but `tracemalloc`/`gc_objects` flat — what and which tool?**
A native leak/retention; use `memray`/`scalene`, not tracemalloc. (Ch 5.2, 11.6,
13.5)

**70. PyTorch GPU memory "never frees" — leak?**
Usually the caching allocator (`memory_reserved` > `memory_allocated`); benign.
`empty_cache()` returns unused blocks. (Ch 5.7, 14.4)

**71. Why is GPU memory not in RSS or the cgroup?**
It's device (VRAM) memory managed by the GPU/driver, a separate pool. (Ch 5.7)

**72. How to reduce RSS without code changes?**
`LD_PRELOAD` jemalloc/tcmalloc, `MALLOC_ARENA_MAX`, cap `*_NUM_THREADS`,
`malloc_trim`. (Ch 5.9–5.10, 15.13)

**73. Why cap `MALLOC_ARENA_MAX` in a container?**
glibc makes up to 8×cores arenas (each up to 64 MB); on a big host that reserves
GBs per process. (Ch 5.9)

**74. Why cap `OMP_NUM_THREADS` in a CPU-limited container?**
Native libs see host cores and spawn huge thread pools (each 8 MiB stack +
scratch), inflating memory. (Ch 5.6, 7.5)

**75. Explain the 7-step k8s memory debugging workflow.**
Confirm OOM → quantify vs limit → classify `memory.stat` → shape (leak/retention)
→ localize (tracemalloc/memray/shm/fd) → rule out node pressure → fix + verify
shape. (Ch 13)

**76. Which `memory.stat` counter routes your diagnosis and how?**
`anon`→Python/native, `shmem`→/dev/shm, `file`→cache, `slab`→fd/socket. (Ch 10.5,
13.3)

**77. How do you tell Python vs. native anon growth in a pod?**
Compare `len(gc.get_objects())` vs RSS: both grow → Python; RSS grows, objects
flat → native. (Ch 13.5)

**78. Six memory growth shapes and their meaning?**
Linear-climb=leak/retention, plateau=caching, rising-floor sawtooth=fragmentation,
returning sawtooth=healthy, periodic drops=cyclic GC, spike=bad input. (Ch 11.2)

**79. Worker recycling — what and when?**
Restart workers after N requests/RSS to reset fragmentation/retention; the
pragmatic fix for unfixable growth. (Ch 11.7, 15.11)

**80. Why does subprocess isolation guarantee memory release?**
Process exit is the only guaranteed return-to-OS; a child's RSS vanishes when it
finishes. (Ch 4.9, 15.12)

**81. How does backpressure prevent OOM?**
A bounded queue makes fast producers wait for slow consumers, capping in-flight
memory. (Ch 14.7, 15.1)

**82. Diagnose fragmentation vs. leak.**
Both grow, but fragmentation plateaus/creeps and RSS ≫ live data (tracemalloc);
`malloc_trim` reclaiming a chunk confirms retained free memory. (Ch 11.7)

**83. What is `oom_score_adj` and how does k8s use it?**
A −1000..1000 bias on OOM scoring; k8s sets it from QoS (Guaranteed protected,
BestEffort sacrificed first). (Ch 6.11, 8.3)

**84. How do you profile a distroless/slim pod image?**
`kubectl debug --target` an ephemeral container sharing the PID namespace, then
run py-spy/memray on PID 1. (Ch 18.9, 13.5)

**85. Why verify a memory fix over a long run, not a smoke test?**
A short test can't distinguish a plateau (fine) from a slow leak; verify the graph
shape changed and `oom_kill` stopped. (Ch 11.9, 13.7)

## Staff / Design (86–110)

**86. How do you size memory requests and limits for a service?**
Request ≈ steady-state working-set p50–p90 (honest, for scheduling); limit ≈ peak
+ 20–50% headroom. Measure working set, not RSS. (Ch 8.2, 21)

**87. Why not set limit == request everywhere (all Guaranteed)?**
Guaranteed is safest but wastes headroom (no bursting); Burstable with honest
requests packs nodes better. Trade safety vs. density. (Ch 8.3)

**88. Why not set very high limits "to be safe"?**
High limit ≫ request overpacks nodes (scheduled by request), causing eviction
storms, and hides leaks until they OOM at the ceiling. (Ch 8.10, 13.8)

**89. Design memory monitoring/alerting for a fleet.**
Alert on working-set/limit ratio, `oom_kill` rate, major-fault rate, and shmem;
track PSS for capacity; not VSZ, not minor faults. (Ch 3, 21)

**90. Capacity-plan N workers on a node.**
Budget with PSS (shared libs counted once), not summed RSS; leave headroom for
page cache + kernel + spikes. (Ch 3.4, 21)

**91. When would you swap the allocator fleet-wide?**
Long-running data/ML services with fragmentation/high RSS: jemalloc/tcmalloc via
`LD_PRELOAD`, measured on a canary. (Ch 5.10, 15.13)

**92. How do you serve a large read-only model across many workers efficiently?**
Load once as a native buffer (NumPy/Arrow) or shared memory so COW doesn't
duplicate it; `gc.freeze()` pre-fork. (Ch 6.8, 9, 14.9)

**93. Design a memory-safe image/OCR pipeline.**
Stream pages (generators), close each image, cap dimensions/DPI, isolate risky
decodes in subprocesses with limits, bound concurrency. (Ch 14.1–14.3, 15)

**94. Design a memory-bounded streaming consumer.**
Bounded queues (backpressure), small fetch batches, incremental processing +
prompt release, scale partitions/consumers. (Ch 14.7, 14.12)

**95. Trade-offs of threads vs. processes vs. async for a memory-bound service?**
Threads/async: low memory, shared state, no CPU parallelism; processes: isolation
+ guaranteed release but N× base + duplication. Choose by workload + release
needs. (Ch 15.14)

**96. How do you prevent a single bad input from OOMing a worker?**
Validate sizes, run the risky op in a subprocess with its own `RLIMIT_AS`/cgroup,
timeouts. (Ch 14.2, 15.12, 17.4)

**97. Your fleet OOMs only under peak traffic — approach?**
Distinguish spike (transient peak → raise limit/bound the op) from leak (unbounded
→ find reference); check whether it's per-container OOM or node pressure. (Ch 11,
8.5, 13)

**98. How do you roll out a memory fix safely?**
Canary with heavy profiling behind a flag, compare working-set shape vs. baseline
over a long window, then progressive rollout; keep worker recycling as a net.
(Ch 12.5, 13.7)

**99. When is a memory limit increase the right fix vs. a band-aid?**
Right when it's a legitimate larger working set/peak; band-aid when it masks a
leak (log a follow-up — it'll OOM at the new ceiling). (Ch 13.8)

**100. How do you set up continuous memory profiling in production?**
Always-on low-overhead sampling (pyroscope + memray/eBPF) shipped to a server so
you can inspect the pod's allocations at the OOM moment. (Ch 12.3)

**101. GC tuning strategy for a low-latency service with a big heap?**
Raise thresholds or `gc.freeze()` warm objects to avoid gen2 pauses; measure —
don't blindly `gc.disable()` (risks cycle growth). (Ch 4.6)

**102. How do you budget memory for `/dev/shm`-heavy workloads (ML)?**
Size shm as a bounded memory `emptyDir` *inside* the limit; account it plus the
app working set under `limits.memory`. (Ch 9.8, 8.8)

**103. Explain the full alloc→fault→reclaim→OOM lifecycle.**
malloc reserves → first touch faults in a frame → under pressure kswapd reclaims
(drop clean, swap anon) → direct-reclaim stalls → nothing left → OOM SIGKILL.
(Ch 6.12)

**104. Why can an "innocent" pod get OOM-killed on a busy node?**
Node-level OOM kills the highest `oom_score` process, which may be a different pod
than the one that tipped memory over. (Ch 6.11, 8.5)

**105. How do you decide between `spawn` and `fork` for multiprocessing memory?**
`fork` shares via COW (cheap but erodes + inherits state/locks); `spawn` re-imports
fresh (no sharing, no COW surprises). (Ch 6.8)

**106. Design a cache that can't cause an OOM.**
Bound size + TTL (`TTLCache`/`lru_cache(maxsize=...)`), or move it out-of-process
(Redis) so it doesn't count against the pod. (Ch 15.5, 14.10)

**107. What memory SLOs/limits would you set for a batch vs. a service?**
Batch: high limit, peak-driven, subprocess isolation, exits reset RSS. Service:
tight-ish limit + recycling + headroom for spikes; alert on trend. (Ch 21)

**108. How do you detect and handle kernel/slab-driven OOM?**
`slabtop`/`memory.stat slab`, `lsof` fd counts; fix fd/socket leaks and pool
limits — user RSS looks small. (Ch 3.13, 13.5e)

**109. How do you communicate a memory incident's root cause?**
State the kind (Python/native/shm/kernel), the shape (leak/retention/spike), the
evidence (memory.stat + profiler), the fix, and the verification (shape changed,
oom_kill=0). (Ch 13.7)

**110. What's your mental checklist when a pod OOMs?**
Is it memory (137)? working set vs limit? `memory.stat` kind? shape? Python or
native? node pressure? fix + verify. (Ch 13.0)

---

## Key takeaways

- **The recurring themes interviewers probe:** RSS vs PSS vs USS; refcounting vs
  GC; why RSS won't drop; native invisibility to `tracemalloc`; requests vs
  limits + QoS; OOMKilled vs Evicted; leak vs retention vs fragmentation.
- **Answers should name the mechanism *and* the metric/tool** — "it's native, so
  RSS grows but tracemalloc is flat; use memray" beats "there's a leak."
- **Staff-level answers weigh trade-offs** (safety vs. density, threads vs.
  processes, fix vs. stopgap) and always mention **verification**.

## Practice exercises

1. Cover the answers and grade yourself section by section; note which chapter to
   re-read for each miss.
2. Pick 10 questions and answer out loud in ≤30 seconds each, naming the metric
   and tool.
3. For every "Advanced" question, write the one command you'd run to demonstrate
   the answer.

## Quiz questions

1. Give the three-number summary of CPython memory management in one sentence.
2. State the single decisive test for leak-vs-not, and the fix for each branch.
3. Explain OOMKilled vs Evicted to a new engineer in two sentences.
4. Why is PSS the right metric for capacity planning and USS for leak hunting?
5. Name the four questions every OOM investigation narrows to.

## Suggested experiments

- Turn 20 of these into a flashcard deck; drill until each answer is <20 seconds.
- Run a mock interview: one person picks questions across grades, the other
  answers and must cite the metric + tool.
- For each Staff question, sketch the YAML/architecture on a whiteboard and
  defend the trade-offs.

---

*Next up: **Chapter 20 — Practical Labs**: hands-on exercises (build a leak, fix
it, profile NumPy, measure RSS/PSS, use tracemalloc/memray, debug a k8s OOM,
exhaust `/dev/shm`, profile multiprocessing) — each with expected output and
explanation.*

[← Chapter 18](18_kubernetes_cheatsheet.md) · [Back to index](README.md) · [Chapter 20 →](20_practical_labs.md)
