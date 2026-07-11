<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 15 — Optimization Techniques

Chapters 11–14 diagnosed *why* memory grows. This chapter is the **fix toolbox** —
the concrete techniques those case studies kept pointing at. Everything here maps
to the **five universal fixes** from Chapter 14:

> **bound it · stream it · share it as a native buffer · isolate it in a
> subprocess · recycle the worker**

Each technique below states what it does, when to use it, its trade-off, and a
code snippet. The overarching principle: **the cheapest memory is the memory you
never allocate** — process data incrementally, reuse buffers, and never hold more
than you need at once.

> Prerequisites: Ch 4 (objects/`__slots__`/GC), Ch 5 (NumPy/pandas/native), Ch 11
> (retention/fragmentation), Ch 14 (where these apply).

## 15.1 Generators, iterators, and streaming — don't materialize

**The single highest-leverage technique.** A list holds *everything at once*; a
generator holds *one item at a time*. Converting materialization to streaming
often cuts peak memory by 100–1000×.

```python
# BAD: materializes the whole file in RAM (peak = file size + objects)
lines = open("huge.log").readlines()
big = [transform(l) for l in lines]        # two full copies live at once
total = sum(x.value for x in big)

# GOOD: streams one line at a time (peak = one line)
def rows(path):
    with open(path) as f:
        for line in f:                     # file object is already a generator
            yield transform(line)
total = sum(x.value for x in rows("huge.log"))   # constant memory
```

- **When.** Any time you `read().split()`, `.readlines()`, build a giant list
  comprehension, or `list(some_generator)`. ETL, log processing, API pagination.
