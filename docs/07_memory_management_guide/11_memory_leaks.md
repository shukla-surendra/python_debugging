<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 11 — Memory Leaks vs. Retention vs. Fragmentation

"We have a memory leak" is the most over-diagnosed sentence in production. Most
of the time it isn't a leak at all — it's **retention** (memory held on purpose
or by accident but bounded), **allocator caching** (freed to the allocator, not
the OS), or **fragmentation** (memory trapped in half-used arenas). Each looks
like "memory goes up," but each has a *different fix*, and applying the wrong fix
wastes days.

This chapter teaches you to **name the pattern from its shape** — using the
memory-over-time graph you already have on a dashboard — before you touch a
profiler.

> Prerequisites: Ch 3 (RSS/working set), Ch 4 (refcount/GC/pymalloc arenas,
> why RSS won't drop), Ch 5 (native/allocator behavior), Ch 10 (leak-vs-retention
> in the master table). Ch 12 is the tools; this is the *diagnosis theory*.

## 11.1 The six patterns, defined

| Pattern | What it is | Bounded? | Root cause | Fix |
|---|---|---|---|---|
| **True leak** | memory allocated, reference lost, never freeable | **No** (unbounded) | growing structure nobody frees; native `free` never called | find & drop the reference; fix native free |
| **Reference leak (retention)** | still-reachable objects you *forgot* to release | often **No** | unbounded cache, growing list/dict, registered callbacks/closures | bound the cache; unregister; weakrefs |
| **Native leak** | C/C++/CUDA buffer `malloc`'d but never `free`'d | **No** | bug in extension / missing `close()` / cycle holding a buffer | fix lib usage; `close()`; upgrade lib |
| **Allocator caching** | freed to pymalloc/glibc, not returned to OS | **Yes** (plateaus) | Ch 4.9 — arenas not released | not a bug; recycle workers / jemalloc if it matters |
| **Fragmentation** | live data scatters across arenas, pinning them | **Yes**-ish (creeps) | varied alloc sizes over time (Ch 4.10, 5.9) | jemalloc/`MALLOC_ARENA_MAX`; reduce churn |
| **Intentional cache** | memory you *chose* to hold (LRU, model, page cache) | **Yes** (by design) | working as intended | size it; nothing to "fix" |

**The single most important distinction:** **unbounded (keeps growing forever)
vs. bounded (rises then plateaus).** Unbounded ⇒ leak/retention ⇒ *find the
reference*. Bounded-but-high ⇒ caching/fragmentation ⇒ *recycle or swap
allocator*. Everything else is detail.

## 11.2 Recognize the pattern from the graph (ASCII gallery)

You can classify ~80% of incidents from the RSS/working-set chart alone. Learn
these shapes.

### True leak — unbounded linear/staircase climb to OOM

```
  RSS
   |                                          X  <- OOMKilled (137)
   |                                    __/
   |                              __/
   |                        __/
   |                  __/                 steady climb, NEVER plateaus,
   |            __/                        proportional to requests/time
   |      __/
   |__/
   +--------------------------------------------> time
      Signature: monotonic rise, resets only on restart, slope ~ traffic.
```

### Retention (unbounded cache) — same shape, different cause

```
  RSS
   |                                   __/X
   |                             __/            Looks identical to a true leak!
   |                       __/                  Difference is in the WHY:
   |                 __/                         objects are still REACHABLE
   |           __/                               (a dict/list/cache you can find
   |     __/                                      with tracemalloc/objgraph).
   +--------------------------------------------> time
```

*True leak vs. retention look the same on the graph; the profiler tells them
apart (Ch 12). In Python, pure "unreachable and unfreeable" leaks are rare —
most "leaks" are actually reachable retention.*

### Allocator caching / plateau — rises then FLATTENS (not a leak)

```
  RSS
   |            ____________________________     <- plateau: freed to allocator,
   |        __/                                      RSS held but STABLE. Safe.
   |     __/
   |  __/
   +--------------------------------------------> time
      Signature: climbs during warm-up/first big job, then flat forever.
      Fix (if the plateau is too high): worker recycling / jemalloc. NOT a leak.
```

### Fragmentation — slow upward creep on a sawtooth

