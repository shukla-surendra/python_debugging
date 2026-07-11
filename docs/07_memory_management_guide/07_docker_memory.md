<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 7 — Docker Memory

Everything in Chapters 1–6 was true for a process on bare Linux. Now we put that
process **in a box**. A container is not a VM — it's just a normal Linux process
with two kernel features wrapped around it: **namespaces** (what it can *see*)
and **cgroups** (what it can *use*). Memory limits, `OOMKilled`, `/dev/shm`
exhaustion, and "why does my container think it has 64 GB of RAM?" all come from
these two mechanisms.

Get this chapter right and Kubernetes (Chapter 8) is just "cgroups with YAML."

> Prerequisites: Ch 3 (RSS/working set/page cache), Ch 6 (OOM killer, overcommit,
> `/dev/shm`-relevant faults). This chapter is the bridge to Ch 8–9.

## 7.1 A container is a process, not a machine

```
   +-----------------------------------------------------------+
   |                     The Linux Kernel (ONE kernel)         |
   |   +--------------------+       +--------------------+     |
   |   | Container A        |       | Container B        |     |
   |   | (python process)   |       | (nginx process)    |     |
   |   |  namespaces: own    |       |  namespaces: own   |     |
   |   |   PID/mnt/net view  |       |   PID/mnt/net view |     |
   |   |  cgroup: mem<=512M  |       |  cgroup: mem<=1G   |     |
   |   +--------------------+       +--------------------+     |
   |          both are just processes sharing this kernel      |
   +-----------------------------------------------------------+
```

- **No guest kernel**, no hypervisor. `ps aux` on the host shows the container's
  Python process directly. This is why containers are cheap — and why a
  container's memory is accounted by the **same** page/RSS/working-set machinery
  you already learned, just scoped by a cgroup.
- **Consequence:** all of Chapter 6 (demand paging, faults, OOM killer, THP)
  applies *unchanged* inside a container. The container merely adds a **limit**
  and a **view**.

## 7.2 Namespaces — what the container can *see*

**What they are.** Kernel features that give a process an isolated *view* of a
global resource. Each type virtualizes one thing:

| Namespace | Isolates | Memory relevance |
|---|---|---|
| **PID** | process IDs | container sees its Python as PID 1 |
| **mount (mnt)** | filesystem tree | its own `/`, `/dev/shm`, `/tmp` |
| **network (net)** | interfaces, ports | socket buffers (kernel mem) |
| **IPC** | SysV/POSIX shm, semaphores | **isolates shared memory** (Ch 9) |
| **UTS** | hostname | — |
| **user** | UID/GID mapping | rootless containers |
| **cgroup** | cgroup tree view | hides host cgroup paths |

- **Why it matters for memory.** Namespaces give *isolation of visibility*, but
  **not** resource limits — that's cgroups. The **IPC** and **mount** namespaces
  are what make each container's `/dev/shm` and shared memory private (Chapter 9).
- **The big gotcha they *don't* fix.** Namespaces do **not** virtualize
  `/proc/meminfo` or the CPU count. Inside a container, `free`, `/proc/meminfo`,
  and `os.cpu_count()` report the **host's** totals, not your limits (§7.7).

## 7.3 cgroups — what the container can *use*

**What they are.** **Control groups**: the kernel mechanism that *limits,
accounts, and isolates* resource usage (memory, CPU, I/O, PIDs) for a group of
processes. The `-m 512m` on `docker run` becomes a cgroup memory limit.

- **Why they exist.** Namespaces isolate *what you see*; cgroups isolate *how
  much you consume*. Together they make a container.
- **v1 vs v2 (know both).**

```
   cgroup v1 (older)                 cgroup v2 (current default on modern distros)
   /sys/fs/cgroup/memory/...         /sys/fs/cgroup/<path>/...
     memory.limit_in_bytes             memory.max        <- hard limit
     memory.usage_in_bytes             memory.current    <- current usage
     memory.stat                       memory.stat       <- breakdown
     memory.soft_limit_in_bytes        memory.high       <- soft throttle
                                       memory.min/low     <- reclaim protection
                                       memory.swap.max    <- swap limit
                                       memory.events      <- oom/high counters
```

