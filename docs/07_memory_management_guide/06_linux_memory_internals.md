<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 6 — Linux Memory Internals

We've gone from RAM (Ch 1) to segments (Ch 2) to metrics (Ch 3) to CPython (Ch
4) to native allocators (Ch 5). Now we descend to the **kernel** — the layer
that turns "my program touched an address" into "a physical frame gets wired
up," and the layer that decides, when RAM runs out, **which process dies**.

This chapter is what separates engineers who can *read* an OOM from those who
can *predict and prevent* one. It's also the densest interview territory:
demand paging, page faults, the TLB, huge pages, NUMA, copy-on-write, overcommit,
and the OOM killer.

> Prerequisites: Ch 1 (pages, virtual↔physical, anonymous vs. file-backed) and
> Ch 3 (RSS, swap, available, committed). Ch 7–8 apply all of this inside
> cgroups/containers.

## 6.1 Demand paging — nothing is real until you touch it

**What it is.** When you `malloc`/`mmap` memory, the kernel does **not** allocate
physical frames. It only records a *virtual mapping* (a VMA — virtual memory
area) and marks the pages "not present." The first time your code **reads or
writes** a page, the CPU triggers a **page fault**, and *only then* does the
kernel find a free physical frame, zero it, wire it into the page table, and
resume your instruction.

```
   ptr = mmap(1 GB)            <- 1 GB of VIRTUAL address space reserved
                                  RSS unchanged. Committed_AS += 1 GB (a promise)
   ptr[0] = 1                  <- PAGE FAULT on page 0 -> 1 frame (4 KiB) wired
                                  RSS += 4 KiB   (NOT 1 GB!)
   memset(ptr, 0, 1 GB)        <- faults in all 262144 pages one by one
                                  RSS += 1 GB    (now it's real)
```

- **Why it exists.** Programs reserve far more than they touch (BSS, big arrays,
  thread stacks, sparse structures). Backing only *touched* pages saves enormous
  RAM and makes `fork()`/overcommit possible.
- **Consequences you've already seen.** This is *why* VSZ ≫ RSS (Ch 3), why a
  100 GB reservation succeeds on a 4 GB box (Ch 1), and why RSS grows as you
  *write* rather than as you *allocate*.
- **Production tell.** A process whose RSS climbs steadily during a loop that
  "already allocated" its buffer is faulting pages in on first touch — normal,
  not a leak.

## 6.2 Page tables — the virtual→physical map

**What it is.** The per-process data structure the MMU walks to translate a
virtual address to a physical frame. On x86-64 it's a **4-level radix tree**
(PGD → PUD → PMD → PTE); each level indexes 9 bits of the address, the final PTE
points to a 4 KiB frame.

```
   64-bit virtual address (48 bits used):
   [ 9 bits PGD | 9 bits PUD | 9 bits PMD | 9 bits PTE | 12 bits offset ]
        |            |            |            |            |
        v            v            v            v            v
      PGD[.] ----> PUD[.] ----> PMD[.] ----> PTE[.] ----> physical frame + offset

   A miss/"not present" bit at any level -> PAGE FAULT (kernel handles it, 6.1/6.4)
```

- **Why 4 levels.** A flat table for 128 TiB would be gigantic; a sparse tree
  only allocates the branches you actually use.
- **Cost.** Page tables themselves consume RAM (`VmPTE` in
  `/proc/<pid>/status`). Millions of sparse mappings ⇒ big page tables — a real,
  if rare, memory cost. A naive walk is 4 memory reads per translation, which is
  why the **TLB** (§6.5) exists.
- **Where it lives.** Kernel memory, per process; on `fork()` the tables are
  copied but the frames are shared copy-on-write (§6.8).

## 6.3 Page faults — the central event

Every time a "not present" page is accessed, the CPU raises a fault and hands
control to the kernel. There are three flavors:

