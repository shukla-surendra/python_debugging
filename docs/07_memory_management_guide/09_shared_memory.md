<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 9 — Shared Memory

Shared memory is where the most *confusing* production OOMs live, because it
breaks the neat mental model "memory belongs to one process." A block of shared
memory is written by process A, read by process B, backed by RAM, counted
against your cgroup — but owned by *no single process's heap*, so it's invisible
to `tracemalloc`, easy to leak, and it kills PyTorch DataLoaders with a cryptic
`Bus error` and Chromium with `Target crashed`.

This chapter makes shared memory concrete: what it is, the tmpfs/`/dev/shm`
plumbing, the POSIX/SysV APIs, Python's `multiprocessing.shared_memory`, and
exactly how to size it in Docker and Kubernetes.

> Prerequisites: Ch 3 (shmem in metrics, working set), Ch 6 (COW `fork`), Ch 7
> (`/dev/shm`, tmpfs = RAM, `--shm-size`), Ch 8 (`emptyDir{medium: Memory}`).

## 9.1 What shared memory is (and why it exists)

**What it is.** A region of physical RAM mapped into the address space of
**two or more processes at once**, so they can read/write the *same bytes*
without copying data between them.

```
   Process A (virtual)        Physical RAM             Process B (virtual)
   0x7f..A000 --------\      +----------------+       /-------- 0x7f..B000
                       \---> | shared segment | <----/
                            | (one set of     |
   writes here ----------->  |  frames)        | <-------- reads here
                            +----------------+
   Both map the SAME frames. A write by A is instantly visible to B.
```

- **Why it exists.** It's the **fastest form of IPC**. Pipes, sockets, and
  queues copy data through the kernel (user→kernel→user). Shared memory copies
  **nothing** — a 2 GB tensor is "sent" to another process by sharing the frames,
  not moving bytes. For high-throughput data passing (ML batches, video frames,
  large arrays) it's the only performant option.
- **The trade-off.** No isolation and no automatic ownership. Because it belongs
  to multiple processes (or to a *filesystem*, not a process), the normal
  refcount/`free` lifecycle doesn't apply — you must **explicitly create and
  unlink** it, which is why it leaks so easily (§9.7).

## 9.2 tmpfs and `/dev/shm` — the plumbing

Almost all modern shared memory on Linux is implemented on top of **tmpfs**, a
RAM-backed filesystem.

- **tmpfs** — a filesystem whose "disk" is actually RAM (+ swap if available).
  Files written to a tmpfs live in **page cache that never has a backing disk
  file**; they occupy RAM until deleted. `/dev/shm`, `/run`, and (often) `/tmp`
  are tmpfs mounts.
- **`/dev/shm`** — the conventional tmpfs mount point that the POSIX shared-memory
  API (`shm_open`) and most libraries use. A file created here *is* a shared
  memory segment: any process that opens and `mmap`s it shares those frames.

```
   /dev/shm  ==  a tmpfs  ==  RAM
   +-----------------------------------------------+
   | /dev/shm/psm_torch_abc123   (a DataLoader tensor)  200 MiB
   | /dev/shm/pym-9f2c...         (multiprocessing.shm)  512 MiB
   | /dev/shm/.org.chromium.XXXX  (a Chromium buffer)     40 MiB
   +-----------------------------------------------+
   Everything here is anonymous-like RAM, charged to your cgroup (Ch 7-8).
```

- **Where it lives / accounting.** It's RAM, so it appears as **`shmem`** in
  cgroup `memory.stat` and counts toward `memory.current`/`memory.max`. In
  system `free`, it's the **`shared`** column. It is **not** part of any
  process's private RSS — a giant `/dev/shm` file with **no process attached**
  still consumes RAM.
- **Inspect it.**

```bash
df -h /dev/shm                              # size + used
ls -la /dev/shm                             # the segments (files)
du -sh /dev/shm                             # total held
grep shmem /sys/fs/cgroup/memory.stat       # shmem charged to this container
```

## 9.3 When shared memory grows and shrinks

Applying the book's standard lens:

- **When it grows.** Every time a process **creates a segment** (`shm_open` +
  `ftruncate`, a `SharedMemory(create=True)`, a DataLoader worker publishing a
  batch, Chromium allocating a render buffer). Growth is **not** tied to any
  object's refcount — it's a filesystem entry.
