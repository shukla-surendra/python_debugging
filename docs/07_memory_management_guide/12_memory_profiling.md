<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 12 — Memory Profiling: The Complete Tool Catalog

You now know *what* to look for (Ch 1–10) and *how to name the pattern* (Ch 11).
This chapter is the toolbox: every Linux and Python memory tool, what layer it
sees, its blind spots, and when to reach for it in production. The golden rule
threaded through the whole chapter:

> **No single tool sees everything.** OS tools see RSS but not *which Python
> line*; `tracemalloc` sees Python lines but not *native* buffers; `memray` sees
> native but adds overhead. You **triangulate**: OS tool to size the problem →
> Python/native profiler to localize it.

This maps directly onto the repo's runnable demos in
[`../03_memory_profiling/`](../03_memory_profiling/) — each tool below points at
one you can execute against
[`../../workloads/memory_leak.py`](../../workloads/memory_leak.py).

> Prerequisites: Ch 3 (RSS/PSS/USS/`smaps`), Ch 5 (native vs. Python memory),
> Ch 11 (patterns). Ch 13 assembles these into a k8s workflow.

## 12.1 Which layer does each tool see?

```
   LAYER                              TOOLS THAT SEE IT
   -----------------------------------------------------------------
   Node / system RAM ............... free, vmstat, sar, /proc/meminfo, slabtop
   Per-process RSS/PSS/USS ......... top, htop, ps, smem, pmap, /proc/<pid>/*
   Kernel slab / buffers ........... slabtop, /proc/slabinfo, /proc/meminfo
   Native heap (malloc/mmap) ....... memray, jemalloc prof, valgrind massif
   Python objects (per line) ....... tracemalloc, memory_profiler, scalene
   Python object GRAPH / refs ...... objgraph, Pympler, guppy3, gc
   Sampling in prod (low overhead) . py-spy, memray (sampling), pyroscope
   -----------------------------------------------------------------
   Rule: pick the tool for the LAYER your Ch 10/11 diagnosis pointed at.
```

## 12.2 Linux tools

### top / htop — first glance, live

- **Measures:** per-process **RES (=RSS)**, `VIRT (=VSZ)`, `%MEM`, `SHR` (shared),
  and (htop) a nicer TUI with per-thread view. System totals up top.
- **Use:** the 5-second "is memory the problem and which process?" check.
- **Limits:** RES **over-counts shared pages** (Ch 3.3); no PSS; no per-line
  attribution; `VIRT` is meaningless for sizing. htop's `MEM%` is RSS-based.
- **Pro tips:** press `M` in top to sort by memory; in htop set up the `M_RESIDENT`
  and `M_SHARE` columns and enable `PSS` via `/proc` if available.

```bash
top -o %MEM             # sort by memory
htop                    # F6 -> sort by RES/MEM; F2 to add PSS column on some builds
```

### ps — scriptable snapshot

- **Measures:** `RSS`, `VSZ`, `%MEM` per process, scriptable and stable columns.
- **Use:** logging/alerting, cron memory samples, comparing workers.

```bash
ps -o pid,rss,vsz,%mem,cmd --sort=-rss | head       # top RSS consumers (KB)
ps -o rss= -p $PID                                   # one process, for scripts
watch -n1 'ps -o rss= -p '$PID                       # crude live RSS
```

- **Limits:** RSS over-count (same as top); no shared apportioning.

### smem — the honest one (PSS/USS)

- **Measures:** **PSS and USS** (Ch 3.4–3.5) by reading `/proc/<pid>/smaps` — the
  only common CLI that apportions shared memory correctly.
- **Use:** capacity planning ("what does this fleet *really* use"), finding the
  leaking worker via **USS**, per-mapping breakdown.
- **Limits:** reads all of `smaps` so it's slower; needs to be installed
  (`apt install smem`); root for other users' processes.

```bash
smem -k -c "pid user command rss pss uss" --sort=pss   # apportioned view
smem -r -k -c "pid pss uss rss" | head                 # worst PSS first
smem -tk -P python                                       # totals for python procs
```

### pmap — per-mapping breakdown of one process

- **Measures:** every mapping of a process with sizes/RSS/dirty — a CLI view of
  `/proc/<pid>/maps`+`smaps` (Ch 2.11).
- **Use:** "what are the big regions?" — spot a huge anonymous block (native
  buffer), many arenas (glibc, Ch 5.9), or mmap'd files.