```
  RSS
   |            /\    /\    /\    /\    /\  ___/    <- peaks return partway, but the
   |          /   \ /   \ /   \ /   \ /             FLOOR creeps up over hours:
   |        /     V     V     V     V               arenas pinned by survivors.
   |     __/
   +--------------------------------------------> time
      Signature: sawtooth whose troughs slowly rise. Fix: jemalloc/ARENA_MAX,
      reduce alloc-size variety, recycle workers periodically.
```

### Healthy sawtooth — grows per request, fully returns (NO problem)

```
  RSS
   |     /\      /\      /\      /\      /\
   |    /  \    /  \    /  \    /  \    /  \        troughs return to the SAME
   |___/    \__/    \__/    \__/    \__/    \__     baseline every cycle. Ideal.
   +--------------------------------------------> time
```

### Cyclic-GC pattern — periodic drops (GC collecting cycles)

```
  RSS
   |    /|   /|   /|   /|          sharp small drops at gc gen2 collections;
   |   / |  / |  / |  / |          overall flat. Normal for cycle-heavy code.
   |__/  |_/  |_/  |_/  |__
   +--------------------------------------------> time
```

## 11.3 The decisive test: does it plateau?

```
   Watch RSS / working set over a LONG run (hours, many request cycles):
        |
        +-- Keeps climbing, never flattens  ---> LEAK or RETENTION  (§11.4-11.6)
        |        |
        |        +-- profiler finds a growing reachable structure -> RETENTION
        |        +-- profiler flat but RSS grows (native)          -> NATIVE leak
        |
        +-- Rises then FLATTENS (plateau)   ---> allocator caching (NOT a bug,
        |                                        recycle/jemalloc if too high)
        |
        +-- Sawtooth with rising floor      ---> FRAGMENTATION
        |
        +-- Sawtooth, returns to baseline   ---> HEALTHY. Stop looking.
```

Run long enough. A "leak" that plateaus at hour 3 was never a leak — it was
warm-up + allocator caching. Killing the investigation early (or restarting to
"fix" it) hides this.

## 11.4 True leaks & reference leaks (retention) in Python

Because Python refcounts, a *classic* unfreeable leak is rare — you usually have
**retention**: something still references the objects. The usual culprits:

```python
# 1) Unbounded module-level cache (THE most common) - see workloads/memory_leak.py
_CACHE = {}
def handle(req):
    _CACHE[req.id] = expensive(req)     # never evicted -> grows forever

# 2) Growing list/accumulator on a long-lived object
class Service:
    def __init__(self): self.history = []
    def process(self, x): self.history.append(x)   # unbounded

# 3) Registered callbacks / observers never unregistered
signal.connect(self.on_event)           # keeps self alive forever

# 4) Closures capturing large buffers (workloads/memory_leak.py: leak_via_closure)
def make(): 
    big = bytearray(10_000_000)
    return lambda: big[0]               # closure pins 10MB per call kept

# 5) Exceptions holding frames via __traceback__ (locals kept alive)
try: ...
except Exception as e:
    self.last_error = e                 # e.__traceback__ pins the whole frame
```

- **How to find it:** `tracemalloc` snapshot-diff (which *line* keeps allocating)
  + `objgraph.show_growth()` / `show_backrefs` (what *references* the survivors) —
  Ch 12. The repo demos
  [`../03_memory_profiling/03_tracemalloc_snapshot_diff.py`](../03_memory_profiling/03_tracemalloc_snapshot_diff.py)
  and [`../03_memory_profiling/05_objgraph_demo.py`](../03_memory_profiling/05_objgraph_demo.py)
  do exactly this against
  [`../../workloads/memory_leak.py`](../../workloads/memory_leak.py).
- **Fixes:** bound caches (`functools.lru_cache(maxsize=...)`, `cachetools.TTLCache`),
  use **`weakref`** for back-references and registries (`WeakValueDictionary`),
  explicitly unregister callbacks, clear `__traceback__`/don't store exceptions,
  cap accumulator lists.

## 11.5 Object cycles (and when they matter)

- **What.** A ↔ B reference cycles (Ch 4.5). Refcounting can't free them; the
  **cyclic GC** does — *eventually*.
- **When it's a "leak":** if the GC is **disabled** (`gc.disable()`), or the cycle
  involves objects the collector can't handle, or you're allocating cycles far
  faster than gen2 runs. Then cyclic garbage accumulates.
