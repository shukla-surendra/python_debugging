<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 4 — Python Memory (CPython internals)

You now understand the OS side: virtual memory, segments, and the metrics
(Chapters 1–3). This chapter zooms *inside* the Python process to answer the
questions that generate the most confusion in real life:

- Why does a plain integer cost 28 bytes?
- What actually frees an object — and why is it usually **not** the garbage
  collector?
- Why does `del big_list` leave RSS exactly where it was?
- When does `gc.collect()` help, and when is calling it a superstition?
- Why does a long-running worker's memory ratchet **up** and never come back
  down, even though `tracemalloc` says nothing is leaking?

The answer to all of these lives in three layers: **reference counting**, the
**cyclic garbage collector**, and the **pymalloc allocator** (arenas → pools →
blocks). We'll build them up in order.

> Repo tie-in: everything here can be watched with
> [`../03_memory_profiling/07_gc_module_demo.py`](../03_memory_profiling/07_gc_module_demo.py)
> (the `gc` module) and reproduced with the leak patterns in
> [`../../workloads/memory_leak.py`](../../workloads/memory_leak.py). Sizes come
> from [`../03_memory_profiling/01_sys_getsizeof.py`](../03_memory_profiling/01_sys_getsizeof.py).

## 4.1 CPython architecture — the 30-second model

"Python" the language has several implementations; the one you almost certainly
run is **CPython**, the reference interpreter written in C. Its memory story:

```
   Your .py source
        |  compiled to
        v
   Bytecode (code objects)  --- executed by --->  The evaluation loop (ceval.c)
        |                                                |
        |  every value is a                              | allocates/frees
        v                                                v
   +-------------------------------------------------------------+
   |                      PyObject graph (the heap)              |
   |   ints, strs, lists, dicts, your class instances, ...       |
   +-------------------------------------------------------------+
        |  memory for those objects comes from
        v
   +-------------------------------------------------------------+
   | pymalloc (small objects <=512B)  |  malloc/mmap (big objects)|
   +----------------+-----------------+---------------------------+
                    |                              |
                    v                              v
              arenas (256 KiB anon mmap)     glibc malloc / mmap  (Ch 5)
                    |
                    v
              Linux pages (Ch 1-2)
```

Two memory-management mechanisms run on top of the `PyObject` graph:

1. **Reference counting** — immediate, deterministic, handles ~everything.
2. **The generational cyclic GC** — a periodic sweep that only exists to clean
   up **reference cycles** that refcounting alone can't.

## 4.2 `PyObject` — everything is a boxed object

**What it is.** In CPython there are **no primitives**. `42`, `"hi"`, `True`,
`None`, a function, a class — all are heap-allocated C structs beginning with a
`PyObject` header:

```c
typedef struct _object {
    Py_ssize_t ob_refcnt;      // reference count (see 4.3)
    PyTypeObject *ob_type;     // pointer to the type object
} PyObject;                    // 16 bytes on 64-bit, before payload
```

**Why it exists.** Uniformity: the interpreter can treat every value through the
same header (refcount + type), which is what makes duck typing and dynamic
dispatch work.

**Consequence — objects are "fat."** Every object pays for that header plus type
overhead:

```python
import sys
sys.getsizeof(0)          # 28   (int: 16-byte header + digit storage)
sys.getsizeof(1)          # 28
sys.getsizeof(2**70)      # 40   (bigger int -> more digit words)
sys.getsizeof("")         # 49   (str object overhead)
sys.getsizeof("a")        # 50
sys.getsizeof([])         # 56   (empty list header)
sys.getsizeof({})         # 64   (empty dict)
```

- **Common misconception.** "A list of 1,000,000 ints uses ~8 MB." No. The list
  stores 1M **pointers** (8 MB) **plus** each distinct int object (~28 B). Small
  ints (−5..256) are **interned** (cached singletons), so `[0]*1_000_000` shares
  one int object — but `list(range(1_000_000))` allocates ~1M distinct int
  objects → tens of MB. `sys.getsizeof` on the list alone hides this; use
  `pympler.asizeof` or `tracemalloc` for the deep size (Chapter 12).
- **Production issue.** This overhead is *the* reason Python is memory-hungry
  for large collections, and why NumPy/Arrays (unboxed, contiguous — Chapter 5)
  are 10–50× smaller for numeric data. See it with
  [`../03_memory_profiling/01_sys_getsizeof.py`](../03_memory_profiling/01_sys_getsizeof.py).

## 4.3 Reference counting — the real workhorse

