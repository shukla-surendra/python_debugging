<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 3 — Memory Metrics

This is the most *practically important* chapter in the first half of the book.
Every memory incident you will ever debug comes down to reading a number and
knowing what it actually means. Engineers waste days because they compared the
wrong two numbers — `top`'s RSS against a container limit, or `free`'s "used"
against total RAM — and drew a false conclusion.

By the end you will know, for every metric: **what it counts, what it
double-counts, whether shared pages inflate it, whether page cache is in it,
and — the money question — which number Kubernetes uses to decide to kill your
pod.**

> Prerequisites: Chapter 1 (virtual vs. physical, anonymous vs. file-backed)
> and Chapter 2 (`/proc/<pid>/maps`, `smaps_rollup`). We read those same files
> here, now interpreting the byte counts.

## 3.1 The one diagram that explains all the metrics

Picture a single process's pages, colored by how they're shared:

```
   A process's resident pages (each box = one 4 KiB physical frame)

   PRIVATE, anonymous            SHARED with other processes
   (only this process)           (libc, python .so, mmap'd files)
   +----+----+----+----+         +====+====+====+====+
   | H  | H  | S  | S  |         || L || L || L || L ||   L = shared library
   +----+----+----+----+         +====+====+====+====+       code page
   | H  | H  | STK| STK|         || L || L ||    ||    ||
   +----+----+----+----+         +====+====+====+====+
     ^ heap/anon = USS             ^ shared: split N ways for PSS

   VSZ  = every mapping, resident or not, private or shared, touched or not
   RSS  = PRIVATE frames + FULL shared frames        (over-counts sharing)
   PSS  = PRIVATE frames + (shared frames / #sharers)(fair share)
   USS  = PRIVATE frames only                        (what you'd reclaim if
                                                       this process died)
```

Three sentences to memorize:

- **VSZ** is a *promise* (address space reserved), not a *cost*.
- **RSS** is real RAM but **counts shared pages in full for every sharer**, so
  summing RSS across processes double-, triple-, N-counts shared libraries.
- **PSS** fixes that by dividing shared pages by the number of sharers, so
  **`sum(PSS)` over all processes = actual physical RAM used**. USS is the
  purely-private part.

## 3.2 VSZ / VSS — Virtual Set Size

- **What it is.** The total size of the process's virtual address space — the
  sum of **all** mappings in `/proc/<pid>/maps`, whether or not a single byte is
  resident in RAM. `VmSize` in `/proc/<pid>/status`; `VSZ` in `ps`.
- **Why it exists.** It's the natural "how big is the address space" number and
  is cheap for the kernel to report.
- **When it grows.** Any `mmap`/`malloc` *reservation*, thread stacks (8 MiB
  each of reservation), `MAP_NORESERVE` regions, glibc arenas, guard pages.
- **Returns to OS?** On `munmap`. But VSZ is so loosely correlated with real
  cost that watching it is usually noise.
- **Common misconception (the big one).** "VSZ is how much memory my program
  uses." **No.** A process can show 20 GB VSZ and 60 MB RSS. glibc's malloc,
  many threads, and CUDA/`jemalloc` routinely reserve huge virtual regions they
  never touch. **Never alert on VSZ.**
- **When it *is* useful.** A sudden VSZ explosion with flat RSS can hint at
  runaway `mmap` reservations or a thread leak (each thread = +8 MiB VSZ).

## 3.3 RSS — Resident Set Size (the one everyone quotes)

- **What it is.** The amount of the process's memory that is **currently
  resident in physical RAM**, in pages. `VmRSS` in `/proc/<pid>/status`; `RES`
  in `top`; `RSS` in `ps`.
