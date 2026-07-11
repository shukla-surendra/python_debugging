<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 10 — Memory Growth: The Master Table

Chapters 1–9 built the model piece by piece. This chapter is the **payoff**: one
consolidated reference that answers, for **every kind of memory in a Python
container**, the four questions that actually decide production behavior:

1. **Does it grow?** (and what makes it grow)
2. **Does it shrink?** (and what makes it shrink)
3. **Does it return to the OS?** (RSS actually drops)
4. **Does it count toward pod memory?** (can it OOMKill you)

Print this chapter. Pin it. When a pod's memory climbs, you'll walk this table
row by row to localize the cause in minutes instead of hours.

> Prerequisites: all of Ch 1–9. This chapter references them constantly rather
> than re-deriving. Chapters 11–13 turn this table into diagnosis workflows.

## 10.1 The master table

For each memory type: **Grows?** what drives growth · **Shrinks?** what releases
it · **Returns to OS?** does RSS drop · **Counts toward pod (cgroup) memory?**
can it OOMKill you.

| # | Memory type | Grows when | Shrinks when | Returns to OS? | Counts toward pod memory? |
|---|---|---|---|---|---|
| 1 | **Python heap** (pymalloc arenas) | you allocate objects <512B (Ch 4) | refs drop to 0 (refcount/GC) → blocks freed | **Rarely** — only when a whole 256KiB arena empties (Ch 4.9) | **Yes** (anonymous) |
| 2 | **Native heap** (malloc/mmap: NumPy, Torch, cv2, pandas) (Ch 5) | native buffers allocated | buffer freed | **Big mmap-backed: yes** (`munmap`); **small on glibc heap: no** (hoarded) | **Yes** (anonymous) |
| 3 | **RSS** (resident set) (Ch 3) | pages touched (demand paging, Ch 6) | pages freed **and** returned, or reclaimed | it *is* the thing that drops when others return | **~Yes** — but pod uses **working set**, not raw RSS |
| 4 | **PSS** (proportional) (Ch 3) | private grows, or sharers leave | private freed, or more sharers | tracks real RAM; sums correctly | **Yes** (best fleet estimate; not the OOM metric) |
| 5 | **USS** (unique/private) (Ch 3) | private anon grows | private freed | **Yes** when private pages return | **Yes** — this is the "dies-with-process" part |
| 6 | **Page cache** (file reads/writes) (Ch 3/7) | you read/write files (incl. overlay fs) | reclaimed under pressure (clean dropped free) | **Yes, freely** (clean pages) | **Counts in `memory.current`, but reclaimable part is excluded from working set** → usually won't OOM alone |
| 7 | **Thread stacks** (Ch 2/6) | each thread created (8MiB *virtual* reserve) | thread exits | mapping freed on exit; touched pages modest | **Yes** (touched pages, anon) — VSZ balloons, RSS modest |
| 8 | **Shared libraries** (.so, interpreter) (Ch 2) | libraries loaded/imported (`import numpy`) | never (fixed) | clean pages **dropped for free** under pressure | **Barely** — shared page cache across containers; counts once, apportioned |
| 9 | **Memory maps** (mmap'd files) (Ch 2/5) | you touch mapped pages | reclaimed (clean) / munmap | clean → **yes**; dirty → written back then freed | **Yes while resident** (reclaimable if clean) |
| 10 | **tmpfs / `/dev/shm`** (Ch 7/9) | files written to tmpfs / shm segments created | files deleted / `unlink()`ed | **Yes** on delete/unlink | **YES, fully** — **non-reclaimable**, OOM-capable |
| 11 | **Container writable layer** (overlay) (Ch 7) | files written into the container fs | files deleted | it's **disk**, not RAM | **No** (ephemeral storage) — *except* its page cache (row 6) |
| 12 | **Persistent Volume** (PVC/CSI) (Ch 8) | files written to the mounted volume | files deleted (external storage) | **disk**, not RAM | **No** — *except* page cache from its I/O (row 6) |
| 13 | **Anonymous memory** (the umbrella: heaps, stacks, shm) (Ch 1) | any touched private/shared-anon page | freed + returned, or swapped | depends on allocator (rows 1, 2) | **YES — the primary OOM driver** |

## 10.2 How to read the table (three big patterns)

**Pattern A — "grows but won't return to OS" (rows 1, 2-small).**
Python heap and small glibc allocations **free to the allocator, not the OS**.
This is *retention/fragmentation*, not a leak (Ch 4.9, 11). RSS plateaus high.
Fix: worker recycling, jemalloc/`MALLOC_ARENA_MAX`, move big work to subprocesses
(Ch 15).

**Pattern B — "counts toward the pod but invisible to Python tools" (rows 2,
10).** Native buffers and tmpfs/`/dev/shm` are charged to your cgroup but
`tracemalloc`/`getsizeof` can't see them. RSS/`memory.stat`/memray reveal them
(Ch 5, 9). This is the "phantom OOM."

**Pattern C — "counts but reclaimable / doesn't count at all" (rows 6, 8, 11,
12).** Page cache, shared libs, the writable layer, and PVs are either
reclaimable or disk. They inflate `memory.current` or RSS but rarely OOM you by
themselves. Don't chase these when hunting a leak.

## 10.3 The "counts toward the pod limit?" quick filter

When a pod is climbing toward OOMKill, only these can actually kill you (they're
**non-reclaimable and charged**):

```
   WILL OOMKILL YOU (non-reclaimable, charged to cgroup):
     [x] Python heap (anon)                 -> Ch 4, 11
     [x] Native buffers (NumPy/Torch/...)   -> Ch 5   (the usual suspect in ML)
     [x] tmpfs / /dev/shm (shmem)           -> Ch 9   (the sneaky suspect)
     [x] Thread stacks (touched, anon)      -> Ch 2/6 (rare, thread leaks)
     [x] Kernel/slab (fds, sockets)         -> Ch 3   (rare, fd/socket leaks)

   WON'T OOMKILL YOU ALONE (reclaimable or disk):
     [ ] Page cache (clean file data)       -> reclaimed under pressure
     [ ] Shared library code                -> clean, dropped for free
     [ ] Container writable layer           -> disk (ephemeral, not memory)
     [ ] Persistent Volume                  -> disk (external)
```

**So the OOM investigation always narrows to four questions:** Is it (1) Python
objects, (2) native buffers, (3) shared memory, or (4) kernel/threads? The rest
is noise. Chapters 11–13 answer *which*.

## 10.4 Growth-source → which row lights up (reverse lookup)

Start from a symptom; find the row.

| Symptom / activity | Row(s) that grow | Chapter |
|---|---|---|
| `import numpy/torch/pandas` at startup | 8 (shared libs) + 2 (native) | 2, 5 |
| Building lots of Python objects (dicts, lists) | 1 (Python heap) | 4 |
| Unbounded cache / accumulating list | 1, 13 (anon) — a **leak** | 4, 11 |
| Loading a big model / big arrays | 2 (native mmap) | 5 |
| Hidden NumPy/pandas copies (astype, boolean index) | 2 (native) | 5 |
| DataLoader `num_workers>0`, passing tensors | 10 (`/dev/shm`) | 9 |
| Reading/writing large files | 6 (page cache) + 11 (writable layer) | 3, 7 |
| Spawning many threads | 7 (stacks, VSZ↑) | 2, 6 |
| Opening millions of fds/sockets | kernel/slab | 3 |
| Chromium/Selenium crash `Target crashed` | 10 (`/dev/shm`) | 9 |
| RSS high after `del`/`gc.collect()` | 1, 2-small (retention) | 4 |
| RSS never drops on many-core host | 2 (glibc arenas) | 5 |

## 10.5 The single decision tree (memory climbing in a pod)

```
   Pod memory climbing / OOMKilled?
        |
        v
   [1] Is working set (kubectl top / memory.current - inactive_file) the culprit,
       or is it page cache?  --> if mostly reclaimable file cache, likely fine.
        |
        v
   [2] Read memory.stat:  which counter dominates?
        |
        +-- anon large ........... Python heap OR native buffers
        |        |
        |        +-- tracemalloc shows growth? --> Python objects (leak/retention) Ch 4,11
        |        +-- tracemalloc flat?          --> NATIVE buffers -> memray       Ch 5
        |
        +-- shmem large .......... /dev/shm / tmpfs / shared_memory leak           Ch 9
        |
        +-- file large ........... page cache from heavy I/O (usually reclaimable) Ch 3,7
        |
        +-- slab/kernel_stack .... fd/socket/thread explosion                      Ch 3,6
        |
        v
   [3] Is it a LEAK (grows unbounded run-over-run) or RETENTION (plateaus)?
        |
        +-- unbounded ........ true leak -> find the retaining reference           Ch 11,12
        +-- plateaus high .... retention/fragmentation -> recycle workers / jemalloc Ch 4,15
        |
        v
   [4] Fix (Ch 15) and set alerts on working set + shmem + major faults (Ch 13,21)
```

## 10.6 Grows vs. returns: the two-axis mental map

Plot every memory type on two axes — *does it grow with your workload?* and
*does it give memory back to the OS?* — and the danger zones pop out:

```
                RETURNS TO OS EASILY
                        ^
      page cache (6)    |   large NumPy mmap (2)
      shared libs (8)   |   mmap'd files (9)
      mmap'd file (9)   |   tmpfs after unlink (10)
                        |
   <--- doesn't grow ---+--- grows with workload --->
      (mostly fixed)    |
                        |   >>> DANGER ZONE <<<
      thread stacks (7) |   Python heap (1)         <- retention, RSS won't drop
                        |   small glibc allocs (2)  <- fragmentation
                        |   /dev/shm leak (10)      <- non-reclaimable, invisible
                        v
                RARELY RETURNS TO OS
```

The **bottom-right quadrant** (grows with workload **and** rarely returns) is
where every hard memory incident lives: Python heap retention, glibc
fragmentation, and `/dev/shm` leaks. Everything you learned in Ch 4, 5, and 9
concentrates here.

## 10.7 Worked mini-scenarios (apply the table)

- **"RSS is 3 GB, `tracemalloc` says 200 MB, no leak in code."** Rows 2 + 10.
  Native buffers and/or `/dev/shm`. Check `memory.stat` `anon` vs `shmem`; profile
  with memray. (Ch 5, 9)
- **"Memory ramps to 1.8 GB then OOMKills at 2 GB every 40 min, sawtooth."**
  Row 1/13, unbounded growth = **leak** (Ch 11). Snapshot-diff with tracemalloc
  (Ch 12).
- **"RSS plateaus at 900 MB after a big job and never drops, but doesn't grow
  further."** Rows 1 + 2-small: **retention/fragmentation**, not a leak. Recycle
  the worker or use jemalloc. (Ch 4, 15)
- **"`free` shows almost no free RAM but the app is fine."** Row 6: page cache.
  Look at `available`, not `free`. (Ch 3)
- **"Pod evicted, not OOMKilled, app under its limit."** Node pressure, not your
  memory — rows don't apply to *you*; a neighbor caused it. (Ch 8)
- **"VSZ is 25 GB, RSS 400 MB."** Row 7 (thread stacks) + glibc arena
  reservations. Virtual, not real — don't alert on it. (Ch 2, 3)

---

## Key takeaways

- **Only anonymous-family memory (Python heap, native buffers, tmpfs/`/dev/shm`,
  thread stacks, kernel/slab) is non-reclaimable and can OOMKill you.** Page
  cache, shared libs, the writable layer, and PVs either reclaim or are disk.
- **"Grows but won't return to the OS"** = Python heap + small glibc allocations
  (retention/fragmentation, not a leak). **"Counts but invisible to Python
  tools"** = native buffers + `/dev/shm` (the phantom OOM).
- Every OOM investigation narrows to **four questions**: Python objects? native
  buffers? shared memory? kernel/threads? — decided by **`memory.stat` +
  tracemalloc-vs-memray**.
- **The danger quadrant** (grows with workload **and** rarely returns) holds all
  hard incidents: heap retention, glibc fragmentation, `/dev/shm` leaks.
- Distinguish **leak (unbounded) vs. retention (plateaus)** — they need different
  fixes (find the reference vs. recycle/allocator-swap).

## Practice exercises

1. Without looking, fill in the four columns (grows/shrinks/returns/counts) for:
   Python heap, large NumPy array, `/dev/shm`, page cache, writable layer. Check
   against §10.1.
2. For each of the six mini-scenarios in §10.7, name the row(s) and the chapter
   you'd open. Then invent two scenarios of your own.
3. Take a real service you run and classify its top-3 memory consumers into table
   rows. Which are reclaimable? Which could OOM it?

## Quiz questions

1. Which memory types count toward the pod limit **and** are non-reclaimable?
   Which count but are reclaimable? Which don't count at all?
2. A pod's `memory.current` is high but mostly `file` in `memory.stat`. Is it at
   OOM risk? Why or why not?
3. RSS won't drop after freeing a million small objects, but memory isn't growing
   further. Leak or retention? Which rows, which fix?
4. Native buffer growth vs. `/dev/shm` growth both show large `anon`/`shmem` and
   flat tracemalloc — how do you tell them apart?
5. Why is writing 5 GB to a PersistentVolume not a pod-memory problem, and when
   could it still affect memory?
6. Where on the two-axis map do the hard incidents live, and which three
   phenomena occupy that quadrant?

## Suggested experiments

- Instrument a script to print `memory.stat` (`anon`, `file`, `shmem`, `slab`)
  plus `tracemalloc` top stats each second while it (a) builds Python objects,
  (b) allocates NumPy arrays, (c) writes to `/dev/shm`, (d) reads a big file.
  Watch a *different* row light up each time — the table, live.
- Reproduce Pattern A (retention): allocate + free a million objects, confirm RSS
  plateaus and won't drop; then rerun under `LD_PRELOAD` jemalloc and compare.
- Build a tiny "row classifier": given a `memory.stat` dump and a tracemalloc
  snapshot, print which of the four OOM questions is implicated. You'll reuse this
  logic in the Chapter 13 workflow.

---

*Next up: **Chapter 11 — Memory Leaks vs. Retention vs. Fragmentation**, where we
sharpen the single most important distinction in this book — is it *actually* a
leak? — with ASCII growth-pattern graphs for true leaks, retention, allocator
caching, and cycles, and how to recognize each on a dashboard.*

[← Chapter 9](09_shared_memory.md) · [Back to index](README.md) · [Chapter 11 →](11_memory_leaks.md)
