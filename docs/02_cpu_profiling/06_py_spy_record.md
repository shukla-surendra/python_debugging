# `py-spy record` / `top` - CPU profiling with zero instrumentation

`py-spy` (introduced for stack dumps in
[`01_stack_dumps/06_py_spy_dump.md`](../01_stack_dumps/06_py_spy_dump.md))
is also a full sampling CPU profiler. Because it samples from **outside**
the process via `ptrace`/process memory inspection, it adds almost no
overhead and works on processes you didn't start under a profiler.

All commands below were verified to work in this repo's sandbox using
**spawn mode** (`py-spy record -- <command>`), which avoids the `ptrace`
permission issues described in module 1 because `py-spy` becomes the
parent of the target process.

## 1. Flamegraph (`record`, default format)

```bash
cd docs/02_cpu_profiling
py-spy record -o profile.svg -- ../../.venv/bin/python ../../workloads/cpu_bound.py --seconds 3
```

```
py-spy> Sampling process 100 times a second. Press Control-C to exit.
py-spy> Stopped sampling because process exited
py-spy> Wrote flamegraph data to 'profile.svg'. Samples: 317 Errors: 0
```

Open `profile.svg` in a browser. Reading a flamegraph:

- **x-axis** = proportion of samples (NOT time order - it's sorted
  alphabetically by default, so don't read left-to-right as a timeline)
- **y-axis** = stack depth - the bottom row is `<module>`, each row above
  is a function called by the one below
- **width of a box** = fraction of samples where that function was on the
  stack - wide boxes are where the time goes

For `cpu_bound.py` you should see three towers above `one_round`:
`sum_of_squares`, `string_churn`, and a tall narrow recursive tower for
`fibonacci`. The widest one is your best optimization target.

## 2. Speedscope format (interactive, better for deep stacks)

```bash
py-spy record -f speedscope -o profile.speedscope.json -- \
    ../../.venv/bin/python ../../workloads/cpu_bound.py --seconds 2
```

```
py-spy> Wrote speedscope file to 'profile.speedscope.json'. Samples: 200 Errors: 0
py-spy> Visit https://www.speedscope.app/ to view
```

Upload the JSON to <https://www.speedscope.app/> (everything runs
client-side in your browser, nothing is uploaded to a server). Speedscope's
"left heavy" view groups identical call paths regardless of order - much
easier than a raw flamegraph for recursive code like `fibonacci`.

## 3. `py-spy top` - live, continuously-updating view

```bash
# Terminal 1: start a long-running workload
../../.venv/bin/python ../../workloads/cpu_bound.py --seconds 60

# Terminal 2 (needs ptrace permissions - see 01_stack_dumps/06_py_spy_dump.md)
sudo py-spy top --pid $(pgrep -f cpu_bound.py)
```

This shows a `top`-style table refreshed ~once/second:

```
Collecting samples from 'python ../../workloads/cpu_bound.py --seconds 60' (python v3.14.4)
Total Samples 1500
GIL: 100.00%, Active: 100.00%, Threads: 1

  %Own   %Total  OwnTime  TotalTime  Function (filename)
 52.30%  52.30%   0.780s     0.780s  string_churn (workloads/cpu_bound.py)
 39.10%  39.10%   0.590s     0.590s  sum_of_squares (workloads/cpu_bound.py)
  8.10%   8.60%   0.120s     0.130s  fibonacci (workloads/cpu_bound.py)
```

`%Own` = time where this function itself was executing (like cProfile's
tottime). `%Total` = time where this function was anywhere on the stack
(like cumtime). The `GIL:` line is important for multi-threaded programs -
if it's low, your threads are fighting over the GIL rather than computing.

## 4. Profiling subprocesses / multiprocessing

```bash
py-spy record -s -o profile.svg -- ../../.venv/bin/python my_multiprocess_app.py
```

`-s`/`--subprocesses` makes `py-spy` also sample any child processes - vital
for `multiprocessing`-based code where the actual CPU work happens in
worker processes, not the parent. See
[`04_concurrency_debugging/`](../04_concurrency_debugging/README.md).

## Why use this over `pyinstrument`?

- `pyinstrument` requires importing it and wrapping your code; `py-spy`
  needs **nothing** - useful for profiling third-party code, or processes
  already running in production.
- `py-spy` can profile **multi-process** and **multi-threaded** programs as
  a single combined view.
- `pyinstrument`'s sampler runs *inside* the process and is aware of
  asyncio's event loop, so for async code it can be more accurate about
  which coroutine "owns" await time. For CPU-bound sync code, both are
  excellent - pick whichever fits your workflow (in-process API vs.
  attach-to-anything).