- **Where it lives / what's in it.** RSS = **anonymous resident** (heap, stack,
  your objects, NumPy buffers) **+ file-backed resident** (the parts of shared
  libraries and mmap'd files paged in) — and it counts **every shared page at
  full size for this process**.
- **When it grows.** As you touch pages: allocate + write objects, fault in
  library code, read through an mmap'd file.
- **When it shrinks.** When pages are freed *and* returned to the OS
  (Chapter 2/4: heap rarely does; large mmaps do), or reclaimed under pressure
  (clean file pages, or anon pushed to swap).
- **Returns to OS?** Partially and reluctantly — the crux of "RSS won't drop."
- **Common misconception.** "Sum of RSS = RAM used by these processes." **Wrong
  by a lot** when they share libraries. Five Python workers each reporting
  300 MB RSS do *not* use 1.5 GB — much of that 300 MB is the *same* shared libc
  and interpreter pages counted five times. Use PSS for totals.
- **Production issue.** RSS is nonetheless **the number your container runtime
  and Kubernetes care about for a single container** (via cgroup accounting,
  §3.14) — because within one cgroup you *do* pay for anonymous pages once.

```bash
grep VmRSS /proc/$PID/status          # KB resident
ps -o rss= -p $PID                    # KB resident (ps)
```

## 3.4 PSS — Proportional Set Size (the honest one)

- **What it is.** Like RSS, but each **shared** page is divided by the number of
  processes mapping it. A page shared by 5 processes contributes 1/5 of a page
  to each one's PSS. Private pages count fully.
- **Why it exists.** So that **`sum(PSS)` across all processes equals the actual
  physical RAM consumed** — no double counting. It's the correct metric for "how
  much RAM does this *fleet of processes* really use."
- **Where to get it.** `/proc/<pid>/smaps_rollup` (field `Pss:`), or the `smem`
  tool (Chapter 12).
- **When it grows/shrinks.** Same triggers as RSS, but a shared page's
  contribution *drops* when more processes map it (more sharers = smaller
  share) and *rises* when sharers exit.
- **Common misconception.** "PSS is always much smaller than RSS." Only when
  there's real sharing. For a process dominated by private anonymous data (a big
  Pandas job), PSS ≈ RSS ≈ USS.
- **Production use.** Capacity planning: to fit N Gunicorn workers on a node,
  budget with **PSS**, not RSS. This is the difference between "we need a 32 GB
  node" and "16 GB is plenty."

```bash
grep -E '^Pss:' /proc/$PID/smaps_rollup    # this process's fair share, KB
```

## 3.5 USS — Unique Set Size

- **What it is.** Only the pages **private to this process** — nothing shared.
  Equivalently: the RAM that would be **freed if this process died right now**.
- **Why it exists.** Answers "how much is *this specific process* uniquely
  costing me?" — the best signal for "which worker is leaking."
- **Where to get it.** `smem` (`USS` column), or sum `Private_Clean` +
  `Private_Dirty` from `smaps`.
- **Production use.** Comparing USS across identical workers instantly reveals
  the one that's leaking (its private/anon grows while shared stays flat).

**RSS ≥ PSS ≥ USS**, always. Memorize that ordering; it's a great sanity check
when a tool reports something weird.

## 3.6 Shared memory (in the metrics sense)

- **What it is.** Pages mapped by more than one process: shared-library code,
  `MAP_SHARED` file mappings, and explicit shared memory (`/dev/shm`, SysV/POSIX
  shm — Chapter 9). In `smaps`: `Shared_Clean` + `Shared_Dirty`.
- **Why it matters for metrics.** It's exactly the part RSS over-counts and PSS
  apportions. `RSS − USS` ≈ this process's shared footprint.
- **Production issue.** Explicit shared memory (`/dev/shm`, `multiprocessing.
  shared_memory`, PyTorch DataLoader workers) is **anonymous-like and counts
  against the cgroup limit** even though it's "shared" — a classic surprise
  OOM. Full treatment in Chapter 9.

## 3.7 Swap

- **What it is.** Disk space used as an overflow for **anonymous** pages when
  RAM is tight. The kernel evicts cold anon pages to swap and faults them back
  on access.
- **Where it lives.** A swap partition/file on disk; per-process usage is
  `VmSwap` in `/proc/<pid>/status` and `Swap:` in `smaps`.
- **When it grows/shrinks.** Grows under memory pressure; shrinks as pages are
  faulted back or freed.
- **Returns to OS?** Freed when the owning pages are freed.
- **Common misconception.** "Swap means my app is broken." Not necessarily — a
  little swap of genuinely-cold pages is fine. **Sustained** swap-in/out
  (thrashing) tanks latency and *is* a problem (watch `si`/`so` in `vmstat`).
- **Kubernetes reality.** Historically **swap was disabled** on Kubernetes nodes
  (kubelet required it off), so anon pages that don't fit → **instant OOM kill**,
  no graceful degradation. Node-level swap support is newer/opt-in (beta) and
  often still off in practice — assume "no swap" unless you've explicitly
  enabled and tested it (Chapter 8).

## 3.8 Working set

- **What it is.** The set of pages a process is **actively using** over a recent
  time window — its "hot" footprint. Conceptually smaller than RSS (which
  includes cold-but-resident pages).