**What it is.** Every `PyObject` carries `ob_refcnt`: how many references point
at it. When you bind, pass, or store an object the count goes **up**; when a
reference goes away it goes **down**. **The instant it hits zero, the object is
freed immediately** — its memory returned to pymalloc/malloc.

```
   a = []          # list obj refcnt = 1
   b = a           # refcnt = 2   (two names -> same object)
   del a           # refcnt = 1
   b = None        # refcnt = 0   -> object freed RIGHT HERE, synchronously
```

**Why it exists.** Determinism. Unlike a tracing GC (Java/Go) that frees "some
time later," CPython frees the moment the last reference drops — so `with
open(...)` closes promptly, `__del__` runs predictably, and memory is reclaimed
eagerly. This is a deliberate CPython design choice.

**Where the count lives.** In the object header (`ob_refcnt`). Inspect it:

```python
import sys
x = object()
sys.getrefcount(x)   # note: getrefcount reports +1 because passing x to the
                     # function itself creates a temporary reference
```

- **When it grows/shrinks.** Grows on assignment, container insertion, argument
  passing, closures capturing. Shrinks on `del`, reassignment, scope exit,
  container removal.
- **Returns memory to the OS?** It returns to the **allocator** (pymalloc),
  **not necessarily to the OS** — that's §4.9, the heart of "RSS won't drop."
- **The one thing refcounting can't do:** collect **cycles** (§4.5). That's the
  entire reason the GC exists.

> **Interview favorite.** "How does CPython manage memory?" Answer: *primarily
> reference counting (immediate, deterministic), with a supplementary
> generational cyclic garbage collector that only handles reference cycles.*
> Then mention the GIL protects refcount updates from races.

### The GIL connection

Refcounts are mutated on nearly every operation and must not race between
threads. The **GIL (Global Interpreter Lock)** serializes bytecode execution so
these `ob_refcnt` updates stay consistent without a lock per object. That's why
free-threaded/no-GIL CPython (PEP 703) needs *biased reference counting* and
other machinery. For memory, the takeaway: **refcounting + threads is why the
GIL exists**, and it's why multiprocessing (separate refcount spaces) is the
classic CPU-parallelism escape hatch (Chapter 14/15).

## 4.4 The garbage collector — what it is *actually* for

**What it is.** A separate, periodic **cyclic** garbage collector (module `gc`)
that finds and frees groups of objects that reference each other but are no
longer reachable from your program.

**Why it exists.** Reference counting fails on cycles: if A points to B and B
points to A, their counts never reach zero even after you drop all external
references. Without the GC they'd leak forever. The GC's *only* job is to break
these cycles. It does **not** manage normal object death — refcounting already
did that.

**Common misconception (huge).** "`gc.collect()` is how Python frees memory /
I should call it to reduce memory." Mostly false: **>99% of objects are freed by
refcounting the instant they go unreferenced**, with the GC never involved. The
GC only matters when you create cycles. See §4.8 for when calling it actually
helps.

## 4.5 Circular references — the thing that needs the GC

```python
class Node: ...
a, b = Node(), Node()
a.other = b          # a -> b
b.other = a          # b -> a  (a cycle)
del a, b             # external refs gone, BUT each still has refcnt 1
                     # (from the other) -> refcounting can't free them
import gc; gc.collect()   # the cyclic GC finds the unreachable cycle & frees it
```

- **Where cycles come from in real code:** parent↔child links (trees, graphs,
  DOM), objects that store a reference to a callback that closes over them,
  caches keyed by objects that also point back, exceptions holding a traceback
  that references the frame (`__traceback__`), and ORM relationships.
- **Reproduce it:** `leak_via_reference_cycle` in
  [`../../workloads/memory_leak.py`](../../workloads/memory_leak.py) builds heavy
  cyclic `Node`s; watch the `gc` reclaim them in
  [`../03_memory_profiling/07_gc_module_demo.py`](../03_memory_profiling/07_gc_module_demo.py).
- **`__del__` caveat (historical).** On Python < 3.4, cycles containing objects
  with `__del__` finalizers were **uncollectable** and leaked into `gc.garbage`.
  PEP 442 fixed this (3.4+), but `gc.garbage` is still where you look for
  finalizer trouble.

## 4.6 Generational GC — why "generational"

**The idea (the generational hypothesis):** most objects die young. So the GC
sorts tracked objects into **3 generations** and scans young ones far more
often than old ones — cheap frequent sweeps for short-lived garbage, rare
expensive sweeps for long-lived data.

```
   gen 0  (youngest)   scanned most often
   gen 1  (middle)     scanned when gen0 has run "threshold1" times
   gen 2  (oldest)     scanned rarely (long-lived objects: caches, modules)

   New container objects start in gen0. Survive a collection -> promoted to the
   next generation.