- **When it shrinks.** Only when a segment is **explicitly unlinked**
  (`shm_unlink`, `SharedMemory.unlink()`, the file deleted from `/dev/shm`) **and
  no process still has it mapped**. Closing/unmapping alone does **not** free it
  if the name still exists.
- **Returns to OS?** Yes — once unlinked and unmapped, the frames are freed and
  RAM (and cgroup `shmem`) drops. But a crashed process that created a segment
  and died **without unlinking** leaves the RAM held **forever** (until reboot or
  manual `rm /dev/shm/...`). This is the shared-memory leak.
- **Counts toward pod memory?** **Yes, fully** — this is the crux. Unlike page
  cache (reclaimable), tmpfs pages are **not reclaimable** (there's no disk to
  flush them to unless swap exists), so they behave like anonymous memory for OOM
  purposes and **can OOMKill you** (Ch 8).

## 9.4 The IPC landscape — where shared memory sits

```
   IPC mechanisms, slowest/safest -> fastest/sharpest:

   Sockets / pipes / queues   copy data user->kernel->user   (safe, slow-ish)
   Memory-mapped file (mmap)  share a file's pages            (Ch 2/5)
   POSIX shared memory        shm_open on /dev/shm  <-------- modern default
   SysV shared memory         shmget/shmat (older, IPC ns)    (legacy)
   -> all "shared memory" variants: ZERO-copy, but manual lifecycle
```

