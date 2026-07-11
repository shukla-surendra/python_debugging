# `austin` - a tiny, dependency-free frame-stack sampler

`austin` is a sampling profiler in the same family as `py-spy`: it reads a
running Python process's memory from **outside** and reconstructs the call
stack, so it needs **no code changes** and adds near-zero overhead. Its
distinguishing traits are that it's a single, tiny C binary with **zero
runtime dependencies** (easy to drop onto a locked-down host or into a
container), and it can sample **wall-clock, CPU, and memory** on Linux,
macOS, and Windows.

Think of it as the minimalist cousin of `py-spy` - reach for it when you
want the lightest-possible always-available sampler, or when you like its
TUI / output format.

## Install (two parts)

The `austin` **binary** is a separate native install; `austin-python` (in
this repo's `requirements.txt`) provides the Python tooling around it -
`austin-tui`, format converters, and a library API.

```bash
# The native binary (pick your platform):
#   Debian/Ubuntu:  apt install austin        (or download a release binary)
#   macOS:          brew install austin
#   Windows:        choco install austin
pip install austin-python   # austin-tui, austin2speedscope, etc. (already in requirements.txt)
austin --version            # confirm the binary is on PATH
```

Like every out-of-process sampler here, attaching to a process you didn't
launch needs `ptrace` permission - `sudo` or a relaxed `ptrace_scope` (see
[`../01_stack_dumps/06_py_spy_dump.md`](../01_stack_dumps/06_py_spy_dump.md)).

## 1. Sample a program (spawn mode - no special permissions)

```bash
austin -i 1ms -o profile.austin ../../.venv/bin/python ../../workloads/cpu_bound.py --seconds 3
#   -i 1ms   sample every 1 millisecond
#   -o FILE  write samples (collapsed-stack format) to FILE
```

`austin` writes **collapsed stacks** (the same format Brendan Gregg's
FlameGraph tools consume), so you can turn it straight into a flamegraph or a
speedscope profile:

```bash
# Speedscope (interactive, client-side at https://www.speedscope.app/):
austin2speedscope profile.austin profile.speedscope.json

# Or a classic SVG flamegraph, if you have the FlameGraph scripts:
austin ../../.venv/bin/python ../../workloads/cpu_bound.py --seconds 3 | flamegraph.pl > profile.svg
```

For `cpu_bound.py` you'll again see the three towers (`sum_of_squares`,
`string_churn`, and the recursive `fibonacci`) - the same picture `py-spy`
gives, from a different sampler.

## 2. Attach to a running process

```bash
sudo austin -p <PID>                 # attach and stream samples
sudo austin -p <PID> -C              # also follow child processes
```

## 3. `austin-tui` - a live top-like view

```bash
austin-tui ../../.venv/bin/python ../../workloads/cpu_bound.py --seconds 30
sudo austin-tui -p <PID>
```

A full-screen, continuously updating table of where time is going per
function and per thread - the analogue of `py-spy top`, with a slightly
richer TUI.

## Useful flags

| Flag | Does |
|---|---|
| `-i <interval>` | Sampling interval (e.g. `-i 1ms`); smaller = finer, more overhead |
| `-p <PID>` | Attach to a running process |
| `-C` / `--children` | Also sample child processes (multiprocessing) |
| `-s` / `--sleepless` | Ignore idle/sleeping time - CPU time only |
| `-m` / `--memory` | Sample memory allocations instead of/alongside time |
| `-o <file>` | Write samples to a file instead of stdout |
| `-t <ms>` | Timeout for attaching |

`austinp` (shipped alongside on Linux) is a variant that can also unwind
**native** stacks, similar in spirit to `py-spy --native` / `pystack
--native`.

## `austin` vs. `py-spy`

They overlap heavily - both are low-overhead, out-of-process, cross-platform
samplers. Differences that might tip you one way:

- **`austin`** is a tiny zero-dependency binary and can sample **memory** as
  well as time; its collapsed-stack output plugs into the classic FlameGraph
  toolchain directly.
- **`py-spy`** has the more polished built-in `record` (SVG/speedscope) and
  `dump` (one-shot stack) commands and is the more widely deployed default in
  this repo (see [`06_py_spy_record.md`](06_py_spy_record.md)).

If you already have `py-spy`, you rarely *need* `austin` too - but it's a
great pick when you want the smallest possible footprint or its memory-
sampling mode. For a **timeline** rather than an aggregate, see VizTracer in
[`../04_concurrency_debugging/05_viztracer_timeline.md`](../04_concurrency_debugging/05_viztracer_timeline.md).

## When to reach for `austin`

- You want a **minimal, dependency-free** sampler to drop onto a host or into
  a slim container.
- You want low-overhead **memory** sampling of a live process.
- You like the `austin-tui` live view or the collapsed-stack → FlameGraph
  workflow.
