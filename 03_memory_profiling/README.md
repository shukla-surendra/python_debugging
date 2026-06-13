# 3. Memory Profiling - "Where does the RAM go, and why doesn't it come back?"

Memory problems come in a few flavors, and different tools suit each:

1. **"My process uses more RAM than I expect, right now."** -> need a
   snapshot of what's currently allocated, broken down by type/location.
   (`tracemalloc`, `pympler`, `objgraph`)
2. **"My process's RAM grows over time and never shrinks."** -> need to
   compare two snapshots and find what *grew*. (`tracemalloc` snapshot
   diff, `pympler.tracker.SummaryTracker`, `objgraph.growth`)
3. **"Something is keeping an object alive that should be dead."** -> need
   to find **reference chains** - who's pointing at this object?
   (`objgraph.find_backref_chain`, `gc`)
4. **"The leak might be in a C extension (numpy, PIL, etc.), not Python."**
   -> need an allocator-level profiler. (`memray`)
5. **"How big IS this one object, including everything it references?"**
   -> (`sys.getsizeof` for shallow, `pympler.asizeof` for deep)

## Concepts

- **RSS (Resident Set Size)**: actual physical RAM used by the process -
  what `top`/`ps`/`memory_profiler` report. Includes the Python heap, the
  interpreter itself, loaded `.so` libraries, etc.
- **Python heap**: memory `tracemalloc`/`pympler`/`objgraph` look at -
  objects allocated via CPython's allocator (`PyObject_Malloc`). A subset
  of RSS.
- **Reference counting vs. cyclic GC**: CPython frees an object the instant
  its refcount hits zero. Objects in **reference cycles** (A points to B,
  B points to A) never hit zero on their own - the generational cyclic
  garbage collector (`gc` module) finds and frees these periodically.
  `workloads/memory_leak.py`'s `leak_via_reference_cycle` demonstrates this.
- **"Leak" in Python usually means "still reachable, shouldn't be"** - not
  a classic C-style leak (unreachable, unfreeable memory). The fix is
  almost always "drop the reference" (bound caches, clear closures, etc.),
  which is why **reference-chain tools** (`objgraph`) are so important.

## Tool comparison

| Tool | What it shows | Snapshot diff? | Tracks native (C) allocations? |
|---|---|---|---|
| `sys.getsizeof` | shallow size of ONE object | no | no |
| `tracemalloc` | Python allocations + source location/traceback | **yes** (built-in) | no |
| `memory_profiler` | process RSS per line, over time | no (time series) | yes (it's just RSS) |
| `objgraph` | object counts, type histograms, **reference chains** | yes (`growth()`) | no |
| `pympler` | heap composition by class/type, deep sizes | **yes** (`SummaryTracker`) | no |
| `gc` | cycle collection stats, unreachable objects | no | no |
| `memray` | every allocation (Python AND native), with full stack | yes (`memray stats`/`transform`) | **yes** |

## Files in this module

| File | Demonstrates |
|---|---|
| `01_sys_getsizeof.py` | `sys.getsizeof` vs. deep size, why containers lie |
| `02_tracemalloc_basics.py` | `tracemalloc.start()`, `take_snapshot()`, top allocations |
| `03_tracemalloc_snapshot_diff.py` | Diffing snapshots to find growth, tracking a leak over iterations |
| `04_memory_profiler_demo.py` | `memory_profiler` - per-line RSS, `@profile`, `memory_usage()` |
| `05_objgraph_demo.py` | Object counts, `growth()`, `find_backref_chain` - "what's holding this alive?" |
| `06_pympler_demo.py` | `SummaryTracker`, `asizeof`, class-level breakdowns |
| `07_gc_module_demo.py` | Reference cycles, `gc.collect()`, `gc.get_referrers`, debugging flags |
| `08_memray_demo.md` | `memray run` / `flamegraph` / `summary` - native + Python allocator profiling |

## Run order

```bash
cd 03_memory_profiling
python 01_sys_getsizeof.py
python 02_tracemalloc_basics.py
python 03_tracemalloc_snapshot_diff.py
python 04_memory_profiler_demo.py
python 05_objgraph_demo.py
python 06_pympler_demo.py
python 07_gc_module_demo.py
```

Then read `08_memray_demo.md` and run the commands shown there.

## Decision guide

```
"Where is my memory going?"
├── One-off snapshot of "what's allocated right now, by source line"
│     -> tracemalloc.take_snapshot()
├── "It grows over time, what's growing?"
│     -> tracemalloc snapshot diff, OR pympler.tracker.SummaryTracker, OR objgraph.growth()
├── "Something specific (a Node, a DataFrame...) isn't being freed - WHY?"
│     -> objgraph.find_backref_chain() / objgraph.show_backrefs()
├── "Is the cyclic GC even the issue?"
│     -> gc.collect() + gc.garbage / gc.get_referrers()
├── "RSS keeps climbing but tracemalloc shows nothing growing"
│     -> probably a NATIVE (C extension) leak -> memray
└── "How much RAM does just THIS variable use?"
      -> sys.getsizeof() (shallow) / pympler.asizeof.asizeof() (deep)
```
