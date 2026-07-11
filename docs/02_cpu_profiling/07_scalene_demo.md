# `scalene` - CPU + GPU + memory, per line, Python vs. native vs. system

`scalene` is the "all-in-one" profiler: a single run gives you, **per
line**:

- time spent in **Python** code
- time spent in **native** code (C extensions, including numpy/pytorch
  internals)
- time spent in **system calls** (I/O, sleeping, waiting)
- memory allocated/freed, and which lines are responsible for growth
- (if a supported GPU is present) GPU time and memory

This makes it the best "first tool to run" when you're not sure if a
slowdown is CPU-bound, I/O-bound, or memory-bound.

## Basic usage

Scalene 2.x has a `run`/`view` split: `run` profiles and saves JSON,
`view` displays it (in browser or terminal).

```bash
cd docs/02_cpu_profiling

# Profile (CPU + memory). Use `---` to pass args to the target script.
scalene run -o scalene-profile.json ../../workloads/cpu_bound.py --- --rounds 5

# View in the terminal (no browser needed - good for SSH sessions / CI logs)
scalene view --cli
```

Verified output for `cpu_bound.py` (columns trimmed for width):

```
 /home/.../../workloads/cpu_bound.py: % of time = 100.00% (128.752ms) out of 128.752ms.
        ╷       ╷       ╷       ╷       ╷
       Time   │ ────── │ ────── │ Await │
  Line │Python│ native │ system │   %   │ Line contents
╺━━━━━━┿━━━━━━┿━━━━━━━━┿━━━━━━━━┿━━━━━━━┿━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   26  │  9%  │   40%  │   1%   │       │     for i in range(n):
   27  │  9%  │   40%  │   1%   │       │         total += i * i
```

(Lines 26-27 are inside `sum_of_squares` - the `for i in range(n): total +=
i * i` loop. Note how scalene splits "Python" time from "native" time even
for a pure-Python loop - the "native" portion here is CPython's own C-level
bytecode interpreter loop / object allocation, which scalene attributes
separately from interpreted-bytecode dispatch overhead.)

```bash
# Or open the full interactive report in a browser:
scalene view
```

## Memory profiling with scalene

Drop `--cpu-only` (it's the default to also collect memory) and point it at
the memory-leak workload:

```bash
scalene run -o leak-profile.json ../../workloads/memory_leak.py
scalene view --cli
```

Scalene will annotate `leak_via_global_cache`'s loop with the memory growth
per line - directly showing you which line is responsible for the bulk of
allocations, without any `tracemalloc` setup. See
[`03_memory_profiling/`](../03_memory_profiling/README.md) for
memory-focused tools and more depth on this workload.

## Useful flags

```bash
scalene run --cpu-only ...        # skip memory/GPU tracking - lower overhead
scalene run --profile-all ...     # also show time spent in library code,
                                   # not just your project's files
scalene run --html -o report.html ...   # save a static HTML report
scalene run --reduced-profile ... # only show lines with non-zero activity
```

## scalene vs. everything else in this module

| Question | Best tool |
|---|---|
| "Which function is the bottleneck?" | `pyinstrument` or `py-spy record` |
| "Which *line* is the bottleneck?" | `line_profiler` (CPU only) or `scalene` (CPU **and** memory) |
| "Is this slowdown CPU, I/O, or memory?" | `scalene` - it's the only tool here that separates all three automatically |
| "I need to profile a process I can't restart" | `py-spy` |