- **v2 is unified** (one hierarchy for all controllers) and is what Kubernetes
  targets now. Chapter 8 & 18 read these files directly.
- **Where it lives.** A pseudo-filesystem at `/sys/fs/cgroup`. Reading these
  files *inside* a running container is the single most reliable way to know your
  real limit and usage (§7.6).

## 7.4 Container memory limits — `-m` / `--memory`

**What happens when you set `docker run -m 512m`:**

```
   docker run -m 512m --memory-swap 512m python app.py
        |
        v
   cgroup v2: memory.max = 536870912   (512 MiB, hard limit)
              memory.swap.max = 0       (no swap beyond RAM)
        |
   Your process's charged memory (anon + page cache + some kernel) climbs...
        |
   charge would exceed memory.max AND nothing reclaimable
        v
   cgroup OOM killer SIGKILLs a process in THIS container -> exit 137
```

- **What counts toward the limit** (from `memory.current` / `memory.stat`):
  **anonymous** memory (your objects/arrays — the main driver), **page cache**
  from files *your container* touches, **tmpfs / `/dev/shm`** usage, socket
  buffers, and (v2) **kernel** memory (slab, stacks). This is exactly Chapter
  3.14's list.
- **What does *not* count:** shared library pages are largely page cache shared
  across containers; the host's own usage; another container's memory.
- **`--memory-swap` subtlety.** `--memory-swap` is **memory + swap** total. If
  you set `-m 512m` without `--memory-swap`, Docker defaults it to `2×memory`,
  allowing 512 MiB swap — often surprising. Set `--memory-swap` equal to
  `--memory` to disable swap (matching typical k8s behavior).
- **`--memory-reservation`** is a *soft* limit (best-effort under host pressure),
  analogous to a request; `--oom-kill-disable` pauses instead of killing (rarely
  a good idea — it hangs).

```bash
docker run -m 512m --memory-swap 512m myimg          # hard 512 MiB, no swap
docker stats --no-stream                              # live MEM USAGE / LIMIT / %
docker inspect -f '{{.HostConfig.Memory}}' <ctr>      # limit in bytes
```

## 7.5 CPU limits (and why they matter for memory)

CPU limits belong here because a **CPU limit that libraries ignore causes memory
blowups**.

- **`--cpus=2`** sets cgroup CPU quota (`cpu.max`). But **`os.cpu_count()`,
  OpenMP, MKL, OpenBLAS, OpenCV, and NumPy still see the host's core count** and
  size their **thread pools** accordingly (Ch 5.6). On a 64-core host with
  `--cpus=2`, a native lib may spawn 64 threads — each with an **8 MiB stack
  reservation** and scratch buffers — inflating VSZ/RSS massively and thrashing.
- **Fix:** pin thread counts to your CPU limit:

```dockerfile
ENV OMP_NUM_THREADS=2
ENV OPENBLAS_NUM_THREADS=2
ENV MKL_NUM_THREADS=2
ENV NUMEXPR_NUM_THREADS=2
# and in code: cv2.setNumThreads(2); torch.set_num_threads(2)
```

- **CPU throttling ≠ memory**, but a throttled GC or reclaim thread can let
  memory back up. Mention `cpu.stat`'s `nr_throttled` when debugging latency.

## 7.6 Reading your *real* limits from inside the container

This is the most useful practical skill in the chapter. Because `free` lies
(§7.7), read the cgroup files:

```bash
# cgroup v2 (modern):
cat /sys/fs/cgroup/memory.max        # your hard limit (or "max" = unlimited)
cat /sys/fs/cgroup/memory.current    # what you're using right now
cat /sys/fs/cgroup/memory.stat       # anon, file, kernel, slab, ... breakdown
cat /sys/fs/cgroup/memory.events     # oom, oom_kill, high, max event counters

# cgroup v1 (older hosts):
cat /sys/fs/cgroup/memory/memory.limit_in_bytes
cat /sys/fs/cgroup/memory/memory.usage_in_bytes
cat /sys/fs/cgroup/memory/memory.stat
```