- **Why it exists.** The kernel keeps hot pages resident and evicts cold ones;
  the working set is what it's trying to keep in RAM.
- **Where you'll meet it by name.** **Kubernetes** reports
  `container_memory_working_set_bytes` — and **this is the number the kubelet
  compares against the limit for eviction/OOM decisions** (§3.14). Roughly:
  `working_set = memory.usage − inactive_file` (reclaimable clean file cache is
  excluded). So it ≈ **non-reclaimable memory**: anonymous + active/unevictable.
- **Production issue.** `kubectl top pod` shows working set, not RSS — people
  compare it to `top`'s RSS *inside* the pod and panic at the mismatch. They
  measure different things.

## 3.9 Page cache

- **What it is.** The kernel's cache of **file** contents in RAM: every file you
  `read()`, `write()`, or `mmap` leaves pages here so future access is fast.
- **Why it exists.** Disk is slow; caching file data in otherwise-free RAM is
  free performance. "Free RAM is wasted RAM."
- **Where it lives.** Kernel-managed, *outside* any single process's private
  memory, but a process's *mmap'd file* pages are page cache that also count in
  its RSS.
- **When it grows/shrinks.** Grows as files are accessed; shrinks under memory
  pressure (clean pages dropped instantly — they're safe on disk).
- **Common misconception (the classic).** "`free` says only 200 MB free, the
  server is out of memory!" No — most of "used" is **page cache** that is
  instantly reclaimable. Look at the **`available`** column, not `free`
  (§3.12).
- **Container gotcha.** Inside a cgroup, page cache generated by *your*
  container's file I/O **counts toward the cgroup's `memory.usage`** — but the
  *reclaimable* part is excluded from the working set, so it usually won't OOM
  you by itself. Heavy log/temp-file writing that stays "active," though, can.

## 3.10 Dirty pages

- **What it is.** Pages that have been **modified in RAM but not yet written
  back** to their backing file (page cache waiting to be flushed).
- **Why it matters.** They can't just be dropped — they must be written to disk
  first, which takes time and can stall reclaim. `Dirty:` in
  `/proc/meminfo`; per-mapping `Private_Dirty`/`Shared_Dirty` in `smaps`.
- **When it shrinks.** The kernel's writeback flushes them (tunable via
  `vm.dirty_ratio`, `dirty_background_ratio`).
- **Production issue.** A burst of dirty pages (writing a huge file) can cause
  latency spikes and, in a cgroup with tight limits, throttling. Anonymous dirty
  pages have nowhere to go but swap — and with no swap, they pin RAM.

## 3.11 Anonymous vs. cached (in `/proc/meminfo`)

Two headline system-wide numbers:

- **`AnonPages`** — total anonymous memory across the system (heaps, stacks,
  objects). This is the "real program data" and the primary OOM driver.
- **`Cached`** — page cache (file data). Reclaimable.

```bash
grep -E '^(MemTotal|MemFree|MemAvailable|Buffers|Cached|AnonPages|Slab|SwapFree):' /proc/meminfo
```

Rule of thumb: **AnonPages is the scary number; Cached is the friendly one.**

## 3.12 free, available, committed — the `free` command decoded

`free -h` output and what each column *really* means:

```
              total        used        free      shared  buff/cache   available
Mem:           31Gi        9Gi         1Gi        400Mi       21Gi        21Gi
Swap:          2Gi         0B          2Gi
```

- **total** — installed RAM.
- **used** — total − free − buff/cache (roughly anonymous + kernel + unreclaimable).
- **free** — genuinely unused, sitting idle. **A low number here is normal and
  healthy** — Linux uses spare RAM for cache.
- **buff/cache** — **buffers + page cache**; reclaimable on demand.
- **available** — the kernel's estimate of memory available for a new workload
  **without swapping**: `free + reclaimable cache`. **This is the number that
  answers "am I about to run out of RAM?"** Not `free`.
- **shared** — tmpfs / `/dev/shm` usage (Chapter 9).

### Committed memory & overcommit

