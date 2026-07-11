# `memray` - whole-process native memory profiler

Every other tool in this module tracks Python-level allocations
(`tracemalloc`), process RSS sampled from outside (`memory_profiler`), or the
current heap composition (`objgraph`/`pympler`). **`memray`** is different:
it hooks `malloc`/`free`/`mmap` (and Python's allocator) directly, so it sees
**every allocation, including inside C extensions** (numpy, pandas, PIL,
...), with full Python+native stack traces - at much lower overhead than
`tracemalloc`'s "record everything" approach.

It's the closest thing to `valgrind --tool=massif` for Python, but
Python-aware.

## 1. Record a run

```bash
cd docs/03_memory_profiling
python -m memray run -o memray_output.bin ../../workloads/memory_leak.py
```

This runs the target script to completion under memray's allocator hooks and
writes a binary capture file (`memray_output.bin`). Add `-f` to overwrite an
existing file, or `--native` to also resolve native (C-level) stack frames
for compiled extensions.

## 2. Summary - allocations grouped by call stack

```bash
python -m memray summary memray_output.bin
```

Verified output (columns trimmed for width) for `workloads/memory_leak.py`:

```
Location                                               <Total Memory>  Total Memory %      Own Memory  Own Memory %  Allocation Count
<module> at workloads/memory_leak.py                        35.065MB           99.96%       1.760kB         0.01%              1457
leak_via_reference_cycle at workloads/memory_leak.py        20.002MB           57.02%       1.600kB         0.00%               401
__init__ at workloads/memory_leak.py                        20.000MB           57.01%      20.000MB        57.01%               400
leak_via_global_cache at workloads/memory_leak.py           10.059MB           28.67%      10.059MB        28.67%              1001
leak_via_closure at workloads/memory_leak.py                 5.000MB           14.25%       5.000MB        14.25%                50
```

Reading this top to bottom:

- **`<Total Memory>` / `<Total Memory %>`** is the sum of everything
  allocated by that frame *and everything it called* (cumulative, like
  `cProfile`'s `cumtime`).
- **`Own Memory` / `Own Memory %`** is memory allocated *directly* in that
  frame - the equivalent of `tottime`.
- `__init__` (Node's `__init__`, allocating the 50KB `payload` bytearray) has
  **57% own memory across 400 allocations** - exactly `200 pairs * 2 nodes *
  50_000 bytes` = 20MB, confirming `leak_via_reference_cycle` is the single
  biggest contributor in this run.
- `leak_via_global_cache` and `leak_via_closure` show up as their own
  "own memory" entries (10MB and 5MB) because their allocations
  (`b"x" * item_size` and `bytearray(100_000)`) happen directly in those
  functions, not in a helper.

This one table answers "which function's allocations dominate peak memory?"
without writing a single line of profiling code into the target script.

## 3. Flamegraph - visualize where memory comes from

```bash
python -m memray flamegraph memray_output.bin
# writes memray-flamegraph-memray_output.html - open it in a browser
```

The flamegraph shows the **call stack at the moment of peak memory usage**,
with each frame's box width proportional to bytes allocated under it. The
three `leak_via_*` functions appear as three large, separate towers under
`<module>` - visually confirming they're independent allocation sites (no
shared helper is the culprit).

Useful flags:

```bash
memray flamegraph --leaks ...   # show only memory that was NEVER freed
                                 # (leaked allocations), not peak usage
memray flamegraph --temporary-allocation-threshold N ...
                                 # highlight allocations freed within N
                                 # allocations of being made (churn)
```

`--leaks` is the most directly useful flag for this repo's workload: run it
against `memory_leak.py` and only `leak_via_global_cache`'s allocations
survive to the end (everything else gets freed or collected before exit),
making it immediately obvious which function is the *actual* leak versus
which ones just allocate a lot transiently.

## 4. Other reporters

```bash
memray table memray_output.bin     # like flamegraph, but a sortable HTML table
memray tree memray_output.bin      # terminal call-tree, like a text flamegraph
memray stats memray_output.bin     # high-level numbers: total/peak memory,
                                    # allocation size histogram, allocator
                                    # type counts (malloc/calloc/realloc/mmap)
```

Verified `stats` output for this workload:

```
Total allocations:       2750
Total memory allocated:  46.382MB
Peak memory usage:       35.079MB

Allocator type distribution:
 MALLOC: 2572
 CALLOC: 127
 REALLOC: 51
```

## 5. Live mode - attach to a running process

```bash
memray run --live python ../../workloads/memory_leak.py     # launch + attach live
memray attach <PID>                                       # attach to an already-running process (Linux)
```

`live` opens a `top`-like terminal UI that updates as the process runs -
useful for "watch this long-running job's memory in real time" without
waiting for it to exit and generate a report file.

## memray vs. everything else in this module

| Question | Best tool |
|---|---|
| "What's the deep size of this one object?" | `pympler.asizeof` (06) |
| "What changed between snapshot A and B?" | `tracemalloc.compare_to` (03) |
| "Which line has the worst per-line RSS delta?" | `memory_profiler` (04) |
| "Why is this object still alive?" | `objgraph.find_backref_chain` (05) |
| "What's the FULL allocation picture, including C extensions, with the lowest overhead?" | `memray` |
| "I need a flamegraph of memory like I'd get for CPU" | `memray flamegraph` |

`memray` is Linux-only and does not support `--native` stack resolution on
all platforms - for quick cross-platform checks, `tracemalloc` (stdlib,
works everywhere) is still the first thing to reach for.
