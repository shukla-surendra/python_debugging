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

# pystack - live process OR core dump, with native frames + GIL/GC state (Linux):
pystack remote <PID>                 # like py-spy dump, plus GIL holder / GC state
pystack remote <PID> --native --locals
pystack core ./core.<PID> --native   # post-mortem from a crash core dump

# debugpy - interactive/remote (IDE) debugging over a socket:
python -m debugpy --listen 127.0.0.1:5678 --wait-for-client myapp.py
# then attach VS Code/PyCharm; tunnel with: kubectl port-forward / ssh -L 5678:...

# Last resort - works even on native/GIL-stuck deadlocks:
gdb -p <PID>
(gdb) py-bt
(gdb) py-list
```

```bash
# OS layer - what is it doing BELOW Python (which syscall / fd / kernel state):
sudo strace -p <PID> -f              # every syscall; futex=lock/GIL, recvfrom=network
sudo strace -c -f -p <PID>           # summary table of syscall time (Ctrl-C to print)
sudo lsof -p <PID>                   # open files/sockets - name the fd it's stuck on
cat /proc/<PID>/status | grep State  # D = uninterruptible I/O sleep (won't budge)
cat /proc/<PID>/task/*/stack         # per-thread kernel stack (root)
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

# austin - minimal zero-dependency out-of-process sampler (time + memory):
austin -i 1ms -o out.austin python myscript.py
austin -p <PID>                       # attach to a running process
austin-tui python myscript.py         # live top-like TUI
austin2speedscope out.austin out.json # view at https://www.speedscope.app/
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

# VizTracer - TIMELINE (order + gaps), the visual tool for async/concurrency:
viztracer --open myscript.py                       # trace + open Perfetto UI
viztracer --log_async -o result.json myapp.py      # asyncio: which coroutine stalled
viztracer --log_multiprocess -o result.json app.py # across child processes
vizviewer result.json                              # open a saved trace

# See an event-loop stall live (blocks the loop; --safe fixes it):
python workloads/async_stall.py            # heartbeat STALLs behind blocking work
python workloads/async_stall.py --safe     # blocking work moved to a thread
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

### Kubernetes (module 5)

```bash
# Snapshot a live pod (safe, ~1ms pause; app is usually PID 1):
kubectl exec <pod> -- py-spy dump --pid 1
kubectl exec <pod> -- pystack remote 1 --native

# Distroless/slim image (no shell/tools) -> ephemeral debug container:
kubectl debug -it <pod> --image=debug-tools --target=<container> --profile=sysadmin

# Interactive debugger, safely: drain from Service, THEN tunnel:
kubectl label pod <pod> app=myapp-DEBUG --overwrite    # stop traffic, keep pod alive
kubectl port-forward <pod> 5678:5678                   # attach debugpy / remote-pdb

kubectl exec <pod> -- kill -USR1 1                     # trigger armed diagnostics
kubectl logs <pod> --previous                          # logs from the crashed container
kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[0].lastState.terminated}'
# exitCode 137 = OOMKilled, 139 = SIGSEGV (grab a core), 1 = app error (see the traceback)
kubectl cp <pod>:/tmp/core.1 ./core.1 && pystack core ./core.1 --native
```

## Observability & auxiliary (module 6)

```python
# logging - lazy %-formatting; log the traceback inside except:
import logging; log = logging.getLogger(__name__)
log.info("handled in %d ms", ms)          # %s/%d, NOT f-strings (lazy)
log.exception("charge failed order=%s", order_id)   # message + traceback

# Lightweight tracing / print-debugging:
import pysnooper
@pysnooper.snoop()                         # log every line + variable change
def f(...): ...
from icecream import ic; ic(x, y)          # better print: "ic| x: 1, y: 2"
from rich.traceback import install; install(show_locals=True)  # pretty tracebacks
```

```bash
# hunter - trace a slice of a big codebase without editing it:
PYTHONHUNTER='module="myapp.orders", action=CallPrinter()' python app.py

# coverage - prove which lines/branches actually ran:
coverage run --branch myscript.py && coverage report -m
coverage html                              # annotated source: green=ran, red=didn't

# pytest debugging:
pytest --lf -x --pdb                       # rerun last failures, stop at 1st, drop to pdb
pytest -l                                  # --showlocals in tracebacks
pytest --trace -k test_name                # pdb at the START of a specific test
```

Production observability (wire in ahead of time):

```python
import sentry_sdk                                   # error tracking across the fleet
sentry_sdk.init(dsn="...", environment="prod", release="myapp@1.4.2")
# OpenTelemetry - distributed tracing across services (zero-code auto-instrument):
#   opentelemetry-instrument python app.py
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
| Stack ends in a syscall - what's it *really* waiting on? | `strace -p <PID>` + `lsof -p <PID>` |
| Post-mortem a crash / need native frames / only have a core | `pystack remote`/`pystack core --native` |
| Interactive debug of a remote/containerized process | `debugpy` + `port-forward` |
| ORDER things ran in / async event-loop stall | VizTracer (`--log_async`) |
| Which lines/branches actually executed? | `coverage run --branch` |
| Aggregate crashes across the fleet, with context | Sentry |
| Which service/hop in a multi-service request is slow? | OpenTelemetry |
| Debug from a failing test | `pytest --lf -x --pdb` |
| Live inspect/mutate process state, no restart | remote pdb console (module 5) |
