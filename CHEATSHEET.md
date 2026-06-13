# Cheatsheet

One page of copy-pasteable commands. See each module's `README.md` for
explanations and `01_thread_stack_dumps.py`-style demo scripts for runnable
examples.

## Stack dumps (module 1)

```python
# At startup - always on, near-zero cost:
import faulthandler; faulthandler.enable()

# One-shot dump of every thread, right now:
faulthandler.dump_traceback(all_threads=True)

# Watchdog: dump if we're not done in N seconds (deadlock detector):
faulthandler.dump_traceback_later(30, repeat=False)
faulthandler.cancel_dump_traceback_later()  # cancel if we finished in time

# Signal-triggered dump (from another terminal: kill -USR1 <pid>):
import signal
faulthandler.register(signal.SIGUSR1, chain=False)

# Manual, no faulthandler:
import sys, threading, traceback
for tid, frame in sys._current_frames().items():
    traceback.print_stack(frame)

# Exception tracebacks:
import traceback
traceback.print_exc()          # to stderr
traceback.format_exc()         # as a string

# Interactive debugging:
breakpoint()                   # drop into pdb here
import pdb; pdb.pm()           # post-mortem after an exception in the REPL
```

```bash
# From OUTSIDE the process, no code changes (may need sudo / ptrace_scope=0):
py-spy dump --pid <PID>
py-spy top --pid <PID>

# Spawn mode - no special permissions needed (py-spy is the parent):
py-spy record -o out.svg -- python myscript.py

# Last resort - works even on native/GIL-stuck deadlocks:
gdb -p <PID>
(gdb) py-bt
(gdb) py-list
```

## CPU profiling (module 2)

```python
# cProfile - deterministic, per-function:
import cProfile, pstats
with cProfile.Profile() as pr:
    do_work()
pstats.Stats(pr).sort_stats("cumulative").print_stats(10)

# Save/reload:
pr.dump_stats("out.prof")
pstats.Stats("out.prof").strip_dirs().sort_stats("tottime").print_stats(10)

# timeit - microbenchmarks:
import timeit
timeit.timeit("do_thing()", globals=globals(), number=1000)
```

```bash
# cProfile from the command line:
python -m cProfile -s cumulative myscript.py
python -m cProfile -o out.prof myscript.py

# line_profiler - per-line, needs @profile decorator:
kernprof -lv myscript.py

# pyinstrument - statistical, low overhead, call tree:
pyinstrument myscript.py
pyinstrument -r html -o report.html myscript.py

# py-spy - flamegraph/speedscope, zero code changes:
py-spy record -o flame.svg -- python myscript.py
py-spy record -f speedscope -o profile.json -- python myscript.py
py-spy record -o out.svg --pid <PID> --duration 30 --subprocesses

# scalene - CPU + memory + GPU, per line, splits Python/native/system:
scalene run -o profile.json myscript.py
scalene view --cli
scalene run --cpu-only -o profile.json myscript.py   # CPU only, lower overhead
```

## Memory profiling (module 3)

```python
# Shallow vs. deep size:
import sys
sys.getsizeof(obj)                    # shallow - doesn't follow references
from pympler import asizeof
asizeof.asizeof(obj)                  # deep - follows references

# tracemalloc - stdlib, source-location tracking:
import tracemalloc
tracemalloc.start()
snap1 = tracemalloc.take_snapshot()
# ... do work ...
snap2 = tracemalloc.take_snapshot()
for stat in snap2.compare_to(snap1, "lineno")[:10]:
    print(stat)
current, peak = tracemalloc.get_traced_memory()

# objgraph - object counts and WHY something is alive:
import objgraph
objgraph.show_most_common_types(limit=10)
objgraph.show_growth(limit=10)        # call twice, see the delta
objgraph.find_backref_chain(obj, objgraph.is_proper_module)

# pympler - heap composition + diffing:
from pympler import muppy, summary, tracker
summary.print_(summary.summarize(muppy.get_objects()), limit=10)
tr = tracker.SummaryTracker()
# ... do work ...
tr.print_diff()

# gc - reference cycles:
import gc
gc.collect()              # returns count of unreachable objects freed
gc.get_stats()            # per-generation collection stats
gc.get_referrers(obj)      # who points AT obj
gc.get_referents(obj)      # what does obj point AT
gc.garbage                 # uncollectable objects (almost always empty, py3.4+)
gc.freeze()                # before fork() - avoid COW churn in workers
```

```bash
# memory_profiler - per-line RSS (needs @profile decorator):
python -m memory_profiler myscript.py
mprof run python myscript.py && mprof plot

# memray - allocator-level, Python + native, flamegraphs:
memray run -o out.bin myscript.py
memray flamegraph out.bin
memray flamegraph --leaks out.bin     # only allocations that were never freed
memray summary out.bin
memray attach <PID>                   # attach to an already-running process
```

## Concurrency (module 4)

```python
# Name your threads - shows up in every dump:
threading.Thread(target=worker, name="cpu-worker-0", daemon=True)
# Note: OS thread names truncate to 15 chars on Linux.

# asyncio - per-task stacks:
for task in asyncio.all_tasks():
    print(task.get_name())
    task.print_stack(limit=5)

# asyncio debug mode - warns on blocking calls in coroutines:
asyncio.run(main(), debug=True)
# or: PYTHONASYNCIODEBUG=1 python myapp.py
```

```bash
# Profile a multiprocessing program - one PID per process:
py-spy dump --pid <PARENT_PID> --subprocesses
py-spy record -o out.svg --pid <PARENT_PID> --subprocesses
```

## Production playbook (module 5)

```python
# At startup - the "debuggable by default" baseline:
import faulthandler, tracemalloc
faulthandler.enable()
tracemalloc.start()

# Remote pdb console (127.0.0.1 ONLY - arbitrary code execution by design):
threading.Thread(target=serve_remote_pdb, args=(globals(),), daemon=True).start()
# connect with: nc 127.0.0.1 4444

# SIGUSR1 -> write threads+GC+memory+objects to a file:
install_diagnostics_handler(Path("/var/log/myapp/"), signal.SIGUSR1)
```

```bash
# Trigger it:
kill -USR1 <PID>
cat /var/log/myapp/diag-<PID>-*.txt
```

## Decision quick-picks

| Question | Tool |
|---|---|
| Process hung, need a stack RIGHT NOW, no code changes | `py-spy dump --pid <PID>` |
| Where does the CPU time go (function-level)? | `cProfile` / `pstats` |
| Where does the CPU time go (line-level)? | `line_profiler` or `scalene` |
| CPU + memory + native split, per line | `scalene` |
| Flamegraph, zero overhead, live process | `py-spy record` |
| What's allocated right now, by source line? | `tracemalloc.take_snapshot()` |
| What GREW between two points in time? | `tracemalloc.compare_to()` / `objgraph.growth()` / `pympler.SummaryTracker` |
| Why is THIS object still alive? | `objgraph.find_backref_chain()` |
| Leak might be in a C extension | `memray` |
| Deep size of one object | `pympler.asizeof.asizeof()` |
| Reference-cycle / GC questions | `gc.collect()`, `gc.get_stats()`, `gc.garbage` |
| Which thread is stuck vs. just idle? | dump all threads, read the top frame |
| Live inspect/mutate process state, no restart | remote pdb console (module 5) |