```

- **Only container-like objects are tracked.** The GC only watches objects that
  *can* form cycles — those with references to other objects (lists, dicts,
  instances, tuples-of-containers). Atomic objects (an `int`, a `str`, a `float`)
  **cannot** create a cycle, so the GC never tracks them; they're pure
  refcounting. That's why a giant list of strings has little GC overhead but a
  giant graph of objects has a lot.
- **Thresholds & tuning.**

```python
import gc
gc.get_threshold()   # (700, 10, 10) default: collect gen0 after 700 net
                     # allocations; gen1 after 10 gen0 collections; etc.
gc.get_count()       # current (gen0, gen1, gen2) counts toward thresholds
gc.set_threshold(50000, 20, 20)   # collect less often -> less CPU, more RAM
gc.freeze()          # move current objects out of GC scanning (great before
                     # fork: keeps parent pages read-only -> better COW, Ch 6)
```

- **Production issue — GC pauses.** For programs with millions of long-lived
  objects (big in-memory caches, large ML object graphs), gen2 collections walk
  the whole set and cause **latency spikes**. Two common fixes: raise thresholds
  (or `gc.disable()` in tightly-controlled batch jobs), and `gc.freeze()` after
  startup so warm objects aren't rescanned. Measure before/after — blindly
  disabling GC risks unbounded cycle growth.

## 4.7 pymalloc — arenas, pools, and blocks

Now the allocator. When CPython needs memory for a **small** object (≤ 512
bytes — which is *most* objects), it does **not** call `malloc` each time (too
slow, too fragmenting). It uses its own allocator, **pymalloc**, with a strict
hierarchy:

```
   ARENA  = 256 KiB, obtained from the OS via mmap (anonymous)
   |
   +-- POOL = 4 KiB (one page). Each pool serves ONE size class only.
       |
       +-- BLOCK = the actual object slot. All blocks in a pool are the same
           size, rounded up to an 8-byte boundary (16, 32, 48, ... 512).

   +-----------------------------------------------------------+
   | ARENA (256 KiB = 64 pools)                                |
   | +--------+--------+--------+--------+   ...                |
   | | pool   | pool   | pool   | pool   |                      |
   | |(32B    | (64B   | (16B   | free   |                      |
   | | blocks)| blocks)| blocks)| pool   |                      |
   | | [x][x] | [x][ ] | [ ][ ] |        |                      |
   | | [ ][x] | [x][x] | [ ][ ] |        |                      |
   | +--------+--------+--------+--------+                      |
   +-----------------------------------------------------------+