- **Trade-off.** Single-pass (can't index/re-iterate without re-reading); slightly
  more code. Almost always worth it.
- **Tools:** `itertools` (`islice`, `chain`, `groupby`), generator expressions
  `(x for x in ...)` instead of `[x for x in ...]`, `yield from`.

## 15.2 Chunk processing — bounded batches

When you *must* batch (vectorized ops, DB writes), process in **fixed-size
chunks** so peak memory is `chunk_size`, not `total_size`.

```python
from itertools import islice
def chunks(iterable, n):
    it = iter(iterable)
    while batch := list(islice(it, n)):
        yield batch

for batch in chunks(rows("huge.csv"), 10_000):   # 10k at a time
    df = pd.DataFrame(batch)
    write(df)                                     # peak ~ 10k rows, not all rows

# pandas / NumPy native chunking:
for df in pd.read_csv("huge.csv", chunksize=100_000):   # Ch 5.4/14.6
    process(df)
```

- **When.** DataFrame builds, model inference batches (Ch 14.4/14.12), bulk DB
  ops. **Batch size is a memory dial** — tune it to your limit.
- **Trade-off.** Too small = throughput/overhead cost; too large = memory. Find
  the knee.

## 15.3 `__slots__` — kill the per-instance `__dict__`

By default every instance carries a `__dict__` (~64+ bytes plus contents).
`__slots__` stores attributes in a fixed C array — big savings when you have
**millions of small objects** (Ch 4.11).

```python
class Point:                       # ~152 bytes/instance (has __dict__)
    def __init__(self, x, y): self.x, self.y = x, y

class SlotPoint:
    __slots__ = ("x", "y")         # ~56 bytes/instance, no __dict__
    def __init__(self, x, y): self.x, self.y = x, y
# 10M instances: ~1.5 GB vs ~560 MB
```

- **When.** Many instances of a fixed-shape class (graph nodes, records, events).
- **Trade-off.** No dynamic attributes, no `__dict__`/`__weakref__` unless added
  to slots, some multiple-inheritance friction. For bulk records, prefer
  `NamedTuple`, `@dataclass(slots=True)`, or better — columnar (§15.9).

## 15.4 Weak references — cache/reference without owning

A `weakref` lets you reference an object **without keeping it alive** — perfect
for caches and back-references that shouldn't cause retention (Ch 11.4).

```python
import weakref
# Cache that lets values be GC'd when nobody else holds them:
cache = weakref.WeakValueDictionary()
cache[key] = obj            # obj stays only while referenced elsewhere

# Parent back-pointer that won't create a retaining cycle (Ch 4.5/11.5):
class Node:
    def __init__(self, parent=None):
        self._parent = weakref.ref(parent) if parent else None
    @property
    def parent(self): return self._parent() if self._parent else None
```

- **When.** Observer registries, parent pointers, object-keyed caches,
  memoization that must not leak.
- **Trade-off.** Values can vanish (must handle `None`); not for data you must
  keep. `WeakValueDictionary`/`WeakKeyDictionary`/`WeakSet` cover most needs.

## 15.5 Cache tuning — every cache needs a bound and a policy

The FastAPI case (Ch 14.10) in one rule: **an unbounded cache is a leak.** Bound
size *and* lifetime.

```python
from functools import lru_cache
@lru_cache(maxsize=10_000)          # bounded LRU; evicts oldest
def expensive(key): ...

from cachetools import TTLCache, LRUCache
cache = TTLCache(maxsize=5_000, ttl=300)   # size AND time bound
```

- **When.** Any in-process memoization/cache.
- **Trade-off.** `maxsize` too small → low hit rate; too large → memory. Measure
  hit ratio. For big/shared caches use **Redis** (out-of-process, its own
  eviction) so cache memory doesn't count against your pod.
- **Watch:** `lru_cache` on a **method** keys on `self` and can retain instances —
  a subtle leak; prefer module-level functions or `cachetools` with explicit keys.

## 15.6 Object pooling & buffer reuse — reduce churn

Reusing a buffer avoids repeated allocate/free churn (which drives fragmentation,
Ch 4.10/5.9) and GC pressure.

```python
# Reuse one NumPy buffer across iterations instead of allocating each loop:
buf = np.empty((1024, 1024), dtype=np.uint8)
for frame in stream:
    cv2.resize(frame, (1024, 1024), dst=buf)   # write into buf, no new alloc
    process(buf)

# Connection/thread pools bound resource count (and their memory):
pool = ThreadPoolExecutor(max_workers=8)       # not one thread per task
```

- **When.** Hot loops with same-shape allocations (image/video, numeric kernels);
  DB connections, threads, HTTP sessions.
- **Trade-off.** Manual lifecycle, aliasing bugs if you forget a buffer is shared.
  Big win for steady-state services.

## 15.7 Avoid unnecessary copies

Copies are the silent memory multiplier (Ch 5.3/14.3). Prefer **views, in-place
ops, and moves**.

```python
a[:] = a * 2                 # in-place-ish; a *= 2 is truly in-place
np.multiply(a, 2, out=a)     # explicit in-place, no temp
view = a[10:20]              # view, shares memory (Ch 5.3)
# AVOID: b = a.astype(np.float64) when a is already usable; big.copy() habitually
```

- **When.** NumPy/pandas transforms, passing large objects around.
- **Trade-off.** In-place mutates shared data — be sure no one else needs the
  original. Use `np.shares_memory(a, b)` to verify view vs. copy.

## 15.8 NumPy optimization

- **Right dtype** (Ch 5.3): `uint8`/`float32` instead of `int64`/`float64` when
  precision allows — often 2–8× smaller. `float16` for storage.
- **Views over copies** (§15.7); boolean/fancy indexing copies — do it once.
- **`out=` parameters**: `np.add(a, b, out=a)`, `np.dot(..., out=...)`.
- **mmap big arrays** you don't need fully resident: `np.load(f, mmap_mode="r")`
  (reclaimable page cache, Ch 5.3).
- **Avoid Python-level loops** over arrays (each element boxes a PyObject);
  vectorize.
- **Free explicitly** at chunk boundaries (`del arr`) so large mmap-backed buffers
  `munmap` and RSS drops (Ch 4.9).

## 15.9 pandas optimization

- **String columns → Arrow/category** (Ch 5.4/14.6):
  `df["c"] = df["c"].astype("string[pyarrow]")` or `"category"` for low
  cardinality — the #1 pandas memory win.
- **Downcast numerics:** `pd.to_numeric(s, downcast="integer"/"float")`.
- **Read smart:** `read_csv(usecols=..., dtype=..., chunksize=...,
  engine="pyarrow")`; don't load columns you won't use.
- **Drop intermediates / avoid chained copies**; `del` big frames; watch
  `merge`/`concat` doubling memory (Ch 5.4).
- **Measure with `df.memory_usage(deep=True)`** — always `deep`.
- **Consider Polars/DuckDB** for out-of-core: streaming, columnar, far lower peak
  for big analytics.

## 15.10 OpenCV / image optimization

- **Cap native threads to the CPU limit** (Ch 5.6/7.5): `cv2.setNumThreads(2)`
  and `OMP/OPENBLAS/MKL_NUM_THREADS`.
- **In-place & `dst=`** to reuse buffers (§15.6); avoid a fresh `Mat` per op.
- **Downscale early**, process small, keep `uint8`; don't hold original + every
  transform (Ch 14.1).
- **`close()`/release**: `VideoCapture.release()`, `Image.close()`; process pages
  in a generator, never accumulate.
- **Decompression-bomb guard**: validate dimensions before decoding;
  `Image.MAX_IMAGE_PIXELS` (Ch 14.2).

## 15.11 Worker recycling — the pragmatic RSS reset

For retention/fragmentation you can't fully eliminate (Ch 11.7/14.11), **restart
workers periodically** so RSS resets — the industry-standard production answer.

```bash
gunicorn app:app --workers 4 --max-requests 1000 --max-requests-jitter 100
uwsgi --max-requests 1000 --reload-on-rss 512      # also restart at RSS threshold
```
```python
# Celery: recycle a worker child after N tasks
app.conf.worker_max_tasks_per_child = 500
# and/or by memory:
app.conf.worker_max_memory_per_child = 512_000     # KB -> restart child at ~512MB
```

- **When.** Long-lived workers whose RSS ratchets up (fragmentation, glibc/pymalloc
  retention, unfixable third-party leaks).
- **Trade-off.** Restart cost (cold caches, dropped warm state); `--jitter` avoids
  thundering-herd restarts. It **masks** rather than fixes — pair with a real fix,
  but it's legitimate and reliable.

## 15.12 Subprocess isolation — guaranteed memory release

The only *guaranteed* way to return memory to the OS is **process exit** (Ch
4.9). Run big/risky/leaky work in a short-lived child so its RSS vanishes when it
finishes.

```python
from concurrent.futures import ProcessPoolExecutor
# Each task runs in a worker process; peak memory is bounded and released.
with ProcessPoolExecutor(max_workers=2, max_tasks_per_child=1) as ex:
    results = list(ex.map(heavy_pdf_render, files))   # Ch 14.2 pattern
```

- **When.** Memory-heavy transforms (PDF/OCR/ML), untrusted inputs
  (decompression bombs), third-party leaks you can't fix, big one-shot jobs.
- **Trade-off.** IPC/serialization cost, no shared state (use shared memory for
  big data, Ch 9), fork/spawn overhead. Blast-radius containment is a bonus.

## 15.13 Allocator & runtime tuning (code-free wins)

From Chapter 5 — often the fastest 20–40% RSS reduction with **zero code
changes**:

```dockerfile
ENV MALLOC_ARENA_MAX=2                                  # cap glibc arenas (Ch 5.9)
ENV LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so.2   # or tcmalloc (Ch 5.10)
ENV MALLOC_CONF=background_thread:true,dirty_decay_ms:1000  # jemalloc page return
ENV OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2   # native threads
```
```python
import ctypes; ctypes.CDLL("libc.so.6").malloc_trim(0)   # nudge glibc to return
# GC tuning (Ch 4.6): fewer collections, or freeze warm objects pre-fork
import gc; gc.freeze(); gc.set_threshold(50_000, 500, 500)
```

- **When.** Long-running data/ML services, many-core hosts, fork servers.
- **Trade-off.** Measure per workload — some trade RAM for CPU; jemalloc's decay
  knobs tune the balance.

## 15.14 Thread vs. process trade-offs (memory lens)

| | **Threads** | **Processes** |
|---|---|---|
| Memory | shared address space — cheap | separate — each pays base RSS |
| Isolation | none (a leak in one hurts all) | full (leak dies with the process) |
| GIL / CPU parallelism | no CPU parallelism (Ch 4.3) | true parallelism |
| Big read-only data | shared for free | duplicated unless shm/COW (Ch 6.8/9) |
| Memory release | never until process exits | **guaranteed on child exit** (Ch 4.9) |
| Best for | I/O-bound, shared caches | CPU-bound, isolation, leaky work |

- **Rule of thumb.** I/O-bound + shared state → threads/async (low memory). CPU-
  bound or needing guaranteed memory release/isolation → processes. For big
  read-only data across processes, use **shared memory / Arrow / NumPy** so you
  don't pay N× (Ch 6.8/9/14.9).

## 15.15 The optimization decision guide

```
   Memory too high. What's the shape/cause (Ch 11)?
        |
        +-- Materializing large collections?   -> generators / chunking (§15.1-2)
        +-- Millions of small objects?          -> __slots__ / columnar / NumPy (§15.3,15.8)
        +-- Unbounded cache/queue?              -> bound + evict / backpressure (§15.5, Ch14.7)
        +-- Retention via references?           -> weakref / unregister (§15.4)
        +-- Hidden copies (NumPy/pandas)?       -> views / in-place / dtype (§15.7-9)
        +-- Native thread-pool blowup?          -> cap *_NUM_THREADS (§15.10, Ch7.5)
        +-- Fragmentation / RSS won't drop?     -> jemalloc/ARENA_MAX + recycle (§15.11,15.13)
        +-- Big/risky one-shot work?            -> subprocess isolation (§15.12)
        +-- Duplicated data across workers?     -> share native buffer / shm (§15.14, Ch9)
```

---

## Key takeaways

- **The cheapest memory is memory you never allocate** — stream with generators
  and process in bounded chunks before reaching for anything fancier (§15.1–2).
- **Bound everything with unbounded growth**: caches (size + TTL), queues
  (backpressure), batches — an unbounded buffer is a leak (§15.5, Ch 14).
- **Shrink the objects**: `__slots__`/dataclass-slots for many instances, right
  dtypes + Arrow strings + views/in-place for NumPy/pandas (§15.3, 15.7–9).
- **Reset what you can't fix**: worker recycling for fragmentation/retention;
  subprocess isolation for guaranteed RSS release; allocator/thread tuning for
  code-free wins (§15.11–13).
- **Choose threads vs. processes by the memory lens**: shared+cheap vs.
  isolated+guaranteed-release; share big read-only data as native buffers, never
  as duplicated Python objects (§15.14).

## Practice exercises

1. Convert a `.readlines()`+list-comprehension pipeline to a generator; measure
   peak RSS before/after on a large file (expect a large drop).
2. Add `__slots__` (or `@dataclass(slots=True)`) to a class and compare total
   memory for 5M instances via `pympler.asizeof`.
3. Replace an unbounded dict cache with `TTLCache`; confirm the memory graph
   flips from climb to plateau (Ch 11.9).
4. Take a NumPy pipeline with `astype`/boolean-index copies and rewrite it with
   `out=`/views/small dtype; measure the peak-RSS reduction.

## Quiz questions

1. Why does switching a list comprehension to a generator expression cut peak
   memory, and what capability do you give up?
2. When does `__slots__` pay off, and what does it cost you?
3. Give a cache design that references objects without retaining them, and when
   you'd use it.
4. Name two ways to make a long-lived worker's RSS reset, and which one
   *guarantees* memory returns to the OS.
5. Why is capping `OMP_NUM_THREADS` a memory optimization, not just a CPU one?
6. You must share a 2 GiB read-only dataset across 16 workers. What do you do and
   why *not* just fork with a Python dict?
7. Which optimizations are "code-free" and typically yield 20–40% RSS reduction?

## Suggested experiments

- Build the §15.2 `chunks()` helper and sweep chunk sizes (1k → 500k) on a
  DataFrame job; plot peak RSS vs. throughput to find the knee.
- Compare `ProcessPoolExecutor(max_tasks_per_child=1)` vs. an in-process loop for
  a memory-heavy task; confirm the subprocess version's RSS returns to baseline
  between tasks (Ch 4.9).
- Toggle jemalloc + `MALLOC_ARENA_MAX=2` on a long-running allocation loop and
  record steady-state RSS vs. the glibc default (§15.13).

---

*Next up: **Chapter 16 — Linux Commands Cheat Sheet**, a fast reference for
top/htop/free/vmstat/iostat/pidstat/ps/smem/pmap/lsof/`/proc`/strace/perf/sar/
slabtop — every flag and example you need at the terminal.*

[← Chapter 14](14_case_studies.md) · [Back to index](README.md) · [Chapter 16 →](16_linux_cheatsheet.md)