```
   +-----------------------------------------------------------------+
   | MINOR fault  | page is in RAM but not yet in THIS page table:   |
   |              | - first touch of anon/BSS (map a zero frame)     |
   |              | - shared lib already in page cache (just map it) |
   |              | - COW read of a shared frame                     |
   |              | => fast: no disk I/O. Microseconds.              |
   +--------------+--------------------------------------------------+
   | MAJOR fault  | page must be fetched from DISK:                  |
   |              | - file-backed page not in page cache -> read()   |
   |              | - anonymous page previously swapped out -> swapin|
   |              | => slow: disk I/O. Milliseconds. LATENCY KILLER. |
   +--------------+--------------------------------------------------+
   | INVALID/     | access to an address with no valid mapping or   |
   | protection   | wrong permission (write to r-x) => SIGSEGV       |
   +-----------------------------------------------------------------+
```

**Inspect them:**

```bash
ps -o min_flt,maj_flt -p $PID         # cumulative minor / major faults
/usr/bin/time -v python app.py        # "Minor (reclaiming a frame) page faults" etc.
vmstat 1                              # not faults, but si/so (swap in/out) + b (blocked)
perf stat -e minor-faults,major-faults -p $PID   # live rates
```

## 6.4 Minor vs. major page faults — why this matters in production

- **Minor faults are cheap and constant** — every program does millions; ignore
  the count, it's normal.
- **Major faults are the enemy of latency.** A rising `maj_flt` rate means your
  working set no longer fits in RAM and the kernel is fetching pages from disk —
  either swapping anonymous pages back in (thrashing, §6.6) or re-reading
  evicted file/library pages. A service that was fast becomes 100–1000× slower
  with *no code change*, purely because RAM got tight.
- **The classic incident.** A node fills up; the kernel evicts your process's
  cold code/data pages to make room; your next request majors-faults them back
  in one 4 KiB read at a time. p99 latency explodes. `pidstat -r 1` shows
  `majflt/s` spiking. The fix is memory headroom, not code.

> **Rule:** Alert on **major** fault *rate* and swap in/out (`si`/`so`), never on
> minor faults.

## 6.5 The TLB (Translation Lookaside Buffer)

**What it is.** A small, extremely fast CPU cache of recent virtual→physical
translations, so the MMU can skip the 4-level page-table walk on a hit.

- **Why it exists.** Walking the page table on *every* memory access would be
  ruinous. The TLB caches ~hundreds–thousands of translations.
- **TLB miss** ⇒ a page-table walk (still RAM, not disk — cheaper than a fault
  but not free). **TLB shootdowns** (invalidating entries across cores when
  mappings change) cost real cycles in multithreaded programs.
- **Why you care: reach.** A TLB with 1536 entries × 4 KiB pages "reaches" only
  ~6 MiB of memory before misses dominate. Large working sets (databases, big
  arrays, ML) thrash the TLB — which is the entire motivation for **huge pages**.

## 6.6 Swap (revisited from the kernel side)

**What it is.** Disk-backed overflow for **anonymous** pages. When RAM is tight,
the kernel's reclaim (`kswapd`) evicts cold anon pages to the swap device and
faults them back on access (a **major** fault).

- **When it grows/shrinks.** Grows under pressure; shrinks as pages are read back
  or freed. `swapiness` (`vm.swappiness`, 0–100/200) tunes how eagerly the kernel
  swaps anon vs. reclaims file cache.
- **Thrashing.** If the working set genuinely exceeds RAM, pages ping-pong to and
  from swap continuously — CPU stalls on I/O, throughput collapses. `vmstat 1`
  with high `si`/`so` is the signature.
- **Kubernetes reality (recap Ch 3).** Nodes traditionally run **swap off**, so
  there's no graceful degradation — exceed memory and you're **OOM-killed**
  immediately. Node swap is newer/opt-in; assume off unless you enabled it.

## 6.7 Huge pages & Transparent Huge Pages (THP)

**What it is.** Instead of 4 KiB, map memory in **2 MiB** (or 1 GiB) chunks. One
huge page = one TLB entry covering 2 MiB, so the TLB "reaches" 512× more memory —
big speedups for large-working-set apps (databases, JVMs, ML).

Two flavors:

- **Explicit HugeTLB** — reserved up front (`vm.nr_hugepages`), mounted, opt-in
  per app. Predictable; used by databases.
- **Transparent Huge Pages (THP)** — the kernel *automatically* promotes eligible
  anonymous regions to 2 MiB pages and has `khugepaged` defrag them in the
  background. Modes: `always`, `madvise`, `never` (`/sys/kernel/mm/transparent_hugepage/enabled`).

**Why THP is a frequent, surprising production problem:**

- **RSS bloat / rounding.** THP rounds allocations up to 2 MiB. A process that
  touches 8 KiB in each of many regions can get whole 2 MiB pages, inflating RSS
  far beyond live data. In `smaps` you'll see `AnonHugePages` large.
- **Latency spikes & fragmentation.** `khugepaged` compaction and the cost of
  allocating a contiguous 2 MiB under memory pressure cause stalls. Redis,
  MongoDB, and many latency-sensitive services **officially recommend disabling
  THP** (`madvise` or `never`).
- **Container gotcha.** THP-inflated RSS counts against your cgroup and can OOM
  you for memory you're not really using.

```bash
cat /sys/kernel/mm/transparent_hugepage/enabled     # [always] madvise never
grep -i huge /proc/meminfo                           # AnonHugePages, HugePages_*
grep AnonHugePages /proc/$PID/smaps_rollup           # THP used by a process
# Common mitigation (host/node-level):
echo madvise > /sys/kernel/mm/transparent_hugepage/enabled
```

## 6.8 Copy-on-write (COW) and `fork()`

**What it is.** `fork()` creates a child process that *shares* all the parent's
physical frames read-only; the page tables are copied but the frames are not.
Only when parent or child **writes** a shared page does the kernel copy that one
page (a minor fault) and give the writer a private copy. Reads stay shared.

```
   Parent RSS = 500 MB
        |  fork()
        v
   Child shares all 500 MB (0 copied)  -> "free" fork, RSS barely moves
        |  child writes to some pages
        v
   Each written PAGE is copied on demand -> RSS grows only by what's mutated
```

- **Why it exists.** Makes process creation cheap and lets pre-loaded data be
  shared. This is the foundation of **pre-fork servers**: Gunicorn/uWSGI load the
  app once, then `fork()` N workers that *share* the code and warm data.
- **The Python COW pitfall (critical).** CPython **mutates every object's
  refcount on access** (Ch 4). Merely *reading* a shared Python object bumps
  `ob_refcnt` → writes the page → triggers COW → the "shared" memory becomes
  private, worker by worker. So the memory savings from pre-fork **erode over
  time**; N workers drift toward N private copies. Also the **cyclic GC** writes
  to objects during collection.