```

- **Block** — one object-sized slot. Freeing an object returns its block to the
  pool's free list; a new same-size object reuses it. Fast, no OS call.
- **Pool** — a 4 KiB page dedicated to one size class. Reduces fragmentation
  *within* a size class.
- **Arena** — 256 KiB of address space (anonymous `mmap`) carved into pools.
- **Why it exists.** Small-object churn is *the* dominant Python allocation
  pattern (temporaries, strings, tuples). Servicing it from pre-carved pools is
  much faster than `malloc`/`free` and avoids fragmenting the C heap.
- **≥ 512 bytes bypasses pymalloc** and goes straight to `malloc`/`mmap`
  (Chapter 5). So a large `bytearray` or NumPy array is *not* a pymalloc
  concern.

## 4.8 The object memory lifecycle (end to end)

```
   x = SomeObject()
     |
     | pymalloc finds a free BLOCK of the right size class in a POOL
     | inside an ARENA (or mmaps a new arena from the OS)
     v
   [ object lives; refcnt tracked; GC watches it if it's a container ]
     |
     | last reference dropped -> refcnt == 0
     v
   pymalloc returns the BLOCK to its pool's free list   <-- memory reusable
     |                                                       by Python, but...
     | ...the POOL/ARENA is only returned to the OS when the WHOLE arena is
     | empty (all 64 pools free). One live block pins the entire 256 KiB.
     v
   arena munmap'd -> pages returned to OS  (RSS finally drops)
```

**When does `gc.collect()` help?**

- ✅ You just tore down a large **cyclic** structure (graph, tree with
  parent-pointers, objects capturing tracebacks) and want it reclaimed *now*
  instead of at the next automatic sweep.
- ✅ Right before `fork()` combined with `gc.freeze()` to improve copy-on-write
  sharing (Chapter 6).
- ✅ In a controlled batch boundary (between jobs) to force cyclic cleanup and
  get a clean baseline.

**When it does NOT help (superstitions):**

- ❌ Reclaiming a big **non-cyclic** object — refcounting already freed it at
  `del`/scope exit; `gc.collect()` does nothing extra.
- ❌ Lowering **RSS** back to the OS — collection frees *blocks to pymalloc*, not
  necessarily *arenas to the OS* (§4.9). RSS often stays flat.
- ❌ Calling it in a hot loop "to be safe" — pure CPU cost, no benefit, and it
  can cause latency spikes.

## 4.9 Why `del` (and even `gc.collect()`) doesn't reduce RSS

This is the single most-asked Python-memory question. Three stacked reasons:

1. **Free ≠ return to OS.** `del`/refcount-zero returns the object's **block**
   to a pymalloc **pool**. The memory is now reusable *by Python*, but the arena
   (and its pages) is still mapped — **RSS unchanged**.
2. **Arena pinning / fragmentation.** An arena is only `munmap`'d when **all 64
   of its pools are completely free**. If even one small long-lived object
   remains in an arena, the whole 256 KiB stays resident. Scatter a few survivors
   across many arenas and you pin megabytes with kilobytes of live data — this is
   **fragmentation**, and it's why memory ratchets up (Chapter 11).
3. **glibc `malloc` behaves the same for big objects.** Large allocations use
   `malloc`, and glibc keeps freed memory in its own free lists / arenas rather
   than returning it (only `munmap`'d mmap-backed allocations reliably return).
   `malloc_trim()` can sometimes push it back (Chapter 5).

```python
import os, gc
def rss_mb():
    with open(f"/proc/{os.getpid()}/status") as f:
        for line in f:
            if line.startswith("VmRSS"):
                return int(line.split()[1]) // 1024

print(rss_mb())                       # baseline, e.g. 15
big = [bytes(1000) for _ in range(1_000_000)]
print(rss_mb())                       # jumps, e.g. 1100
del big
gc.collect()
print(rss_mb())                       # often STILL high (e.g. 400-1100),
                                      # NOT back to 15  -> arenas not released
```

- **Common misconception.** "There's a leak — memory didn't come back." Usually
  **not a leak**; it's retention/fragmentation (Chapter 11 distinguishes them).
  A true leak keeps growing run over run; retention plateaus.
- **What actually lowers RSS:** (a) the process exits (the only guaranteed way);
  (b) large allocations that were `mmap`-backed get freed (`munmap`); (c)
  `ctypes.CDLL("libc.so.6").malloc_trim(0)` sometimes; (d) restarting the worker
  — which is why production uses **worker recycling** (`--max-requests` in
  Gunicorn, Celery `max_tasks_per_child`), Chapters 14–15.
- **Design fix:** do heavy allocation in a **subprocess** that exits (guaranteed
  RSS release), or use an allocator that returns memory better (**jemalloc**,
  Chapter 5).

## 4.10 Memory fragmentation in CPython

**What it is.** Free memory that exists but can't be handed back to the OS (or
even reused) because it's scattered in small holes among live objects.

- **Internal fragmentation:** an object rounded up to the next size class wastes
  the slack (a 33-byte object uses a 48-byte block).
- **External fragmentation:** arenas/pools kept alive by a few survivors, as in
  §4.9. Long-running services that allocate varied sizes over time accumulate
  this.
- **Why it's worse in long-lived workers.** Request 1 allocates a big transient
  structure; request 2 leaves one cached object in each arena; over hours,
  arenas can't be freed. RSS climbs to a plateau far above steady-state live
  data — the "sawtooth that never fully falls."
- **Mitigations:** worker recycling; move big/varied allocations to short-lived
  subprocesses; switch allocator to jemalloc/tcmalloc (better fragmentation
  behavior for many workloads); reduce allocation churn (object pooling,
  generators — Chapter 15).

## 4.11 Special cases worth knowing

- **Interning / free lists.** Small ints (−5..256), some short strings, and
  interned identifiers are **cached singletons** shared process-wide. CPython
  also keeps **free lists** for frequently churned types (small tuples, floats,
  frames) to avoid re-allocating — so `sys.getrefcount(1)` is huge and freeing a
  float may not touch the allocator at all.
- **`__slots__`.** By default each instance has a `__dict__` (a whole dict,
  ~64+ B). Declaring `__slots__ = ('a', 'b')` stores attributes in a fixed C
  array instead — big memory savings for millions of instances (Chapter 15).
- **String/bytes buffers.** Large `str`/`bytes` payloads are single big
  allocations (via malloc), so they *can* return to the OS on free — unlike a
  million tiny objects.

## 4.12 Inspecting Python memory (quick tour — full catalog in Ch 12)

```python
import gc, sys, tracemalloc

sys.getsizeof(obj)            # shallow size of one object
gc.get_count()                # (gen0,gen1,gen2) allocation pressure
gc.get_stats()                # per-generation collection stats
gc.get_objects()             # EVERY tracked object (huge; filter carefully)
len(gc.get_objects())         # rough "how many tracked objects exist"

tracemalloc.start()
snap1 = tracemalloc.take_snapshot()
# ... do work ...
snap2 = tracemalloc.take_snapshot()
for stat in snap2.compare_to(snap1, 'lineno')[:10]:
    print(stat)               # top lines by *Python-level* allocation growth
```

Repo demos: `07_gc_module_demo.py` (gc), `02_tracemalloc_basics.py`,
`03_tracemalloc_snapshot_diff.py` (find growth), `06_pympler_demo.py` (deep
sizes), `05_objgraph_demo.py` (who references what). **Caveat:** `tracemalloc`
only sees allocations made **through Python's allocator** — it is blind to
NumPy/OpenCV/PyTorch **native** memory (Chapter 5), which is why "tracemalloc
says nothing leaks but RSS grows" happens.

---

## Key takeaways

- **Everything is a heap `PyObject`** with a refcount + type header — that's why
  Python objects are "fat" (an int is 28 B) and why NumPy wins for numeric data.
- **Reference counting frees ~everything, immediately and deterministically.**
  The **generational cyclic GC exists only to collect reference cycles** — it is
  not "how Python frees memory."
- **`pymalloc` serves small objects (≤512 B) from arenas → pools → blocks**;
  big objects go to `malloc`/`mmap`.
- **Freeing returns blocks to pymalloc, not pages to the OS.** An arena is only
  released when *entirely* empty, so **`del`/`gc.collect()` usually don't lower
  RSS** — that's retention/fragmentation, not a leak.
- **`gc.collect()` helps only for cycles / pre-fork / batch boundaries**;
  calling it to "reduce memory" is usually a superstition. Restarting/recycling
  workers is the reliable RSS reset.

## Practice exercises

1. Use `sys.getsizeof` on `0`, `2**100`, `""`, `"abcd"`, `[]`, `[1,2,3]`, `{}`.
   Explain each number in terms of the object header + payload.
2. Build the RSS-probe from §4.9. Allocate a million small objects, `del` +
   `gc.collect()`, and record whether RSS returns to baseline. Write one sentence
   naming the mechanism.
3. Create a reference cycle of two heavy objects, `del` the external names, and
   show via `gc.collect()`'s return value that it reclaimed them.
4. Add `__slots__` to a class with 3 attributes; compare `sys.getsizeof` and
   total memory for 1,000,000 instances with vs. without slots.

## Quiz questions

1. What frees the vast majority of Python objects — the GC or refcounting? When
   is the other one *required*?
2. Why can't reference counting alone collect `a.other=b; b.other=a`?
3. Which objects does the cyclic GC **track**, and why is an `int` never one of
   them?
4. You `del` a 1 GB list and call `gc.collect()`; RSS barely moves. Give two
   distinct reasons.
5. What is an arena, a pool, and a block — and what condition must hold for an
   arena to be returned to the OS?
6. Name two situations where `gc.collect()` genuinely helps and one where it's a
   superstition.
7. Why does `tracemalloc` sometimes report "no growth" while RSS climbs?

## Suggested experiments

- Run [`../03_memory_profiling/07_gc_module_demo.py`](../03_memory_profiling/07_gc_module_demo.py)
  and watch `gc.get_count()` climb toward the `(700,10,10)` thresholds, then
  drop after a collection.
- Run [`../../workloads/memory_leak.py`](../../workloads/memory_leak.py) and use
  [`../03_memory_profiling/03_tracemalloc_snapshot_diff.py`](../03_memory_profiling/03_tracemalloc_snapshot_diff.py)
  to attribute growth to `leak_via_global_cache` (retention, not a cycle) vs.
  `leak_via_reference_cycle` (needs the GC).
- Toggle `gc.disable()` around a workload that builds a large object graph and
  measure wall-time and peak RSS. Note the trade-off (less CPU, risk of unbounded
  cycles).

---

*Next up: **Chapter 5 — Native Memory**, where we leave CPython's allocator
entirely: NumPy/OpenCV/PyTorch/Arrow buffers, `malloc` vs. `jemalloc` vs.
`tcmalloc`, and exactly why `tracemalloc` and most Python profilers can't see
the memory that's actually OOM-killing your ML pod.*

[← Chapter 3](03_memory_metrics.md) · [Back to index](README.md) · [Chapter 5 →](05_native_memory.md)