- **`Committed_AS`** (`/proc/meminfo`) — total memory *promised* to all
  processes (everything malloc'd, whether touched or not).
- **`CommitLimit`** — how much the kernel is willing to promise, governed by
  `vm.overcommit_memory` and `vm.overcommit_ratio`.
- **Overcommit** (default `mode 0`, heuristic) lets `Committed_AS` exceed RAM
  because most promises are never fully used (Chapter 6). When reality catches
  up with the promises, the **OOM killer** fires (Chapter 6).

## 3.13 Kernel memory, Slab, Buffers

These are memory used by the **kernel itself**, not attributable to your
process's user-space RSS — but they *do* consume physical RAM and, in a cgroup,
some kernel memory is charged to you.

- **Slab** — the kernel's allocator for its own objects: `dentry` (directory
  entries), `inode` caches, network buffers, `task_struct`s. Two parts:
  `SReclaimable` (caches it can drop under pressure) and `SUnreclaim` (pinned).
  Inspect with `slabtop` (Chapter 12) and `Slab:`/`SReclaimable:` in meminfo.
- **Buffers** — page cache specifically for block-device/filesystem metadata
  (superblocks, etc.). Small; reclaimable. Historically distinct from `Cached`.
- **Kernel memory in cgroups.** cgroup v2 accounts kernel memory (including
  slab and socket buffers) to the container by default. A container that opens
  millions of files/sockets can OOM on **kernel** memory even with modest
  user-space RSS — a genuinely nasty, under-diagnosed production issue.

```bash
sudo slabtop -o | head        # top kernel slab consumers
grep -E '^(Slab|SReclaimable|SUnreclaim|KernelStack|Buffers):' /proc/meminfo
```

## 3.14 Which metrics Kubernetes actually uses (the money section)

This is what separates people who *think* they understand memory from people
who can stop the 3 a.m. OOM pages. Precisely:

```
   +-------------------------------------------------------------+
   |  cgroup accounts your container's memory (v2 file):         |
   |     memory.current      = total charged (anon + page cache  |
   |                           + some kernel/socket memory)      |
   |     memory.max          = the hard limit (your `limits`)    |
   |     memory.stat         = breakdown: anon, file, kernel,... |
   +-------------------------------------------------------------+
                    |
                    v
   working_set_bytes  ≈  memory.current − inactive_file
   (reclaimable clean file cache excluded)
                    |
        +-----------+------------------------------+
        |                                          |
        v                                          v
   kubectl top pod                       OOM decision:
   shows WORKING SET                     if a cgroup charge would exceed
   (NOT RSS, NOT VSZ)                    memory.max and memory cannot be
                                         reclaimed -> the cgroup OOM killer
                                         kills a process in the container
                                         -> pod status: OOMKilled (137)
```

Key facts to burn in:

1. **The limit (`resources.limits.memory`) sets the cgroup `memory.max`.**
   Exceed it with non-reclaimable memory → **OOMKilled**, exit code **137**
   (128 + SIGKILL 9).
2. **`kubectl top pod` = working set ≈ non-reclaimable (anon + active).** It is
   **not** RSS and **not** VSZ. Comparing it to `top` inside the pod will
   mislead you.
3. **Page cache from your file I/O counts in `memory.current`** — but the
   reclaimable part is *excluded* from working set, so it usually won't OOM you
   alone. Anonymous memory is what kills you.
4. **`/dev/shm`, tmpfs, and shared-memory** count as container memory (Ch 9).
5. **Requests vs. limits** (`requests.memory`) affect *scheduling and eviction
   priority*, not the hard OOM threshold — Chapter 8.

We build the full debugging workflow on this in Chapters 8, 13, and 18. For
the exact cgroup file paths to read *inside* a running pod, see
[`../05_production_playbook/04_kubernetes_debugging.md`](../05_production_playbook/04_kubernetes_debugging.md).

## 3.15 Metric cheat table

| Metric | Includes shared? | Includes page cache? | Sums correctly across procs? | Alert on it? | Where |
|---|---|---|---|---|---|
| **VSZ** | Yes (reserved) | N/A (virtual) | No | ❌ never | `status:VmSize`, `ps VSZ` |
| **RSS** | Yes, **full** | mmap'd file part | ❌ double-counts | ⚠️ per-container yes | `status:VmRSS`, `top RES` |
| **PSS** | Yes, **apportioned** | apportioned | ✅ yes | ✅ for fleets | `smaps_rollup:Pss`, `smem` |
| **USS** | No (private only) | private only | ✅ yes | ✅ for leaks | `smem USS` |
| **Working set** | active only | excludes reclaimable | ✅ (per cgroup) | ✅ **k8s uses this** | `kubectl top`, cgroup |
| **Swap** | anon only | No | ✅ | ⚠️ thrashing | `status:VmSwap`, `vmstat` |
| **available** | — | + reclaimable | system-wide | ✅ node health | `free`, `/proc/meminfo` |