- **`memory.stat` keys you'll use:** `anon` (anonymous — the OOM driver),
  `file` (page cache), `kernel_stack`, `slab`, `sock`, `shmem` (tmpfs/`/dev/shm`),
  `inactive_file`/`active_file` (working-set math from Ch 3.14).
- **Compute working set yourself:** `working_set ≈ memory.current −
  inactive_file` — the number Kubernetes uses (Ch 3.14/8).
- **From Python**, prefer libraries that read cgroup, not `psutil.virtual_memory()`
  (which reports host RAM). Newer runtimes are "container-aware"; verify.

```python
def cgroup_limit_bytes():
    for p in ("/sys/fs/cgroup/memory.max",                       # v2
              "/sys/fs/cgroup/memory/memory.limit_in_bytes"):    # v1
        try:
            v = open(p).read().strip()
            return None if v in ("max", str(2**63 - 1)) else int(v)
        except FileNotFoundError:
            continue
```

## 7.7 The "my container thinks it has 64 GB" trap

**The single most common container-memory mistake.**

```
   Inside a container with -m 512m:
     free -h              -> shows the HOST's 64 GiB   (WRONG for your limit)
     /proc/meminfo        -> HOST totals                (not virtualized!)
     os.cpu_count()       -> HOST cores                 (not your --cpus)
     nproc                -> HOST cores
```

- **Why.** `/proc/meminfo` and the CPU topology are **not** namespaced; the
  kernel exposes host-global values. Only cgroup files reflect your limit.
- **Consequences.** JVMs/Python apps that size heaps, caches, worker counts, or
  thread pools from "available RAM/CPUs" will size for **64 GB / 64 cores** and
  get **OOMKilled at 512 MB**. This has caused countless incidents.
- **Fixes.** Read cgroup limits (§7.6); set explicit worker/thread/cache sizes
  from the *limit*, not from `free`/`cpu_count`; use container-aware runtimes
  (recent OpenJDK, Node, Python libs). Tools like `LimitRANGE`/downward API
  (Ch 8) can inject the limit as an env var.

## 7.8 `/dev/shm`, `--shm-size`, and tmpfs

**What `/dev/shm` is.** A **tmpfs** (RAM-backed filesystem) mounted at
`/dev/shm`, used for POSIX shared memory and inter-process data passing. Docker
gives each container a **default `/dev/shm` of just 64 MiB**.

```
   /dev/shm  ---- is a tmpfs ---->  lives in RAM (counts as container memory!)
   default size in Docker: 64 MiB
   grow with: docker run --shm-size=1g ...
```

- **Why it exists.** Fast IPC: processes share data without copying through
  pipes/sockets. **PyTorch DataLoader workers, OpenCV, Chromium/Selenium, and
  many multiprocessing patterns write here.**
- **When it grows/shrinks.** Grows as processes write files/segments into it;
  shrinks when they're deleted. It is **RAM**, so its usage **counts toward the
  cgroup limit** and can OOM you.
- **The classic failure:** `Bus error (core dumped)` or
  `RuntimeError: DataLoader worker ... killed` / `No space left on device` on
  `/dev/shm` — the 64 MiB default is exhausted by DataLoader shared tensors.
  Fix: `--shm-size=1g` (Docker) or an `emptyDir{medium: Memory}` mount in k8s
  (Ch 8–9).
- **tmpfs in general.** Any `tmpfs` mount (`/tmp` if you mount it tmpfs, `--tmpfs
  /scratch`) is RAM-backed and charged to your container. Writing "temp" files to
  a tmpfs is writing to RAM.

```bash
docker run --shm-size=1g myimg                 # bigger /dev/shm
docker run --tmpfs /scratch:size=256m myimg    # explicit RAM-backed scratch
df -h /dev/shm                                  # inside container: size + usage
```

Full shared-memory mechanics (POSIX shm, `multiprocessing.shared_memory`, why
Chromium needs it) are Chapter 9.

## 7.9 The overlay filesystem, image layers, and the writable layer

**What it is.** Docker images are stacks of **read-only layers**; a running
container adds one **thin writable layer** on top, unified by the **overlay2**
storage driver (a union filesystem).