- **POSIX shm** (`shm_open`, `shm_unlink`) — file-like, lives in `/dev/shm`,
  isolated by the **mount namespace** (each container's `/dev/shm` is its own).
  What Python's `multiprocessing.shared_memory` and PyTorch use.
- **SysV shm** (`shmget`, `shmat`, `shmctl`) — older, keyed by integer, isolated
  by the **IPC namespace**; limits in `/proc/sys/kernel/shmmax`, `shmall`. Still
  seen in legacy C code and some databases. Inspect with `ipcs -m`.
- **Anonymous shared mmap** (`mmap(..., MAP_SHARED | MAP_ANONYMOUS)`) — shared
  only with **child** processes via `fork`; no name, freed when all unmap. This
  is what `multiprocessing`'s `Value`/`Array` and shared `fork` state use.

## 9.5 Python `multiprocessing.shared_memory`

Since Python 3.8, the standard way to share raw bytes across processes:

```python
from multiprocessing import shared_memory
import numpy as np

# Producer: create a named segment and expose a NumPy view over it
shm = shared_memory.SharedMemory(create=True, size=10_000_000)   # 10 MB in /dev/shm
arr = np.ndarray((2500,), dtype=np.float64, buffer=shm.buf)      # zero-copy view
arr[:] = np.arange(2500)
print(shm.name)   # e.g. 'psm_ab12cd34' -> a file in /dev/shm

# Consumer (another process): attach by name, no copy
existing = shared_memory.SharedMemory(name='psm_ab12cd34')
view = np.ndarray((2500,), dtype=np.float64, buffer=existing.buf)

# --- LIFECYCLE (this is where leaks happen) ---
existing.close()   # unmap in THIS process (does NOT free the RAM)
shm.close()        # unmap in the producer
shm.unlink()       # DELETE the segment -> NOW the RAM is freed (call ONCE, by owner)
```

- **`close()` vs `unlink()` (memorize).** `close()` detaches *this* process;
  `unlink()` destroys the segment. **You must call `unlink()` exactly once**
  (usually by the creator) or the RAM leaks. Forgetting it is the #1 cause of
  `/dev/shm` filling up in Python services.
- **The resource tracker.** Python spawns a `resource_tracker` process to clean
  up leaked segments at interpreter exit and warns:
  `resource_tracker: There appear to be N leaked shared_memory objects`. That
  warning means **you leaked** — fix the lifecycle, don't silence it.
- **`SharedMemoryManager`** (a context manager) auto-unlinks — prefer it:

```python
from multiprocessing.managers import SharedMemoryManager
with SharedMemoryManager() as smm:
    shm = smm.SharedMemory(size=10_000_000)
    # ... use it across processes ...
# auto-unlinked here -> no leak
```

- **`multiprocessing.Pool`/`Process` with `fork`** also uses shared memory
  implicitly and inherits COW pages (Ch 6.8); large read-only data is best put in
  a shared buffer to avoid per-worker copies.

## 9.6 Why Chromium, Selenium, PyTorch, and OpenCV need `/dev/shm`

The libraries that most often crash on the **64 MiB default `/dev/shm`**
(Ch 7.8):

- **PyTorch DataLoader (`num_workers > 0`).** Worker processes load/collate
  batches and pass the resulting **tensors to the main process via shared
  memory** (POSIX shm in `/dev/shm`). Big batches × several workers × prefetch
  easily exceed 64 MiB → `RuntimeError: DataLoader worker (pid X) is killed by
  signal: Bus error` or `unable to open shared memory object`. **Fix:** raise
  `/dev/shm` (Docker `--shm-size=1g`, k8s memory `emptyDir` at `/dev/shm`), or
  reduce `num_workers`/`batch_size`, or set
  `torch.multiprocessing.set_sharing_strategy('file_system')` (trades speed for
  fewer shm handles).
- **Chromium / headless Chrome / Selenium / Playwright.** Chromium uses
  `/dev/shm` heavily for its multi-process renderer. On the 64 MiB default it
  crashes tabs (`Target crashed`, `SessionNotCreated`). **Fix:** enlarge
  `/dev/shm`, or run Chrome with `--disable-dev-shm-usage` (makes it use `/tmp`
  disk instead — slower but avoids the RAM limit).
- **OpenCV / multiprocessing image pipelines.** Passing large frames/arrays
  between worker processes uses shared memory; same exhaustion pattern.

```
   Symptom cheat-sheet:
   "Bus error" / "DataLoader worker killed by signal"   -> /dev/shm too small (PyTorch)
   "Target/renderer crashed", "session not created"     -> /dev/shm too small (Chromium)
   "No space left on device" writing to /dev/shm        -> /dev/shm full
   "resource_tracker: N leaked shared_memory objects"   -> missing unlink() (Python)
```

## 9.7 The shared-memory leak (and how to find it)

The nastiest kind: **RAM held by segments in `/dev/shm` with no live process
accounting for them.**

```
   Signature:
     - cgroup memory.stat: shmem is large and growing
     - tracemalloc / per-process RSS: look small/flat  (it's not in any heap!)
     - df -h /dev/shm: filling up; ls /dev/shm: many stale segments
     - crashed/killed workers that created segments but never unlinked
```

Find and clean it:

```bash
ls -la /dev/shm                      # stale segments? (old psm_/pym-/chromium files)
du -sh /dev/shm                      # total leaked RAM
grep shmem /sys/fs/cgroup/memory.stat
ipcs -m                              # SysV segments (nattch=0 == leaked, no attachers)
# Careful cleanup (only if you know the owners are dead):
ipcrm -m <shmid>                     # remove a SysV segment
rm /dev/shm/psm_stale_name           # remove a leaked POSIX segment
```

- **Prevention:** always `unlink()` in a `finally`/context manager; use
  `SharedMemoryManager`; ensure worker crash paths clean up; monitor
  `du -sh /dev/shm` and cgroup `shmem` as first-class metrics.

## 9.8 Sizing `/dev/shm` in Docker and Kubernetes (reference)

**Docker** (Ch 7):

```bash
docker run --shm-size=1g myimg           # /dev/shm = 1 GiB
docker run --ipc=host myimg              # share host IPC ns (host /dev/shm) - use with care
```

```yaml
# docker-compose
services:
  app:
    shm_size: "1gb"
```

**Kubernetes** (Ch 8 — no `shm-size` field; mount a memory `emptyDir`):

```yaml
spec:
  containers:
    - name: trainer
      volumeMounts:
        - { name: dshm, mountPath: /dev/shm }
      resources:
        limits: { memory: 8Gi }     # dshm usage counts INSIDE this 8Gi
  volumes:
    - name: dshm
      emptyDir:
        medium: Memory
        sizeLimit: 2Gi              # bound it; leave 6Gi for the app
```

- **Golden rule:** `/dev/shm` size + app working set must fit under
  `limits.memory`. Sizing `/dev/shm` to 2Gi inside an 8Gi limit leaves ~6Gi for
  everything else. Oversizing `/dev/shm` doesn't pre-allocate RAM (tmpfs is
  demand-paged), but it **removes the guard rail** — an unbounded producer can
  then eat the whole limit.

## 9.9 Decision guide: should you use shared memory?