```bash
pmap -x $PID | sort -k3 -n | tail        # biggest RSS mappings
pmap -x $PID | tail -1                    # total line
```

### /proc/<pid>/{status,smaps_rollup,maps} — ground truth, no install

- **status:** `VmRSS`, `VmSize`, `VmData`, `VmStk`, `VmSwap`, `VmPTE`, `Threads`.
- **smaps_rollup:** aggregated `Rss/Pss/Private_*/Shared_*/Anonymous/Swap` — the
  fastest way to get PSS/USS without `smem` (Ch 3.16).
- **maps:** classify each region (Ch 2.11).

```bash
grep -E 'VmRSS|VmSwap|VmData|Threads' /proc/$PID/status
grep -E '^(Rss|Pss|Private_Clean|Private_Dirty|Anonymous|Swap):' /proc/$PID/smaps_rollup
```

### free — system memory & the `available` truth

- **Measures:** system total/used/free/**buff-cache**/**available**, swap
  (Ch 3.12). **Alert on `available`, not `free`.**
- **Container caveat:** reports the **host**, not your cgroup (Ch 7.7) — read
  `/sys/fs/cgroup/memory.*` instead inside containers.

```bash
free -h -w             # -w splits buffers/cache; watch the 'available' column
```

### vmstat — pressure & swap over time

- **Measures:** `si`/`so` (swap in/out), `free`, `buff`, `cache`, `b` (blocked),
  faults — sampled per interval. **The swap-thrashing detector (Ch 6.6).**
- **Use:** is the node thrashing? Rising `si`/`so` = memory pressure.

```bash
vmstat 1 10            # 1s samples; watch si/so and free/cache trends
```

### sar / pidstat — historical & per-process rates

- **sar** (sysstat): **historical** memory/swap/paging (`sar -r`, `sar -B`,
  `sar -S`) from stored samples — "what did memory do at 3 a.m. last night?"
- **pidstat -r:** per-process **minor/major fault rates** and RSS over time —
  the tool for spotting major-fault storms (Ch 6.4).

```bash
sar -r 1 5             # memory util samples
sar -B 1 5             # paging: pgpgin/out, majflt/s, pgscan
pidstat -r 1 -p $PID   # per-process minflt/s, majflt/s, RSS
```

### perf — fault & allocation events (advanced)

- **Measures:** hardware/software events including `page-faults`,
  `minor-faults`, `major-faults`, and (with probes) allocation call stacks.
- **Use:** deep native investigation, fault attribution, flame graphs of where
  faults originate.

```bash
perf stat -e page-faults,minor-faults,major-faults -p $PID sleep 10
perf record -e page-faults -p $PID -g -- sleep 10 && perf report
```

### slabtop — kernel object memory

- **Measures:** kernel **slab** caches (`dentry`, `inode`, network buffers) —
  the kernel/slab layer that counts against cgroups (Ch 3.13).
- **Use:** OOM with small user RSS → suspect fd/socket/dentry explosion.

```bash
sudo slabtop -o | head
grep -E '^(Slab|SReclaimable|SUnreclaim):' /proc/meminfo
```

### lsof / strace — indirect but useful

- **lsof:** open files/sockets (fd leaks → kernel memory, Ch 3.13):
  `lsof -p $PID | wc -l`.
- **strace:** watch `mmap`/`munmap`/`brk` syscalls live to see allocation
  behavior: `strace -f -e trace=memory -p $PID`.

## 12.3 Python tools

### sys.getsizeof — shallow, per object

- **Measures:** the **shallow** size of one object's own struct (Ch 4.2). **Does
  not** include referenced objects or native buffers.
- **Use:** quick "how big is this header/container?"; teaching object overhead.
- **Limits:** meaningless for NumPy/pandas/containers-of-objects (Ch 5). Repo:
  [`../03_memory_profiling/01_sys_getsizeof.py`](../03_memory_profiling/01_sys_getsizeof.py).

### tracemalloc — the built-in Python allocation profiler

- **Measures:** memory allocated **through CPython's allocator**, attributed to
  the **Python line** that allocated it; supports **snapshot diffing** (the leak
  finder).
- **Use:** the first Python profiler to reach for a suspected **Python-object**
  leak/retention — no install, works in prod behind a flag.
- **Limits:** **blind to native memory** (Ch 5.2); adds overhead + doubles some
  bookkeeping; must be started early.