- **Recognize:** memory drops sharply at periodic intervals (gen2 collections,
  §11.2) — if those drops *stop happening* or shrink, cycles are winning.
- **Diagnose:** `gc.collect()` returns the count it freed; `gc.garbage` (with
  `gc.set_debug(gc.DEBUG_SAVEALL)`) shows uncollectable objects;
  `len(gc.get_objects())` trending up. Repo demo:
  [`../03_memory_profiling/07_gc_module_demo.py`](../03_memory_profiling/07_gc_module_demo.py).
- **Fix:** break cycles explicitly (set refs to `None` in teardown), use
  `weakref` for parent pointers, don't disable the GC in cycle-heavy code, or call
  `gc.collect()` at safe boundaries.

## 11.6 Native leaks

- **What.** A C/C++/CUDA buffer `malloc`'d (or `cudaMalloc`'d) and never freed —
  the Python wrapper may be gone but the native buffer lingers. Or a library bug
  that grows internal state.
- **Recognize (the tell):** **RSS climbs unbounded while `tracemalloc` and
  `len(gc.get_objects())` stay flat** (Ch 5.2). Python sees nothing; the OS sees
  growth. Also GPU: `torch.cuda.memory_allocated()` climbing without your tensors
  growing.
- **Diagnose:** **memray** (intercepts `malloc`/`free`, attributes native
  allocations to stacks — the right tool), `LD_PRELOAD` jemalloc heap profiling
  (`prof:true`), library-specific tools (`torch.cuda.memory_summary()`), valgrind
  `--tool=memcheck` / `massif` for pure C repro.
- **Common sources:** un-`close()`d Pillow images / file handles / DB cursors,
  OpenCV `VideoCapture` not released, a C extension missing a `Py_DECREF`, PyTorch
  tensors kept alive by autograd graph (`loss` retaining the whole graph — detach
  or `torch.no_grad()`), pinned host memory.
- **Fix:** always `close()`/release native resources (context managers), detach
  tensors, upgrade the library, cap DataLoader/pinned memory.

## 11.7 Allocator caching & fragmentation (not bugs — behaviors)

- **Allocator caching (Ch 4.9, 5.9).** After you free objects, pymalloc keeps the
  arenas and glibc keeps its free lists. RSS stays high but **stable**. This is
  the **plateau** shape. It is *not* a leak — memory is reusable by the process.
- **Fragmentation (Ch 4.10, 5.9).** Over a long run with varied allocation sizes,
  a few survivors pin many arenas; RSS **creeps** upward (the rising-floor
  sawtooth). Worse with glibc + many threads (many arenas).
- **How to confirm it's caching/fragmentation, not a leak:** RSS ≫ live data
  (from tracemalloc/memray) **and** it plateaus or creeps slowly rather than
  tracking traffic linearly. `malloc_trim(0)` reclaiming a chunk is a strong hint
  it was retained free memory, not a leak.
- **Fixes (no code-logic bug to find):**
  - **Worker recycling** — the pragmatic industry standard: restart workers after
    N requests (`gunicorn --max-requests 1000 --max-requests-jitter 100`, Celery
    `worker_max_tasks_per_child`, uWSGI `max-requests`). RSS resets on restart.
    (Ch 15)
  - **Swap the allocator** — `LD_PRELOAD` jemalloc/tcmalloc; cap
    `MALLOC_ARENA_MAX` (Ch 5.10).
  - **Reduce churn** — object pooling, generators, fewer transient large allocs
    (Ch 15).
  - **Isolate big jobs** in short-lived subprocesses that exit (guaranteed RSS
    release, Ch 4.9/14).

## 11.8 The differential-diagnosis flow (leak vs. everything else)

```
   Memory going up. Is it a bug?
        |
   [A] Let it run for hours across many cycles. Does RSS/working set PLATEAU?
        |                                   |
        | no (keeps climbing)               | yes (flattens)  -> allocator caching:
        v                                   |                    NOT a leak. Recycle
   [B] tracemalloc/objgraph: is a           |                    or jemalloc if too high.
       reachable Python structure growing?  |
        |            |                        \-> sawtooth w/ rising floor?
        | yes        | no (flat)                    -> FRAGMENTATION (jemalloc)
        v            v
   RETENTION    [C] RSS grows but Python tools flat?
   (bound the        |
    cache /          v
    weakref)     NATIVE leak -> memray / cuda tools -> close()/detach/upgrade
        |
        v
   [D] periodic GC drops stopped / gc.garbage growing? -> CYCLE accumulation
        (break cycles / don't disable GC)
```