```
   Do you need to move large data between processes on the SAME node?
        |
        +-- No  -> use a queue/socket/pipe (simpler, safe, no lifecycle). Done.
        |
        +-- Yes, and it's big (arrays/tensors/frames)?
              |
              +-- Use shared memory, BUT:
                    - own the lifecycle (create/unlink in one place; context mgr)
                    - size /dev/shm to fit under the cgroup limit (Ch 7-8)
                    - monitor du /dev/shm + memory.stat shmem
                    - on crash paths, clean up segments
              |
              +-- Cross-node? -> shared memory can't; use object storage / a
                    broker / RDMA. (Ch 14 streaming case study.)
```

---

## Key takeaways

- **Shared memory = the same RAM frames mapped into multiple processes**: the
  fastest, zero-copy IPC — but with **manual lifecycle** and **no owner**, so it
  leaks easily.
- **It's almost always tmpfs/`/dev/shm` = RAM**, shows as `shmem` in
  `memory.stat` / `shared` in `free`, is **non-reclaimable**, and **counts fully
  toward your cgroup limit** — it can OOMKill you with a tiny process heap.
- **`close()` detaches; `unlink()` frees.** Forgetting `unlink()` (or crashing
  before it) leaks RAM until reboot. Use `SharedMemoryManager`/context managers;
  heed the `resource_tracker` "leaked objects" warning.
- **The 64 MiB default `/dev/shm` breaks PyTorch DataLoaders (`Bus error`) and
  Chromium (`Target crashed`)** — raise it (`--shm-size`, memory `emptyDir`) or
  reduce workers/batch, and always size it **inside** the memory limit.
- **Diagnose shm leaks with `du -sh /dev/shm`, `ls /dev/shm`, `ipcs -m`, and
  `shmem` in `memory.stat`** — not with `tracemalloc`, which can't see it.

## Practice exercises

1. Create a `SharedMemory(create=True, size=100_000_000)`; check `df -h /dev/shm`
   and `grep shmem /sys/fs/cgroup/memory.stat` before and after. Then `unlink()`
   and confirm the RAM returns.
2. Deliberately forget `unlink()` and exit; observe the `resource_tracker`
   leak warning and the stale file in `/dev/shm`.
3. Run a PyTorch (or simulated) DataLoader with `num_workers=4` in a container
   with the default 64 MiB `/dev/shm` and reproduce the `Bus error`; fix it by
   enlarging `/dev/shm`.
4. Compare passing a 200 MB array between processes via a `Queue` vs. via
   `SharedMemory`; measure time and peak RSS.

## Quiz questions

1. Why is shared memory the fastest IPC, and what safety/lifecycle price do you
   pay for that speed?
2. A `/dev/shm` file exists but no process has it open. Does it still use RAM?
   Does it count toward the cgroup?
3. Difference between `SharedMemory.close()` and `.unlink()`? Which frees RAM?
4. Your pod's `memory.stat` shows large `shmem`, RSS is small, and `tracemalloc`
   is flat. What's leaking and how do you find it?
5. Why does a PyTorch DataLoader throw `Bus error` on the default `/dev/shm`, and
   give two different fixes?
6. Is tmpfs/`/dev/shm` memory reclaimable under pressure like page cache? What
   does that imply for OOM?
7. In Kubernetes there's no `--shm-size`; how do you enlarge `/dev/shm`, and what
   must you watch relative to `limits.memory`?

## Suggested experiments

- Write a producer/consumer pair with `multiprocessing.shared_memory` + NumPy
  views; verify zero-copy by mutating in the consumer and reading in the
  producer. Then convert it to `SharedMemoryManager` and confirm no leak warning.
- Fill `/dev/shm` toward its size limit in a container and watch which fails
  first: `No space left on device` (hit tmpfs `sizeLimit`) vs. OOMKilled (hit
  `memory.max`) — depends on how you sized them (§9.8 golden rule).
- Leave stale segments, then practice cleanup with `ls /dev/shm`, `ipcs -m`,
  `ipcrm`, and `rm /dev/shm/...`; re-check `du -sh /dev/shm` and cgroup `shmem`.

---

*Next up: **Chapter 10 — Memory Growth: The Master Table**, which consolidates
Chapters 1–9 into a single reference: for Python heap, native heap, RSS/PSS/USS,
page cache, thread stacks, shared libs, mmaps, tmpfs, the container writable
layer, PVs, and anonymous memory — does each grow, shrink, return to the OS, and
count toward pod memory?*

[← Chapter 8](08_kubernetes_memory.md) · [Back to index](README.md) · [Chapter 10 →](10_memory_growth.md)