- **Mitigations.** `gc.freeze()` after loading (moves warm objects out of GC
  scanning so they aren't written), `gc.disable()` in workers, load big
  read-only data as NumPy/Arrow buffers (no per-object refcounts → stays shared),
  or use `fork` server models carefully. Measure with **PSS** (Ch 3): true
  sharing shows PSS ≪ sum(RSS); COW erosion shows PSS rising toward RSS.
- **Multiprocessing.** `multiprocessing` with the `fork` start method inherits
  this; `spawn` (default on macOS/Windows, safer) re-imports fresh — no sharing
  but no COW surprises. DataLoader workers (Ch 5) are forks.

## 6.9 NUMA (Non-Uniform Memory Access)

**What it is.** On multi-socket servers, RAM is divided into **nodes**, each
attached to a CPU socket. A core accessing its **local** node's memory is fast;
accessing a **remote** node's memory (across the interconnect) is slower.

- **Why you care.** A thread scheduled on socket 1 but whose data was allocated
  on node 0 pays a latency/bandwidth penalty on every access. For memory-bound
  workloads (big arrays, in-memory DBs, ML) this is a 10–30% swing.
- **Default policy.** Linux allocates on the node of the **first-touching** CPU
  ("first-touch"), which usually does the right thing if you initialize data on
  the same thread that uses it.
- **Inspect/control.**

```bash
numactl --hardware                 # nodes, sizes, distances
numastat -p $PID                   # local vs remote allocations for a process
numactl --cpunodebind=0 --membind=0 python app.py   # pin to node 0
```

- **Container note.** Kubernetes has a **Topology Manager** and CPU/memory
  pinning for NUMA-sensitive workloads; most apps can ignore NUMA, but
  high-performance data/ML services on big nodes should not.

## 6.10 Memory overcommit

**What it is.** The kernel lets processes *promise* (commit) more memory than
physically exists, betting that not all of it will be touched (demand paging,
§6.1). Governed by `vm.overcommit_memory`:

| Mode | `vm.overcommit_memory` | Behavior |
|---|---|---|
| **Heuristic** (default) | `0` | Allow "reasonable" overcommit; reject wildly large single allocs |
| **Always** | `1` | Never refuse `malloc`/`mmap` (used by Redis for `fork`-save) |
| **Never** | `2` | Strict: total commit capped at `swap + RAM×overcommit_ratio`; `malloc` fails instead of overcommitting |

- **The trade-off.** Overcommit enables `fork()`, sparse arrays, and efficient
  memory use — but it means `malloc` **succeeding is not a guarantee** the memory
  exists. When processes cash in more promises than RAM+swap can cover, something
  has to give: the **OOM killer** (§6.11).
- **`Committed_AS` vs `CommitLimit`** (Ch 3): watch these to see how deep the
  overcommit is. Mode `2` trades "no surprise OOM kills" for "some `malloc`s fail"
  — chosen by systems that must never be killed.

## 6.11 The OOM killer — how Linux decides who dies

**What it is.** When the kernel truly cannot satisfy a memory request (no free
frames, nothing reclaimable, swap full or absent), it invokes the
**Out-Of-Memory killer**: it scores every process and **SIGKILLs** the worst
offender to free memory.

**How the victim is chosen:**

```
   For each process, compute oom_score (roughly):
       base = proportion of available memory it uses (its RSS+swap share)
       adjust by oom_score_adj  (-1000 .. +1000, user/operator tunable)
   Kill the process with the HIGHEST oom_score.
   => "biggest memory hog" usually dies, but adj lets you protect/sacrifice.
```

- **Global vs. cgroup OOM.** The above is the **system-wide** OOM killer. Inside
  a container, hitting the **cgroup** `memory.max` triggers a **cgroup-scoped**
  OOM kill that targets a process *within that container* — this is your
  Kubernetes `OOMKilled` (Ch 7–8). Same mechanism, narrower scope.
- **What you see.**

```bash
dmesg -T | grep -i -E 'killed process|out of memory|oom'
# Out of memory: Killed process 12345 (python) total-vm:9GB, anon-rss:8GB ...
journalctl -k | grep -i oom
cat /proc/$PID/oom_score        # current score
cat /proc/$PID/oom_score_adj    # tunable bias (-1000 = never kill)
```

- **Tuning.** `oom_score_adj = -1000` makes a process (near-)immune (used for
  critical daemons); positive values sacrifice it first. Kubernetes sets these
  automatically based on **QoS class** (Guaranteed pods get protective scores,
  BestEffort get sacrificed first — Ch 8).
- **Exit code.** A SIGKILL (signal 9) shows up as exit code **137** (128+9) —
  the number you see on `OOMKilled` pods (Ch 3.14, 8, 13).
- **Misconception.** "The OOM killer kills the process that asked for the memory
  that couldn't be satisfied." **No** — it kills the highest-scoring process,
  which may be a *different, innocent* process (the memory hog), not the one
  whose allocation tipped the system over. This is why an unrelated pod on a
  packed node can die.

## 6.12 The full lifecycle: allocation → fault → reclaim → OOM

```
   malloc/mmap  -->  demand fault on touch  -->  frame wired, RSS grows
        |                                              |
        |                                    memory gets tight
        |                                              v
        |                          kswapd reclaims:  drop clean file pages (free),
        |                          write dirty pages, swap out cold anon (major
        |                          faults later)
        |                                              |
        |                                    still not enough / no swap
        |                                              v
        |                          direct reclaim stalls the allocating thread
        |                                              |
        |                                    truly nothing to reclaim
        |                                              v
        +------------------------------------->  OOM KILLER: SIGKILL victim (137)
```

Every production memory incident is somewhere on this pipeline. Diagnosing it =
figuring out *which stage* you're stuck at: growing RSS (Ch 4–5), major-fault
thrashing (§6.4/6.6), or a hard OOM (§6.11).

---

## Key takeaways

- **Demand paging:** memory becomes real (RSS) only when *touched*, not when
  allocated — the root of VSZ≫RSS and overcommit.
- **Minor faults are free and constant; major faults hit disk and destroy
  latency.** Alert on major-fault rate and `si`/`so`, never minor faults.
- **The TLB** motivates **huge pages**; but **THP** silently bloats RSS and adds
  latency — a top reason latency-sensitive services set THP to `madvise`/`never`.
- **COW `fork()`** makes pre-fork servers cheap, but **CPython refcount writes
  erode the sharing** — use `gc.freeze()`/`gc.disable()` and NumPy/Arrow buffers;
  watch **PSS** to see erosion.
- **Overcommit** means `malloc` success ≠ memory exists; when promises exceed
  RAM+swap the **OOM killer** SIGKILLs the highest-`oom_score` process (exit
  **137**) — possibly an innocent bystander. Kubernetes maps QoS → `oom_score_adj`.

## Practice exercises

1. `mmap`/allocate 1 GiB but touch only the first page; show `VmRSS` barely
   moves. Then `memset` it all and show RSS jump by ~1 GiB. Explain via demand
   paging.
2. Run a program under `/usr/bin/time -v` and read off minor vs. major page
   faults. Then run it on a memory-starved box and watch major faults appear.
3. `cat /sys/kernel/mm/transparent_hugepage/enabled` and
   `grep AnonHugePages /proc/self/smaps_rollup`. Is THP inflating any process?
4. Fork a Python process that holds a large dict; compare `sum(RSS)` vs `PSS`
   (Ch 3) before and after the child *reads* the dict a lot. Explain the COW
   erosion.

## Quiz questions

1. Why does allocating 10 GB on an 8 GB machine often succeed, and what makes it
   eventually fail?
2. Distinguish minor and major page faults with a concrete example of each.
   Which one should page you at 3 a.m.?
3. What problem do huge pages solve, and why do many databases *disable* THP?
4. Explain why the memory savings of a Gunicorn pre-fork server erode over time
   in CPython specifically. Name two mitigations.
5. The OOM killer fires. Does it kill the process whose allocation failed?
   How is the victim actually chosen, and what exit code results?
6. How does `vm.overcommit_memory=2` change `malloc` behavior and the OOM
   picture?
7. What is first-touch NUMA allocation and when does it hurt you?

## Suggested experiments

- Write a loop that touches one page per iteration of a large `mmap` and plot
  `VmRSS` over time — watch the staircase of demand faults.
- Toggle `MALLOC_ARENA_MAX` and THP (`madvise` vs `always`) on the same
  allocation-heavy workload; compare `AnonHugePages` and total RSS in
  `smaps_rollup`.
- In a memory-limited container (`docker run -m 256m`), allocate until the
  **cgroup** OOM killer fires; capture the `dmesg` line and confirm exit 137.
  (Full lab in Chapter 20.)
- Fork a process holding a big Python list vs. a big NumPy array; use PSS to show
  the NumPy buffer stays shared (no per-object refcount writes) while the list
  erodes.

---

*Next up: **Chapter 7 — Docker Memory**, where all of this moves inside a
container: cgroups (v1 vs v2), namespaces, memory/CPU limits, `/dev/shm` &
`--shm-size`, tmpfs, the overlay filesystem and writable layer, and what
*actually* counts as your container's memory.*

[← Chapter 5](05_native_memory.md) · [Back to index](README.md) · [Chapter 7 →](07_docker_memory.md)