```
   +-------------------------------+
   |  Container writable layer     |  <- your runtime writes land here
   |  (copy-on-write from below)   |     (logs, temp files, pip installs)
   +-------------------------------+
   |  Image layer N (RUN pip ...)  |  read-only, SHARED across containers
   |  Image layer 2 (COPY . .)     |  read-only, shared
   |  Image layer 1 (FROM python)  |  read-only, shared
   +-------------------------------+
```

- **Memory vs. disk (crucial distinction).** The writable layer and image layers
  live on **disk**, not RAM — writing a file there is **ephemeral storage**, not
  container *memory*. It does **not** count toward `memory.max`. (Contrast with
  tmpfs/`/dev/shm`, which *are* RAM.)
- **But page cache blurs it.** Files you read/write on the overlay fs populate
  the **page cache**, which *is* RAM and *does* count in `memory.current` (though
  the reclaimable part is excluded from working set — Ch 3.14). So heavy file I/O
  raises your memory footprint even though the file itself is on disk.
- **Copy-up cost.** Modifying a file that exists in a lower read-only layer
  triggers a **copy-up** of the whole file into the writable layer — a fat log
  file rewritten in place can silently bloat ephemeral storage.
- **Production issues.** (1) Containers writing unbounded logs/temp files to the
  writable layer fill **ephemeral storage** and get evicted (k8s, Ch 8). (2)
  Confusing "disk full" (ephemeral) with "OOM" (memory) — different limits,
  different symptoms. Use a **volume** or `emptyDir` for scratch, keep the
  writable layer small.

## 7.10 Ephemeral storage vs. memory — a table you must internalize

| Where you write | Backed by | Counts as MEMORY (cgroup)? | Counts as DISK? | Survives restart? |
|---|---|---|---|---|
| Anonymous alloc (objects, arrays) | RAM | ✅ **yes** (anon) | No | No |
| `/dev/shm`, `--tmpfs`, tmpfs mount | **RAM** | ✅ **yes** (shmem) | No | No |
| Writable layer (`/app/out.log`) | Disk (overlay) | No (except page cache) | ✅ ephemeral | No |
| Image layers | Disk (read-only) | No | shared, read-only | Yes (in image) |
| Bind mount / named volume | Host disk | No (except page cache) | host disk | ✅ yes |
| Reading a big file | page cache (RAM) | ⚠️ counts, but reclaimable | — | — |

**The one-sentence rule:** *tmpfs/`/dev/shm` is RAM (charged as memory); the
writable layer is disk (charged as ephemeral storage); page cache straddles both
but is reclaimable.* Misplacing scratch data across this line causes both OOMs
and disk-pressure evictions.

## 7.11 Putting it together: a memory-sane Dockerfile & run

```dockerfile
FROM python:3.14-slim
# Cap native thread pools to the CPU limit you'll run with (avoids thread/RSS blowup)
ENV OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2
# Optional: better allocator for long-running data/ML services (Ch 5)
# RUN apt-get update && apt-get install -y libjemalloc2
# ENV LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so.2
# Cap glibc arenas in many-core hosts (Ch 5.9)
ENV MALLOC_ARENA_MAX=2
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt   # --no-cache-dir keeps image small
COPY . .
CMD ["python", "app.py"]
```

```bash
docker run \
  -m 1g --memory-swap 1g \      # hard 1 GiB, no swap (matches typical k8s)
  --cpus 2 \                    # 2 CPUs (and thread envs above respect it)
  --shm-size 512m \             # room for DataLoader/OpenCV shared memory
  --tmpfs /scratch:size=256m \  # RAM-backed scratch (counts as memory!)
  myimg
```

## 7.12 Debugging a container OOM (mini-workflow; full k8s version in Ch 13)