## 3.16 Worked example: reading one process end to end

```bash
PID=$(pgrep -f my_app | head -1)

# Virtual vs resident vs swap for the process:
grep -E '^(VmSize|VmRSS|VmData|VmStk|VmSwap):' /proc/$PID/status

# The honest breakdown (RSS/PSS/USS-ish):
grep -E '^(Rss|Pss|Shared_Clean|Shared_Dirty|Private_Clean|Private_Dirty|Anonymous|Swap):' \
     /proc/$PID/smaps_rollup

# Interpretation:
#   Private_Clean + Private_Dirty        ~= USS  (dies-with-process)
#   Pss                                   = fair share incl. shared
#   Rss = Private* + Shared*              = the over-counting number
#   Anonymous large & growing            -> your data / a leak (Ch 11)
#   Shared_Clean large                   -> shared libs (cheap; ignore)
```

If `Anonymous` climbs run over run while `Shared_Clean` stays flat, you have a
real anonymous-memory growth problem — proceed to Chapters 4, 11, and 12.

---

## Key takeaways

- **RSS ≥ PSS ≥ USS.** RSS over-counts shared pages; **PSS sums correctly**
  across processes; **USS** is what dies with the process (best leak signal).
- **VSZ is a promise, not a cost — never alert on it.**
- **Kubernetes uses *working set* (≈ non-reclaimable = anon + active), not
  RSS/VSZ**, for `kubectl top` and OOM/eviction decisions. Exceed `memory.max`
  with non-reclaimable memory → **OOMKilled (137)**.
- On the node, read **`available`**, not `free`; page cache is friendly and
  reclaimable, **AnonPages** is the scary number.
- **Page cache, tmpfs/`/dev/shm`, and kernel/slab memory** all count against a
  cgroup even though they're not in your user-space "objects."

## Practice exercises

1. For a running process, print `VmRSS`, `Pss`, and `Private_Clean +
   Private_Dirty` (≈USS) and confirm `RSS ≥ PSS ≥ USS`.
2. Start 4 copies of `python3 -c "input()"`. Sum their `VmRSS`, then sum their
   `Pss` (from `smaps_rollup`). Explain the gap.
3. Run `free -h`. Which is bigger, `free` or `available`? Write one sentence on
   why alerting on `free` would page you needlessly.
4. Read `/proc/meminfo` and identify `AnonPages`, `Cached`, `Slab`,
   `Committed_AS`. Which would grow if you started a big Pandas job? A big file
   copy?

## Quiz questions

1. Five workers each show 300 MB RSS. What's the *minimum* and *maximum* real
   RAM they could be using together, and why?
2. Your pod's `kubectl top` shows 1.8 Gi but `top` inside shows 2.4 Gi RES.
   Which is bigger and why can they legitimately differ?
3. A container writes 5 GB of logs to a file. Does that risk OOMKill? Under what
   condition could it?
4. Exit code 137 — what happened, and which cgroup number was exceeded by which
   *kind* of memory?
5. Why is USS the best metric for spotting *which* worker is leaking?
6. Is a process with 20 GB VSZ and 200 MB RSS a problem? What would make it one?

## Suggested experiments

- Write a script that allocates a 1 GiB `bytearray`, then `input()`. Compare
  `VmRSS`, `Pss`, and working set (if in a container:
  `cat /sys/fs/cgroup/memory.current`). Note that this private anon memory makes
  RSS ≈ PSS ≈ USS ≈ working set — no sharing to apportion.
- `cat` a large file (`cat bigfile > /dev/null`), then run `free -h` before and
  after. Watch `buff/cache` jump and `available` stay roughly flat — page cache
  in action.
- Inside a memory-limited Docker container
  (`docker run -m 256m ...`), read `/sys/fs/cgroup/memory.current` and
  `memory.max`, then allocate until OOMKilled. Confirm the exit code is 137.
  (We do this as a full lab in Chapter 20.)

---

*Next up: **Chapter 4 — Python Memory**, where we open up CPython: `PyObject`,
reference counting, the generational GC, `pymalloc` arenas/pools/blocks,
fragmentation, and the definitive answer to "why doesn't `del` / `gc.collect()`
lower my RSS?"*

[← Chapter 2](02_linux_process_memory.md) · [Back to index](README.md) · [Chapter 4 →](04_python_memory.md)
