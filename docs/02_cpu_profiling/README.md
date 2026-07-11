# 2. CPU Profiling - "Where does the time go?"

A CPU profiler answers: *across a run of my program, how much time was
spent in each function / line, and who called whom?*

There are two fundamentally different approaches:

- **Deterministic (tracing) profilers** instrument every function call and
  return (`cProfile`, `line_profiler`). They're exact, but the
  instrumentation itself adds overhead - sometimes 2-10x slowdown,
  which can hide effects that only show up at full speed (cache behavior,
  GIL contention, JIT-like optimizations).
- **Statistical (sampling) profilers** interrupt the program N times per
  second and record the current stack (`py-spy`, `pyinstrument`, `scalene`
  in CPU mode). Overhead is tiny (often <5%), at the cost of statistical
  noise on rarely-sampled fast functions.

Rule of thumb: **start with a sampling profiler** (`pyinstrument` or
`py-spy`) to find the hot area, then switch to `line_profiler` for a
deterministic, line-by-line breakdown of just that area.

## Tool comparison

| Tool | Type | Granularity | Overhead | Setup |
|---|---|---|---|---|
| `cProfile` + `pstats` | deterministic | per-function | medium | stdlib, zero setup |
| `timeit` | deterministic (wall-clock) | statement/expression | n/a | stdlib, zero setup |
| `line_profiler` | deterministic | **per-line** | high | pick functions to instrument |
| `pyinstrument` | statistical | per-call (call tree) | low | zero setup |
| `py-spy record`/`top` | statistical, **out-of-process** | per-call (flamegraph) | ~zero | none - works on running processes |
| `austin` | statistical, **out-of-process** | per-call (also memory mode) | ~zero | tiny zero-dependency binary + `pip install austin-python` |
| `scalene` | hybrid (statistical CPU + instrumented memory) | **per-line**, splits Python/native/system time | low-medium | zero setup |

All the tools above **aggregate** time by function/line. For a **timeline**
(the order things ran in, and where the gaps are - crucial for async and
concurrency), see VizTracer in
[`../04_concurrency_debugging/05_viztracer_timeline.md`](../04_concurrency_debugging/05_viztracer_timeline.md).

## Files in this module

| File | Demonstrates |
|---|---|
| `01_cprofile_basics.py` | `cProfile.Profile`, `pstats.Stats`, sorting, `print_callers`/`print_callees` |
| `02_save_and_load_profile.py` | Saving `.prof` files, reloading with `pstats`, `snakeviz`/`gprof2dot` for visualization |
| `03_timeit_microbenchmarks.py` | `timeit.timeit`/`Timer`, comparing implementations, common pitfalls |
| `04_line_profiler_demo.py` | `line_profiler.LineProfiler` - per-line timing |
| `05_pyinstrument_demo.py` | `pyinstrument.Profiler` - low-overhead call-tree profiling, HTML report |
| `06_py_spy_record.md` | `py-spy record`/`top` - flamegraphs for any running process |
| `07_scalene_demo.md` | `scalene` CLI - per-line CPU/native/system split |
| `08_austin.md` | `austin` - minimal zero-dependency out-of-process sampler (time + memory), `austin-tui` |

## Run order

```bash
cd docs/02_cpu_profiling
python 01_cprofile_basics.py
python 02_save_and_load_profile.py
python 03_timeit_microbenchmarks.py
python 04_line_profiler_demo.py
python 05_pyinstrument_demo.py
```

Then read `06_py_spy_record.md`, `07_scalene_demo.md`, and `08_austin.md`
and run the commands shown there.

## Decision guide

```
"My code is slow, where do I start?"
├── Don't know which function -> pyinstrument or py-spy record (low overhead, call tree / flamegraph)
├── Know the function, want line detail -> line_profiler
├── Comparing two small implementations -> timeit
├── Need to profile a process you can't restart -> py-spy top / py-spy record --pid (or austin -p)
├── Want the ORDER things ran in / async event-loop gaps -> VizTracer (module 4)
└── Suspect it's secretly a MEMORY problem (swapping, GC pressure) -> scalene (shows CPU + memory together)
```