```python
import tracemalloc
tracemalloc.start(25)                       # keep 25 frames of traceback
snap1 = tracemalloc.take_snapshot()
# ... run a work cycle ...
snap2 = tracemalloc.take_snapshot()
for s in snap2.compare_to(snap1, 'lineno')[:10]:
    print(s)                                 # top growth by line == the leak
```

Repo: [`../03_memory_profiling/02_tracemalloc_basics.py`](../03_memory_profiling/02_tracemalloc_basics.py),
[`../03_memory_profiling/03_tracemalloc_snapshot_diff.py`](../03_memory_profiling/03_tracemalloc_snapshot_diff.py).

### memory_profiler — line-by-line RSS

- **Measures:** **process RSS delta per source line** (via `psutil`) with the
  `@profile` decorator; `mprof` records RSS over time into a plot.
- **Use:** "which line makes RSS jump?" — and because it's RSS-based it **does**
  catch native spikes (unlike tracemalloc), just without native attribution.
- **Limits:** slow (line tracing); RSS granularity is coarse; largely
  unmaintained but still handy. Repo:
  [`../03_memory_profiling/04_memory_profiler_demo.py`](../03_memory_profiling/04_memory_profiler_demo.py).

```bash
python -m memory_profiler script.py          # needs @profile on functions
mprof run script.py && mprof plot            # RSS-over-time chart
```

### objgraph — who references the survivors

- **Measures:** the **Python object graph** — counts by type, growth between
  points, and **backref chains** (what keeps an object alive).
- **Use:** the retention-hunter's tool (Ch 11.4): `show_growth()` finds what's
  accumulating; `show_backrefs()` draws *why* it's retained.

```python
import objgraph
objgraph.show_growth(limit=10)               # types that grew since last call
objgraph.show_backrefs([obj], max_depth=5, filename='refs.png')  # who holds it
```

Repo: [`../03_memory_profiling/05_objgraph_demo.py`](../03_memory_profiling/05_objgraph_demo.py).

### Pympler — deep sizes & summaries

- **Measures:** **deep** (recursive) object size via `asizeof`, `muppy` heap
  snapshots, `summary` diffs, and class-tracker growth.
- **Use:** "how big is this structure *really*" (unlike `getsizeof`) and
  heap-composition over time.

```python
from pympler import asizeof, muppy, summary
asizeof.asizeof(obj)                          # deep size incl. referents
summary.print_(summary.summarize(muppy.get_objects()))
```

Repo: [`../03_memory_profiling/06_pympler_demo.py`](../03_memory_profiling/06_pympler_demo.py).

### guppy3 / heapy — heap analysis

- **Measures:** whole-heap partitioning by type/referrer (`hp.heap()`), classic
  deep heap explorer.
- **Use:** interactive heap forensics; heavier and steeper learning curve than
  objgraph/Pympler; less used today but powerful.

```python
from guppy import hpy; hp = hpy()
hp.heap()                                     # partitioned heap view
```

### gc — the collector as a probe

- **Measures:** tracked-object counts, generation stats, cycles, uncollectables.
- **Use:** confirm cycle accumulation (Ch 11.5); `len(gc.get_objects())` as a
  cheap "is the object count growing?" signal.

```python
import gc
len(gc.get_objects()); gc.get_count(); gc.get_stats()
gc.set_debug(gc.DEBUG_SAVEALL); gc.collect(); gc.garbage   # uncollectables
```

Repo: [`../03_memory_profiling/07_gc_module_demo.py`](../03_memory_profiling/07_gc_module_demo.py).

### memray — THE native + Python allocation profiler (Bloomberg)

- **Measures:** **every `malloc`/`free`** at the C level *and* Python frames —
  the one tool that sees **native buffers** (NumPy/Torch/cv2) with full stacks,
  plus flame graphs, a live TUI, and a **leak report** mode.
- **Use:** the **phantom OOM** (Ch 5.11) — "RSS climbs, tracemalloc flat." Also
  the best all-round allocation profiler for Python today.
- **Limits:** overhead in tracking mode (use **sampling** in prod); Linux/macOS;
  captures to a file you analyze offline.

```bash
memray run -o out.bin script.py               # record
memray flamegraph out.bin                     # -> interactive HTML flame graph
memray tree out.bin                           # allocation tree in terminal
memray run --native -o out.bin script.py      # include C/C++ native stacks
memray run --live script.py                   # live TUI
```

