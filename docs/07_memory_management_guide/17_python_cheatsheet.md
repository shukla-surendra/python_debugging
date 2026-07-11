<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 17 — Python Memory Cheat Sheet

The code-level companion to Chapter 16. Paste-ready snippets for inspecting and
controlling memory from *inside* a Python process: `gc`, `sys.getsizeof`,
`tracemalloc`, `resource`, `psutil`, `objgraph`, `pympler`, `memory_profiler`.
Every snippet is self-contained. Chapter 12 explains *when* to use each; this is
the *how*, at the REPL.

> Reminder (Ch 5): Python tools that walk the object graph or hook CPython's
> allocator are **blind to native buffers** (NumPy/Torch/cv2). For those, read
> **RSS/cgroup** (§17.6) or use **memray** (Ch 12). Runnable versions live in
> [`../03_memory_profiling/`](../03_memory_profiling/).

## 17.1 `sys` — object sizes & refcounts

```python
import sys
sys.getsizeof(obj)               # SHALLOW size of one object (Ch 4.2) - no referents
sys.getsizeof([])                # 56 ; {} -> 64 ; 0 -> 28 ; "" -> 49
sys.getrefcount(obj)             # refcount (+1 for the arg itself, Ch 4.3)
sys.intern("frequent_string")    # dedupe/interned string -> shares one object
sys.getallocatedblocks()         # pymalloc blocks in use (coarse leak signal)
```
- **Gotcha:** `getsizeof` on a list/dict/NumPy array ignores contents/buffers —
  use `pympler.asizeof` (§17.8) or `.nbytes` (NumPy, Ch 5.3) for true size.

## 17.2 `gc` — the collector as inspector & knob

```python
import gc
len(gc.get_objects())            # total TRACKED objects (cheap "is it growing?")
gc.get_count()                   # (gen0, gen1, gen2) allocs toward thresholds
gc.get_stats()                   # per-generation collections/collected/uncollectable
gc.get_threshold()               # (700, 10, 10) default (Ch 4.6)

n = gc.collect()                 # force a full collection; returns #objects freed
gc.freeze()                      # exclude current objects from GC (pre-fork, Ch 6.8)
gc.disable(); gc.enable()        # turn cyclic GC off/on (measure! Ch 4.6)
gc.set_threshold(50_000, 500, 500)   # collect less often (less CPU, more RAM)

# Find uncollectable / referrers of a leak (Ch 11.5):
gc.set_debug(gc.DEBUG_SAVEALL); gc.collect(); print(gc.garbage)
gc.get_referrers(obj)            # what points AT obj
gc.get_referents(obj)            # what obj points TO
```

## 17.3 `tracemalloc` — which Python line allocated (leak finder)

```python
import tracemalloc
tracemalloc.start(25)                              # keep 25 frames of traceback

cur, peak = tracemalloc.get_traced_memory()        # bytes now / peak since start
print(cur/1e6, "MB now,", peak/1e6, "MB peak")

snap1 = tracemalloc.take_snapshot()
# ... one unit of work / one request cycle ...
snap2 = tracemalloc.take_snapshot()
for stat in snap2.compare_to(snap1, "lineno")[:10]:
    print(stat)                                    # top GROWTH by line == the leak

# Top allocations right now, grouped by file:line:
for stat in tracemalloc.take_snapshot().statistics("lineno")[:10]:
    print(stat)

# Full traceback for the single biggest allocation site:
top = snap2.statistics("traceback")[0]
print("\n".join(top.traceback.format()))

tracemalloc.stop()
```
- **Blind to native** (Ch 5.2). Moderate overhead — start early, enable behind a
  flag in prod (Ch 12.5).

## 17.4 `resource` — process peak RSS & limits (stdlib)

```python
import resource
# Peak RSS ("maximum resident set size") of THIS process:
peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss   # KB on Linux
print(peak_kb / 1024, "MB peak RSS")                            # (bytes on macOS!)

# Page faults so far (Ch 6.3):
ru = resource.getrusage(resource.RUSAGE_SELF)
print("minor faults:", ru.ru_minflt, "major:", ru.ru_majflt)

# Set a hard address-space cap (self-defense / test OOM handling):
soft, hard = resource.getrlimit(resource.RLIMIT_AS)
resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, hard))   # 512 MB cap
```
- **`ru_maxrss` unit differs by OS** (KB on Linux, bytes on macOS). Great for
  batch jobs: no imports, reports the peak.

## 17.5 `psutil` — live RSS/VMS/USS (third-party, portable)

