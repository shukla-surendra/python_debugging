# 4. Concurrency Debugging - threads, asyncio, and multiprocessing

Modules 1-3 covered single-threaded, single-process programs. Concurrency
adds a new failure mode on top of everything else: **the bug is in how
multiple threads/tasks/processes interact**, not in any one function. The
tools from modules 1-3 still apply, but you have to apply them PER
thread/task/process, and ask different questions.

## Concepts

- **The GIL (Global Interpreter Lock)**: only one thread executes Python
  bytecode at a time. Threads help with I/O-bound work (the GIL is released
  during blocking I/O - file/socket reads, `time.sleep`, most C-extension
  calls) but NOT with CPU-bound pure-Python work. See
  `01_thread_stack_dumps.py` for a timing comparison that makes this concrete.
- **asyncio is single-threaded, cooperative concurrency**: exactly one
  coroutine runs at a time, and it runs until it hits an `await` that
  actually yields control. A coroutine that does blocking work WITHOUT
  awaiting (e.g. calls `time.sleep` or a synchronous DB driver) freezes the
  ENTIRE event loop - every other task, timer, and I/O callback waits too.
- **multiprocessing has no shared memory by default**: each process has its
  own GIL, heap, and (crucially for this repo) its own profiler/tracer state.
  A profiler started in the parent sees nothing the children do.
- **Deadlock vs. starvation vs. just-slow**: a stack dump distinguishes these.
  Threads stuck in `Lock.acquire()` on different locks = deadlock. Threads
  stuck in `Event.wait()`/`queue.get()` = idle/starved (waiting for work).
  Threads with normal-looking, advancing application frames = just slow
  (profile them, don't look for a "stuck" cause).

## Tool comparison

| Tool / technique | Threads | asyncio tasks | Processes |
|---|---|---|---|
| `faulthandler.dump_traceback(all_threads=True)` | **yes** | shows the one running coroutine's frame only | no (per-process) |
| `threading.enumerate()` + naming | **yes** | n/a | no |
| `asyncio.all_tasks()` + `task.get_stack()` | n/a | **yes** | no |
| `asyncio` debug mode (`PYTHONASYNCIODEBUG=1`) | n/a | **yes** | no |
| `cProfile` / `py-spy` per worker | one profile covers all threads in a process | covers all tasks (one event loop = one thread) | need one **per process** (or `py-spy --subprocesses`) |
| `py-spy dump --pid <pid> --subprocesses` | yes | yes | **yes** |
| VizTracer (timeline) | **yes** (per-thread rows) | **yes** (`--log_async`, task-aware) | **yes** (`--log_multiprocess`) |

The aggregating tools above answer "where does the time go"; **VizTracer**
(`05_viztracer_timeline.md`) answers the concurrency-specific question of
**order and gaps on a timeline** - which is usually what a concurrency bug
actually turns on.

## Files in this module

| File | Demonstrates |
|---|---|
| `01_thread_stack_dumps.py` | Naming threads, busy-vs-idle stacks, GIL timing comparison (threads vs. processes) |
| `02_asyncio_debug_mode.py` | `asyncio.all_tasks()`, `task.get_stack()`, slow-callback warnings, debug mode |
| `03_multiprocessing_profiling.py` | Per-process `cProfile`, merging `.prof` files with `pstats`, `py-spy --subprocesses` |
| `04_deadlock_diagnosis.py` | `faulthandler.dump_traceback_later()` as a hang watchdog, reading a lock-ordering deadlock, fixes |
| `05_viztracer_timeline.md` | VizTracer: a visual **timeline** of threads/tasks/processes - order and gaps, not just totals |

## Run order

```bash
cd docs/04_concurrency_debugging
python 01_thread_stack_dumps.py
python 02_asyncio_debug_mode.py
python 03_multiprocessing_profiling.py
python 04_deadlock_diagnosis.py
```

Then read `05_viztracer_timeline.md` and follow along - it renders a timeline
in a browser (`vizviewer`).

## Decision guide

```
"My concurrent program is misbehaving - where do I look?"
├── Threads: "is a worker thread stuck or just idle?"
│     -> dump all threads (faulthandler/py-spy), check the frame:
│        Lock.acquire/Event.wait/queue.get = idle or deadlocked,
│        application code = busy (profile it)
├── Threads: "adding workers didn't make CPU-bound code faster"
│     -> it's the GIL - use multiprocessing/subprocess instead (01)
├── asyncio: "one slow request is delaying ALL requests"
│     -> something is blocking the event loop - enable debug mode,
│        look for 'Executing ... took X seconds' (02)
├── asyncio: "a task seems to have vanished / never completes"
│     -> asyncio.all_tasks() + task.get_stack() to find where it's
│        suspended; debug mode logs 'Task was destroyed but it is
│        pending!' if it was garbage-collected while running (02)
├── Multiprocessing: "where do MY WORKERS spend their time?"
│     -> profile inside each worker, merge .prof files with pstats,
│        OR py-spy --pid <parent> --subprocesses (03)
└── "The whole process is hung, no CPU usage"
      -> faulthandler.dump_traceback_later() watchdog (or py-spy dump
         from outside) - look for multiple threads stuck in
         Lock.acquire() on different locks = deadlock (04)
```