Repo walkthrough: [`../03_memory_profiling/08_memray_demo.md`](../03_memory_profiling/08_memray_demo.md).

### scalene — CPU + memory + GPU, separates Python vs. native

- **Measures:** line-level **CPU, memory, and GPU** at once, and crucially
  **distinguishes Python-level vs. native memory** and copy volume — with low
  overhead (sampling).
- **Use:** one-shot "where's my time AND memory, and is it Python or C?" — great
  first pass on data/ML scripts.

```bash
scalene script.py                             # rich HTML/terminal report
scalene --reduced-profile script.py
```

### py-spy — sampling, no code changes, attach to prod

- **Measures:** primarily a **CPU/stack** sampler, but invaluable in memory work:
  attach to a **running** process (no restart, no imports) to see *what it's
  doing* while memory climbs (e.g. stuck in a loop appending to a cache).
- **Use:** production triage — `py-spy dump` for an instant stack, `py-spy top`
  for live. Pairs with RSS growth to catch the culprit code path.
- **Limits:** not an allocation profiler; needs `ptrace` (cap/sudo). See the CPU
  chapter's [`../02_cpu_profiling/06_py_spy_record.md`](../02_cpu_profiling/06_py_spy_record.md)
  and stack-dump [`../01_stack_dumps/06_py_spy_dump.md`](../01_stack_dumps/06_py_spy_dump.md).

```bash
py-spy dump --pid $PID                         # instant stack of every thread
py-spy top --pid $PID                          # live top-like function view
```

### pyroscope (+ memray/eBPF) — continuous profiling in production

- **Measures:** **continuous**, always-on profiles (CPU + memory allocations)
  shipped to a server, so you can look *back* at what a pod was allocating when it
  OOMed at 3 a.m. Integrates memray/eBPF for allocation profiles.
- **Use:** fleet-wide, historical, low-overhead production profiling — the
  "always have the data" answer to intermittent OOMs. See the observability
  section [`../06_observability/`](../06_observability/).

## 12.4 The tool-selection decision table

| You need to… | Reach for | Why |
|---|---|---|
| See if memory is the problem, fast | `top`/`htop`, `free` (`available`) | 5-second triage |
| Real fleet RAM (no double count) | **smem** (PSS/USS), `smaps_rollup` | apportions sharing (Ch 3) |
| Find the leaking worker | **smem USS**, `ps --sort=-rss` | private growth per process |
| See big regions of one process | `pmap -x`, `/proc/<pid>/maps` | native buffers, arenas |
| Node thrashing / swap | **vmstat** `si/so`, `sar -B`, `pidstat -r` | pressure + major faults (Ch 6) |
| Kernel/slab OOM (small RSS) | **slabtop**, `lsof \| wc -l` | fd/socket/dentry (Ch 3.13) |
| Which **Python line** allocates | **tracemalloc** (snapshot diff) | per-line Python attribution |
| Which line makes **RSS** jump | **memory_profiler**/`mprof` | RSS-based, catches native spikes |
| **Who retains** the objects | **objgraph** backrefs, Pympler | reference chains (Ch 11.4) |
| Deep object size | **Pympler** `asizeof` | recursive, unlike getsizeof |
| **Native** buffers (NumPy/Torch) | **memray** (`--native`) | sees malloc/free (Ch 5) |
| Python vs native split, + CPU | **scalene** | separates the two cheaply |
| Attach to **running prod** proc | **py-spy** (dump/top) | no restart, no code change |
| Always-on historical profiles | **pyroscope** + memray | look back at the OOM moment |

## 12.5 Overhead & production-safety guide

| Tool | Overhead | Safe to attach to prod? | Notes |
|---|---|---|---|
| top/htop/ps/smem/pmap/free/vmstat/`/proc` | ~none | ✅ yes | read-only OS views |
| slabtop/sar/pidstat/lsof | low | ✅ yes | monitoring-grade |
| py-spy | very low (sampling) | ✅ yes (needs ptrace) | no target changes |
| pyroscope | low (continuous sampling) | ✅ designed for it | fleet-wide |
| scalene | low–moderate (sampling) | ⚠️ staging/canary | great dev tool |
| memray (sampling) | moderate | ⚠️ canary/short windows | full stacks |
| tracemalloc | moderate–high | ⚠️ behind a flag, short | doubles some bookkeeping |
| memory_profiler (line) | high | ❌ dev only | line tracing is slow |
| objgraph/Pympler/guppy full walk | high (walks heap) | ❌ dev/staging | can pause a big heap |