```python
import psutil, os
p = psutil.Process(os.getpid())
mi = p.memory_info()
print(mi.rss / 1e6, "MB RSS,", mi.vms / 1e6, "MB VSZ")
full = p.memory_full_info()
print(full.uss / 1e6, "MB USS,", getattr(full, "pss", 0) / 1e6, "MB PSS")  # USS/PSS!
print(p.num_fds(), "open fds,", p.num_threads(), "threads")

# System-wide (HOST, not cgroup - Ch 7.7!):
vm = psutil.virtual_memory()
print(vm.available / 1e9, "GB available,", vm.percent, "% used")
```
- **Container caveat:** `virtual_memory()` reports the **host**, not your limit —
  read cgroup files instead (§17.7). `memory_full_info().uss`/`.pss` are the
  honest per-process numbers (Ch 3).

## 17.6 Read your own RSS / cgroup with no dependencies

```python
import os
def rss_mb(pid="self"):
    for line in open(f"/proc/{pid}/status"):
        if line.startswith("VmRSS"):
            return int(line.split()[1]) // 1024      # MB

def cgroup_mem():
    """Real container limit & usage (v2, falls back to v1). Ch 7.6/16.17."""
    def read(p):
        try: return open(p).read().strip()
        except FileNotFoundError: return None
    cur = read("/sys/fs/cgroup/memory.current") or read("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    mx  = read("/sys/fs/cgroup/memory.max")     or read("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    return cur, mx

print(rss_mb(), "MB RSS")
print("cgroup used/limit:", cgroup_mem())
```

## 17.7 `objgraph` — who retains the survivors (reference chains)

```python
import objgraph
objgraph.show_growth(limit=10)                 # types that grew since last call (Ch 11.4)
objgraph.show_most_common_types(limit=10)      # heap composition
objgraph.count("dict")                         # how many dicts exist
# Draw WHY an object is alive (needs graphviz):
obj = objgraph.by_type("MyClass")[-1]
objgraph.show_backrefs([obj], max_depth=6, filename="/tmp/backrefs.png")
objgraph.show_chain(
    objgraph.find_backref_chain(obj, objgraph.is_proper_module),
    filename="/tmp/chain.png")                 # shortest path from a module -> obj
```

## 17.8 `pympler` — deep sizes & heap summaries

```python
from pympler import asizeof, muppy, summary, tracker
asizeof.asizeof(obj)                           # DEEP size incl. all referents (Ch 5)
asizeof.asized(obj, detail=1).format()         # per-attribute breakdown

all_objs = muppy.get_objects()
summary.print_(summary.summarize(all_objs))    # table: type, count, total bytes

tr = tracker.SummaryTracker()                  # diff heap over time:
# ... do work ...
tr.print_diff()                                # what grew since tracker creation
```

## 17.9 `memory_profiler` — line-by-line RSS

```python
# pip install memory_profiler ; decorate the function:
from memory_profiler import profile
@profile
def build():
    a = [0] * 10_000_000          # each line annotated with RSS + increment
    b = a[:]                      # watch the copy's increment
    return b
```
```bash
python -m memory_profiler script.py     # prints per-line RSS + increment
mprof run script.py && mprof plot       # RSS-over-time chart (catches native, Ch 12.3)
```

## 17.10 One-off diagnostics you'll paste often

```python
# A) Snapshot: RSS + tracked objects + top tracemalloc line (paste anywhere)
import gc, os, tracemalloc
tracemalloc.start()
def snap(tag=""):
    rss = next(int(l.split()[1]) for l in open("/proc/self/status") if l.startswith("VmRSS"))//1024
    top = tracemalloc.take_snapshot().statistics("lineno")[0]
    print(f"[{tag}] RSS={rss}MB objs={len(gc.get_objects())} top={top}")

# B) Decorator: log RSS delta around any function
import functools
def memlog(fn):
    @functools.wraps(fn)
    def w(*a, **k):
        r0 = next(int(l.split()[1]) for l in open("/proc/self/status") if l.startswith("VmRSS"))//1024
        try: return fn(*a, **k)
        finally:
            r1 = next(int(l.split()[1]) for l in open("/proc/self/status") if l.startswith("VmRSS"))//1024
            print(f"{fn.__name__}: {r1-r0:+d} MB (now {r1})")
    return w

# C) Is it a cycle? count uncollectable after forcing collection
import gc; gc.set_debug(gc.DEBUG_SAVEALL); print("uncollectable:", gc.collect(), len(gc.garbage))

# D) Deep-size the top suspects
from pympler import asizeof
for name, val in list(globals().items()):
    sz = asizeof.asizeof(val)
    if sz > 5_000_000: print(f"{name}: {sz/1e6:.1f} MB")
```

## 17.11 NumPy / pandas / Torch quick size checks (native, Ch 5)

