# Python Debugging Dojo

A hands-on repo for becoming fluent in three overlapping skills:

1. **Stack dumps** - "what is my process doing *right now*?"
2. **CPU profiling** - "where does my process spend its *time*?"
3. **Memory profiling** - "where does my process spend its *RAM*, and why
   doesn't it go back down?"

Every topic has a `README.md` with concepts + a tool comparison table, plus
small runnable scripts you execute yourself. There are no "fill in the
blank" exercises - you run real tools against real (small, deliberately
flawed) programs in `workloads/` and read real output.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Everything here was tested on **Python 3.14, Linux x86_64**. `py-spy` and
`memray` need to read another process's memory, so on some systems you'll
need `sudo` or `ptrace_scope` adjustments - each section calls this out
where relevant.

## The "victim" programs (`workloads/`)

All demos point at one of these small, self-contained scripts so you can
compare tools apples-to-apples:

| File | What it does | Good for |
|---|---|---|
| `cpu_bound.py` | Tight numeric loop + string churn + recursive fibonacci | CPU profilers |
| `memory_leak.py` | Unbounded cache, reference cycles, closures capturing buffers | Memory profilers, `gc` |
| `io_bound_sleep.py` | Multiple threads doing `time.sleep` (stand-in for I/O) | Stack dumps, concurrency |
| `deadlock.py` | Two threads acquire two locks in opposite order | Stack dumps, hang diagnosis |
| `recursion_blowup.py` | Deep / unbounded recursion | Stack traces, `RecursionError` |

## Learning path

Work through these roughly in order. Each module is independent enough to
jump around, but stack dumps first will make the profiling sections click
faster.

### 1. [`docs/01_stack_dumps/`](docs/01_stack_dumps/README.md) - "what is it doing right now?"

| Tool | Type | Needs source change? | Works on a *hung* process? |
|---|---|---|---|
| `traceback` | stdlib | yes (in except block) | no |
| `faulthandler` | stdlib | yes (one-time setup) | yes (via `SIGUSR1` / timeout) |
| `signal` + custom handler | stdlib | yes | yes |
| `threading.enumerate()` + `sys._current_frames()` | stdlib | yes | yes |
| `pdb.post_mortem` / `pdb.set_trace` | stdlib | yes | n/a (interactive) |
| `py-spy dump` / `py-spy top` | external (Rust binary) | **no** | **yes** |
| `gdb` + `python3-dbg` | external | **no** | **yes** (even native deadlocks) |

### 2. [`docs/02_cpu_profiling/`](docs/02_cpu_profiling/README.md) - "where does the time go?"

| Tool | Technique | Overhead | Granularity | Needs source change? |
|---|---|---|---|---|
| `cProfile` / `pstats` | deterministic (every call) | medium-high | per-function | no |
| `timeit` | microbenchmark | n/a | statement/expression | no |
| `line_profiler` | deterministic | high | per-line | yes (`@profile`) |
| `pyinstrument` | statistical sampling | low | per-call (tree) | no |
| `py-spy record` / `top` | statistical sampling (out-of-process) | ~zero | per-call (flamegraph) | **no** |
| `scalene` | statistical + instrumented | low-medium | per-line, CPU/GPU/memory | no |

### 3. [`docs/03_memory_profiling/`](docs/03_memory_profiling/README.md) - "where does the RAM go?"

| Tool | Tracks | Granularity | Live process? |
|---|---|---|---|
| `sys.getsizeof` | shallow size of one object | object | yes |
| `tracemalloc` | Python allocations, with source location | line / traceback | yes (stdlib) |
| `memory_profiler` | process RSS over time | per-line | yes |
| `objgraph` | object counts & reference chains | object graph | yes |
| `pympler` | heap composition, growth between snapshots | class / object | yes |
| `gc` | reference cycles, collection stats | object graph | yes |
| `memray` | Python **and** native (C extension) allocations | line / call stack, flamegraph | attach or run-under |

### 4. [`docs/04_concurrency_debugging/`](docs/04_concurrency_debugging/README.md)

Putting stack dumps + profiling together for threads, `asyncio`, and
`multiprocessing` - including diagnosing the deadlock in `workloads/deadlock.py`.

### 5. [`docs/05_production_playbook/`](docs/05_production_playbook/README.md)

How to wire some of this into a long-running service *ahead of time* so
that when something goes wrong in production, you can diagnose it without
restarting the process.

### 6. [`docs/06_observability/`](docs/06_observability/README.md)

The layers *around* your code: OS-level introspection below it
(`strace`/`lsof`/`/proc`), lightweight tracing and coverage alongside it
(`PySnooper`, `snoop`, `hunter`, `icecream`, `rich`, `coverage.py`), and
production observability above it - error tracking (**Sentry**) and
distributed tracing (**OpenTelemetry**) for problems that span a whole fleet
or request path.

## Quick reference

See [`CHEATSHEET.md`](CHEATSHEET.md) for a single page of commands.