**Production discipline:** default to **OS tools + py-spy + continuous
profiling**; enable heavy profilers (tracemalloc/memray) **on a canary or behind
a runtime flag for a short window**, never blanket-on across a fleet.

## 12.6 A triangulation recipe (ties Ch 10–11–12 together)

```
   1. OS sizes it:   smem/smaps_rollup -> how big, PSS/USS, which worker?
                     memory.stat       -> anon vs shmem vs file vs slab (Ch 10)
   2. Classify:      Ch 11 shape       -> leak / retention / caching / frag?
   3. Localize:
        anon + tracemalloc grows  -> tracemalloc diff -> the Python LINE
                                     + objgraph backrefs -> the RETAINER
        anon + tracemalloc flat   -> memray --native   -> the C alloc site
        shmem                     -> du /dev/shm, ipcs  (Ch 9)
        slab/kernel               -> slabtop, lsof      (Ch 3.13)
   4. Confirm fix:   re-run long; verify the graph shape changed (Ch 11.9)
```

---

## Key takeaways

- **No tool sees all layers** — match the tool to the layer your Ch 10/11
  diagnosis pointed at (system / per-process / native / Python-object /
  reference-graph).
- **OS ground truth:** `smem`/`smaps_rollup` for **PSS/USS** (not top's
  over-counting RSS), `pmap` for regions, `vmstat`/`pidstat` for pressure/faults,
  `slabtop` for kernel memory.
- **Python objects:** `tracemalloc` (which *line*, snapshot-diff = leak finder) +
  `objgraph`/`Pympler` (who *retains*). **Native:** `memray` (the phantom-OOM
  tool) or `scalene` (Python-vs-native split).
- **Production:** OS tools + **py-spy** + **pyroscope** are safe/always-on; enable
  **tracemalloc/memray** only on a canary or behind a flag for a short window.
- **Triangulate:** OS sizes it → Ch 11 classifies the shape → the right profiler
  localizes it → re-run long to confirm the shape changed.

## Practice exercises

1. Run [`../../workloads/memory_leak.py`](../../workloads/memory_leak.py) and,
   against it, exercise: `tracemalloc` snapshot-diff, `objgraph.show_growth`,
   `pympler.asizeof`, and `memray flamegraph`. Note what each *uniquely* reveals.
2. On any running Python process, capture: `smem` PSS/USS, `pmap -x` biggest
   region, `/proc/$PID/smaps_rollup`. Reconcile the three RSS figures.
3. Use `py-spy dump` on a process while it's growing memory in a loop; identify
   the code path from the stack alone.
4. Fill in §12.4's table from memory for five scenarios, then check.

## Quiz questions

1. Your NumPy job's RSS climbs but `tracemalloc` shows nothing. Which tool, which
   flag, and why does tracemalloc miss it?
2. Why does `smem` give a truer fleet total than summing `top`'s RES?
3. Which tool tells you *which line* allocates Python memory, and which tells you
   *who retains* the result? How do they combine?
4. You suspect an fd/socket leak causing OOM with tiny user RSS. Which two tools
   confirm it?
5. Rank tracemalloc, memray-sampling, py-spy, and memory_profiler by production
   safety, and state where you'd run each.
6. What's the difference between what `memory_profiler` and `tracemalloc` measure,
   and when does that difference matter?
7. Give the 4-step triangulation recipe for a phantom OOM.

## Suggested experiments

- Take one leak and localize it three ways (tracemalloc line, objgraph backref,
  memray stack); note which gave the fastest "aha."
- Compare overhead: time
  [`../../workloads/memory_leak.py`](../../workloads/memory_leak.py) plain vs.
  under tracemalloc vs. under `memray run` vs. under `python -m memory_profiler`.
- Wire `smem -r -k -c "pid pss uss command"` into a 1-minute cron and watch which
  worker's **USS** grows — the leaking one.

---

*Next up: **Chapter 13 — Kubernetes Memory Debugging Workflow**, a complete
step-by-step: a pod's memory keeps rising — from `kubectl` symptoms through
cgroup `memory.stat`, tracemalloc-vs-memray, `/dev/shm`, and node pressure — to
root cause, using realistic output at each step.*

[← Chapter 11](11_memory_leaks.md) · [Back to index](README.md) · [Chapter 13 →](13_kubernetes_debugging.md)
