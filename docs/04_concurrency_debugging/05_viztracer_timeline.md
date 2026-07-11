# VizTracer - a timeline view of concurrency

Every profiler in module 2 **aggregates**: `cProfile` and `py-spy` tell you
*"function X used 40% of the time"* but throw away *when* things ran and in
*what order*. For concurrency bugs that's exactly the information you need.
"Why did this task stall for 200ms?" and "which coroutine was hogging the
event loop?" are questions about **ordering and gaps on a timeline**, not
about totals.

VizTracer records that timeline. It logs every function entry/exit with
timestamps (low-overhead, implemented in C) and renders it as a **flame
timeline** you explore in the Perfetto UI - the same visualization Chrome
uses. It is the missing *visual* tool for this module.

## Install

```bash
pip install viztracer
```

## 1. Trace a script and open the timeline

```bash
viztracer ../workloads/io_bound_sleep.py     # writes result.json
vizviewer result.json                        # opens the Perfetto UI in a browser
# or in one step:
viztracer --open ../workloads/io_bound_sleep.py
```

In the viewer, the **x-axis is real time** and each row is a thread (or, for
async, the event loop). You read it left-to-right as an actual timeline:

- **Wide bars** = a call that took a long time.
- **Gaps** = the thread/task was blocked or waiting - the interesting part.
- **Stacked bars** = nested calls (caller above callee).

For `io_bound_sleep.py` you'll see each worker thread's `time.sleep` as a
wide idle bar, with the threads overlapping in wall-clock time - a picture of
"these ran concurrently, mostly waiting" that a flat profile can't show.

## 2. Trace just a region of your own code

Don't trace the whole program - wrap the suspect region:

```python
from viztracer import VizTracer

with VizTracer(output_file="result.json"):
    handle_request(req)      # only this is traced
```

Or start/stop manually (`tracer.start()` / `tracer.stop()` /
`tracer.save()`) around the code you care about.

## 3. asyncio - VizTracer's strongest use case

`asyncio` is single-threaded cooperative concurrency: one coroutine runs
until it hits an `await` that yields. When "one slow request delays all
requests" (the classic event-loop stall from
[`02_asyncio_debug_mode.py`](02_asyncio_debug_mode.py)), VizTracer shows you
*exactly* which coroutine held the loop and for how long.

```bash
viztracer --log_async -o result.json my_async_app.py
```

`--log_async` labels tasks so you can follow each coroutine across its
`await` suspensions on the timeline. A single wide bar with everything else
stalled behind it **is** your blocking call - the synchronous work that
should have been `await`ed or pushed to a thread/executor.

Handy flags:

| Flag | Does |
|---|---|
| `--log_async` | Track and label `asyncio` tasks across awaits |
| `--log_func_args` | Record function arguments (see *which* input was slow) |
| `--log_multiprocess` / `-` | Trace across `multiprocessing` children |
| `--max_stack_depth N` | Cap depth to shrink huge traces |
| `--include_files A B` | Only trace these paths (drop stdlib/library noise) |
| `--ignore_c_function` | Skip C calls to reduce volume |
| `-o result.json` | Output file (`.json`, or `.html` for a self-contained report) |

## 4. multiprocessing

Because each process has its own tracer state (the recurring theme of this
module), trace children explicitly:

```bash
viztracer --log_multiprocess -o result.json ../workloads/deadlock.py
```

You then get one combined timeline across the parent and its workers -
letting you see, for instance, that two processes' work never overlaps
because they're serialized on a shared lock.

## VizTracer vs. the aggregating profilers

| Question | Best tool |
|---|---|
| "Where does total time go?" (one busy function) | `cProfile` / `py-spy` (module 2) |
| "In what **order** did things run, and where are the **gaps**?" | **VizTracer** |
| "Which coroutine stalled the event loop, and when?" | **VizTracer** (`--log_async`) |
| "Attach to an already-running prod process, no code" | `py-spy` (module 2) - VizTracer traces from the start |

VizTracer's overhead is higher than sampling (`py-spy`) because it records
**every** call, not a sample - so scope it to a region or a short run rather
than leaving it on a busy production service. For "attach to whatever's
running in prod", stay with `py-spy`; for "understand the choreography of my
concurrent code in dev/staging", VizTracer is the clearest window you'll get.

## When to reach for VizTracer

- A concurrency bug that's about **timing and ordering**, not totals.
- An `asyncio` event-loop stall you need to *see*.
- You want to understand how threads/tasks/processes **interleave** in
  wall-clock time - the one thing flat profiles discard.