```python
arr.nbytes                                   # real bytes of a NumPy buffer
arr.base is not None                          # True => it's a VIEW (shares memory)
np.shares_memory(a, b)                        # do two arrays overlap?
df.memory_usage(deep=True).sum()              # pandas: REAL bytes (deep!) (Ch 5.4)
df.info(memory_usage="deep")
import torch
torch.cuda.memory_allocated()/1e9            # GB in live GPU tensors (Ch 5.7)
torch.cuda.memory_reserved()/1e9             # GB held by caching allocator
print(torch.cuda.memory_summary())           # full GPU breakdown
```

## 17.12 Tool → task quick index

| I want to… | Use |
|---|---|
| Size of one object (shallow) | `sys.getsizeof` |
| **Deep** size (with contents) | `pympler.asizeof.asizeof` |
| Which **line** allocates Python mem | `tracemalloc` snapshot diff |
| Which line moves **RSS** (incl. native) | `memory_profiler` / `mprof` |
| **Who retains** an object | `objgraph.show_backrefs` |
| Peak RSS of a batch job | `resource.getrusage().ru_maxrss` |
| Live RSS/USS/PSS/fds | `psutil` `memory_full_info`/`num_fds` |
| Container real limit/usage | read `/sys/fs/cgroup/memory.*` (§17.6) |
| Cycle / uncollectable check | `gc.DEBUG_SAVEALL` + `gc.garbage` |
| Native buffer size | `.nbytes`, `df.memory_usage(deep=True)`, `torch.cuda.*` |
| GC pressure / object growth | `gc.get_count()`, `len(gc.get_objects())` |

---

## Key takeaways

- **`tracemalloc` (which line) + `objgraph` (who retains) + `pympler.asizeof`
  (how big)** are the core Python-object trio; `sys.getsizeof` is shallow-only.
- **For a batch job's peak, `resource.getrusage().ru_maxrss` is the zero-import
  answer**; for live numbers use `psutil.memory_full_info()` (USS/PSS) — but it
  reports **host** system memory, so read **cgroup files** in containers.
- **All Python-object tools are blind to native buffers** — check `.nbytes`,
  `df.memory_usage(deep=True)`, `torch.cuda.*`, or RSS/memray for those (Ch 5).
- **`gc`** is both an inspector (`get_objects`/`get_count`/`garbage`) and a knob
  (`freeze`/`disable`/`set_threshold`) — measure before tuning.
- Keep the §17.10 paste snippets handy: a `snap()`/`@memlog` gives you RSS +
  object count + top allocation line anywhere in seconds.

## Practice exercises

1. Paste the §17.10 `snap()` helper before and after building a 10M-element list;
   interpret RSS, object count, and the top tracemalloc line.
2. Deep-size a dict of NumPy arrays with `pympler.asizeof` vs. `sys.getsizeof` vs.
   summing `.nbytes`; explain the differences.
3. Use `resource.getrusage().ru_maxrss` to report a script's peak RSS; convert
   correctly for your OS.
4. Use `objgraph.show_backrefs` to prove what retains a leaked object from
   [`../../workloads/memory_leak.py`](../../workloads/memory_leak.py).

## Quiz questions

1. Why does `sys.getsizeof(numpy_array)` mislead, and what gives the true size?
2. Which stdlib call reports a batch job's peak RSS with no dependencies, and
   what's the unit pitfall?
3. `psutil.virtual_memory()` inside a container shows 64 GB but your limit is
   512Mi. Why, and what do you read instead?
4. Which tool tells you *which line* allocates and which tells you *who retains*?
   How do they combine on a leak?
5. Name three `gc` calls: one inspector, one knob, one for finding
   uncollectables.
6. `tracemalloc` shows flat, RSS climbs. What can't tracemalloc see, and what do
   you switch to?

## Suggested experiments

- Wrap a suspect function with the §17.10 `@memlog` decorator in a running service
  and watch per-call RSS deltas accumulate (or not).
- Run [`../03_memory_profiling/06_pympler_demo.py`](../03_memory_profiling/06_pympler_demo.py)
  and [`../03_memory_profiling/05_objgraph_demo.py`](../03_memory_profiling/05_objgraph_demo.py)
  against the repo victim; note which answered "how big" vs. "who holds it."
- Add the §17.6 `cgroup_mem()` helper to an app and log used/limit each minute
  inside a Docker container with `-m 256m`; compare to `psutil.virtual_memory()`.

---

*Next up: **Chapter 18 — Kubernetes Cheat Sheet**: `kubectl top/describe/exec/
logs/debug`, reading `memory.current`/`memory.max`/`memory.stat` from inside a
pod, and every command for inspecting a running pod's memory.*

[← Chapter 16](16_linux_cheatsheet.md) · [Back to index](README.md) · [Chapter 18 →](18_kubernetes_cheatsheet.md)