## 11.9 Reproduce, then trust the fix

Every fix must be validated against the **shape** and a **long run** — not a
5-minute test (which can't distinguish plateau from leak).

- **Reproduce** with the repo victim
  [`../../workloads/memory_leak.py`](../../workloads/memory_leak.py) (unbounded
  cache = retention, reference cycle = GC, closure = retention) and watch each
  pattern emerge.
- **Validate a fix** by confirming the graph changed shape: an unbounded climb
  becomes a plateau/healthy-sawtooth; a rising-floor sawtooth becomes flat. If RSS
  still climbs after the "fix," you fixed the wrong pattern.

---

## Key takeaways

- **Not everything that grows is a leak.** The decisive test is **does it
  plateau?** Unbounded ⇒ leak/retention (find the reference). Plateau ⇒ allocator
  caching (recycle/jemalloc). Rising-floor sawtooth ⇒ fragmentation.
- **Learn the shapes:** you can classify most incidents from the memory graph
  before opening a profiler (§11.2).
- **In Python, "leaks" are usually reachable retention** — unbounded caches,
  growing accumulators, un-unregistered callbacks, closures, stored exceptions.
  Bound them; use `weakref`.
- **Native leaks give the signature RSS-up / tracemalloc-flat** — use **memray**
  and library tools, not Python-level profilers.
- **Caching & fragmentation are behaviors, not bugs** — fix with **worker
  recycling**, allocator swaps, and reduced churn, not by hunting a nonexistent
  reference.

## Practice exercises

1. For each ASCII shape in §11.2, name the pattern, whether it's a bug, and the
   first fix you'd try. Do it without re-reading the labels.
2. Run [`../../workloads/memory_leak.py`](../../workloads/memory_leak.py) three
   ways (cache only, cycle only, closure only) and sketch/plot the RSS shape each
   produces. Match them to §11.2.
3. Take a plateau graph and a linear-climb graph; write the one-line reason each
   is or isn't a bug, and the fix.
4. Write a 20-line unbounded cache; add `functools.lru_cache(maxsize=1000)` or a
   `TTLCache`; confirm the shape changes from climb to plateau.

## Quiz questions

1. Two services both show RSS climbing to OOM with identical graphs. One is a
   true leak, one is retention. How do you tell them apart, and does it change the
   fix?
2. RSS rises for 20 minutes then stays flat for 6 hours. Leak or not? What is it,
   and when (if ever) would you act?
3. You see a sawtooth whose troughs slowly rise over a day. Name it and give two
   fixes.
4. `tracemalloc` shows no growth but RSS climbs steadily. What category is this,
   and which tool do you reach for?
5. Why are pure unfreeable leaks rare in CPython, and what takes their place?
6. Periodic sharp drops in RSS suddenly stop appearing. What's likely happening
   and how do you confirm?
7. Why is a 5-minute test insufficient to conclude "no leak"?

## Suggested experiments

- Instrument any long-running worker to log RSS + `len(gc.get_objects())` +
  tracemalloc top-1 each minute for an hour; classify the resulting shape.
- Introduce a deliberate unbounded cache and watch the climb; then bound it and
  confirm the plateau. Then introduce glibc fragmentation (varied-size alloc loop
  with threads) and watch the floor creep; fix with `MALLOC_ARENA_MAX=2` +
  jemalloc and compare.
- Reproduce a native "leak" by never `close()`-ing Pillow images in a loop; watch
  RSS climb while tracemalloc stays flat; then add `with Image.open(...) as im:`
  and confirm the difference.

---

*Next up: **Chapter 12 — Memory Profiling: The Complete Tool Catalog**, covering
every Linux tool (top/htop/ps/smem/pmap/vmstat/sar/perf/slabtop, `/proc`) and
every Python tool (tracemalloc, memory_profiler, objgraph, Pympler, guppy3,
memray, scalene, py-spy, pyroscope) — what each measures, its limits, and its
production use.*

[← Chapter 10](10_memory_growth.md) · [Back to index](README.md) · [Chapter 12 →](12_memory_profiling.md)