```
   Container exits 137 / "OOMKilled"
        |
        1. Confirm it's memory: docker inspect -f '{{.State.OOMKilled}}' <ctr> -> true
        |
        2. What was the limit vs usage? docker stats / memory.max / memory.current
        |
        3. Which KIND of memory? cat /sys/fs/cgroup/memory.stat
        |     anon high        -> your data / leak (Ch 4-5, 11)
        |     shmem high       -> /dev/shm exhaustion (raise --shm-size, Ch 9)
        |     file high        -> heavy I/O page cache (usually reclaimable)
        |     kernel/slab high -> fd/socket explosion
        |
        4. Native vs Python? memray + RSS (Ch 5) if tracemalloc looks flat
        |
        5. Fix: raise limit, cap threads (§7.5), jemalloc/MALLOC_ARENA_MAX,
           bound caches, move scratch off RAM, recycle workers (Ch 15)
```

---

## Key takeaways

- A container is **a normal process** + **namespaces** (what it sees) +
  **cgroups** (what it can use). All of Chapter 6 applies unchanged, just scoped.
- **cgroups (v2: `memory.max`/`memory.current`/`memory.stat`) enforce the limit;
  namespaces do not.** Exceeding the limit with non-reclaimable memory →
  **cgroup OOM kill, exit 137.**
- **`free`, `/proc/meminfo`, and `os.cpu_count()` report the HOST, not your
  limits** — read `/sys/fs/cgroup/memory.*` instead, and cap thread pools to your
  `--cpus`.
- **`/dev/shm`/tmpfs are RAM** (charged as memory; default `/dev/shm` is only
  64 MiB → `Bus error`); the **writable/overlay layer is disk** (ephemeral
  storage); **page cache** straddles but is reclaimable.
- A memory-sane container: hard limit = swap limit, capped native threads,
  optional jemalloc/`MALLOC_ARENA_MAX`, right-sized `--shm-size`, scratch off the
  writable layer.

## Practice exercises

1. `docker run -m 256m --memory-swap 256m python:3.14-slim` and, inside, `cat
   /sys/fs/cgroup/memory.max`. Then run `free -h` and explain why they disagree.
2. Inside that container, `python3 -c "import os; print(os.cpu_count())"` on a
   multi-core host with `--cpus 1`. What does it print and why is that dangerous?
3. `df -h /dev/shm` in a default container vs. one started with `--shm-size=1g`.
4. Write 200 MB to a file on the writable layer and 200 MB to `--tmpfs
   /scratch`; watch `docker stats` MEM USAGE for each. Explain the difference.

## Quiz questions

1. What two kernel features make a container, and which one enforces the memory
   limit?
2. Inside a 512 MiB container, `free` shows 64 GiB. Why, and what should you read
   instead?
3. Name four kinds of memory that count toward `memory.max`.
4. Why does `/dev/shm` exhaustion show up as `Bus error` in a PyTorch DataLoader,
   and how do you fix it in Docker?
5. Is writing a 2 GB log file to the container's writable layer a *memory*
   problem or a *disk* problem? When could it still affect memory?
6. On a 64-core host with `--cpus 2`, why might a NumPy job's RSS explode, and
   what env vars fix it?
7. What's the difference between `--memory` and `--memory-swap`?

## Suggested experiments

- Start a container with `-m 300m`, then allocate a growing `bytearray` in a loop
  printing `VmRSS`; watch `docker inspect -f '{{.State.OOMKilled}}'` flip to
  `true` and the container exit 137. Correlate with `memory.events` `oom_kill`.
- Compare `cat /sys/fs/cgroup/memory.stat | grep -E '^(anon|file|shmem|slab)'`
  before and after (a) allocating objects, (b) writing to `/dev/shm`, (c) reading
  a large file. See which counter each moves.
- Build the "memory-sane Dockerfile" (§7.11) and confirm `OMP_NUM_THREADS`
  actually reduces thread count via `cat /proc/$PID/status | grep Threads`.

---

*Next up: **Chapter 8 — Kubernetes Memory**, where cgroups get YAML: requests
vs. limits, QoS classes (Guaranteed/Burstable/BestEffort), how QoS maps to
`oom_score_adj`, node memory pressure and eviction, `emptyDir` (and `medium:
Memory`), volumes, ConfigMaps/Secrets, and reading a pod's real memory.*

[← Chapter 6](06_linux_memory_internals.md) · [Back to index](README.md) · [Chapter 8 →](08_kubernetes_memory.md)
