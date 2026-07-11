# Incident checklist: "Something is wrong with this Python process"

A practical runbook tying together every tool in this repo. Find the symptom
that matches, follow the steps, and cross-reference back to the module that
explains the tool in depth.

Every step here assumes you can run commands on the host (or a debug
sidecar/exec into the container) but generally **cannot restart the
process** - that's the whole point of these tools.

> **Running in Kubernetes?** The *diagnosis* below is the same, but getting
> the tools to the process (exec vs. ephemeral debug container, `SYS_PTRACE`,
> not tripping liveness probes, `port-forward`, core dumps, OOMKilled) has its
> own playbook: [`04_kubernetes_debugging.md`](04_kubernetes_debugging.md).

---

## 0. First, get the PID and basic vitals

```bash
pgrep -af python                      # find the PID(s)
ps -o pid,ppid,%cpu,%mem,etime,cmd -p <PID>
cat /proc/<PID>/status | grep -i vm   # VmRSS, VmPeak, etc.
ls /proc/<PID>/task/ | wc -l          # number of OS threads
```

- **High `%CPU`, climbing**: go to [§1 CPU](#1-the-process-is-using-too-much-cpu--is-slow).
- **High/climbing `VmRSS`**: go to [§2 Memory](#2-the-process-is-using-too-much-memory).
- **`%CPU` near 0, process not responding**: go to [§3 Hung](#3-the-process-is-hung-not-responding-0-cpu).
- **Thread count growing unboundedly**: go to [§4 Threads/tasks](#4-thread--task-count-is-growing-unboundedly).

---

## 1. The process is using too much CPU / is slow

1. **Zero-instrumentation first look**: attach a sampling profiler -
   no code changes, safe on a live process.
   ```bash
   py-spy top --pid <PID>          # top-like view, refreshes
   py-spy dump --pid <PID>         # one-shot stack snapshot
   py-spy record -o out.svg --pid <PID> --duration 30   # flamegraph
   ```
   See [`01_stack_dumps/06_py_spy_dump.md`](../01_stack_dumps/06_py_spy_dump.md)
   and [`02_cpu_profiling/06_py_spy_record.md`](../02_cpu_profiling/06_py_spy_record.md).
   If `py-spy` reports a permission error, see the `ptrace_scope`/`sudo`
   notes in that file before trying anything more invasive.

2. **Multiple worker processes?** Use `--subprocesses` (or target each PID
   under `<PID>` from `pgrep -P <PID>`):
   ```bash
   py-spy dump --pid <PID> --subprocesses
   ```
   See [`04_concurrency_debugging/03_multiprocessing_profiling.py`](../04_concurrency_debugging/03_multiprocessing_profiling.py).

3. **Need per-line detail, and CAN reproduce it offline?** Re-run the
   workload under `scalene` or `line_profiler` in staging:
   ```bash
   scalene run -o profile.json path/to/script.py
   ```
   See [`02_cpu_profiling/07_scalene_demo.md`](../02_cpu_profiling/07_scalene_demo.md)
   and [`02_cpu_profiling/04_line_profiler_demo.py`](../02_cpu_profiling/04_line_profiler_demo.py).

4. **Is it asyncio, and ONE slow request seems to be delaying everything
   else?** Enable debug mode (no restart needed if you can reach a
   diagnostics console - see §5) and look for "Executing ... took X
   seconds":
   ```bash
   PYTHONASYNCIODEBUG=1 python myapp.py   # for next restart
   ```
   See [`04_concurrency_debugging/02_asyncio_debug_mode.py`](../04_concurrency_debugging/02_asyncio_debug_mode.py).

5. **Threads not helping / many cores idle while one is pegged?** That's the
   GIL - CPU-bound work needs `multiprocessing`/subprocesses, not threads.
   See [`04_concurrency_debugging/01_thread_stack_dumps.py`](../04_concurrency_debugging/01_thread_stack_dumps.py) §3.

---

## 2. The process is using too much memory

1. **Is it still growing, or did it plateau?** If it plateaued (even at a
   high number), it may just be normal working-set size (caches, loaded
   models, etc.) - not a leak. If it's UNBOUNDED and climbing with
   time/requests, continue.

2. **If `tracemalloc` is already running** (you started it at boot - see
   §5), take two snapshots under load and diff:
   ```python
   snap1 = tracemalloc.take_snapshot()
   # ... wait / handle more requests ...
   snap2 = tracemalloc.take_snapshot()
   for stat in snap2.compare_to(snap1, "lineno")[:10]:
       print(stat)
   ```
   See [`03_memory_profiling/03_tracemalloc_snapshot_diff.py`](../03_memory_profiling/03_tracemalloc_snapshot_diff.py).
   The top entries are your growing allocation sites.

3. **`tracemalloc` wasn't running and you can't restart**: use `memray
   attach <PID>` (Linux) to start tracking a live process, or fall back to
   `objgraph` via a remote console (§5) to find growing object counts:
   ```python
   objgraph.show_growth(limit=10)   # call twice, a few minutes apart
   ```
   See [`03_memory_profiling/05_objgraph_demo.py`](../03_memory_profiling/05_objgraph_demo.py)
   and [`03_memory_profiling/08_memray_demo.md`](../03_memory_profiling/08_memray_demo.md).

4. **Found a growing type/object - now find WHY it's alive**:
   ```python
   objgraph.find_backref_chain(obj, objgraph.is_proper_module)
   ```
   This gives the reference chain keeping it alive - usually an unbounded
   cache, a registered-but-never-unregistered callback, or a list that's
   only ever appended to. See [`03_memory_profiling/05_objgraph_demo.py`](../03_memory_profiling/05_objgraph_demo.py) §3.

5. **Suspect the leak is in a C extension (numpy/PIL/etc.), not Python
   objects?** `tracemalloc`/`objgraph` won't show it (they only see the
   Python heap). Use `memray`:
   ```bash
   memray attach <PID>     # or memray run for the next restart
   memray flamegraph --leaks output.bin
   ```
   See [`03_memory_profiling/08_memray_demo.md`](../03_memory_profiling/08_memray_demo.md).

6. **Reference cycles?** Confirm the cyclic GC is actually running and check
   `gc.garbage`:
   ```python
   gc.collect()
   print(len(gc.garbage))   # should be 0 on Python 3.4+
   ```
   See [`03_memory_profiling/07_gc_module_demo.py`](../03_memory_profiling/07_gc_module_demo.py).

7. **Already got OOM-killed (exit 137 / `OOMKilled`)?** `SIGKILL` gives the
   process no chance to dump anything - there's no traceback or core to read.
   Memory debugging then has to be **proactive**: reproduce under a slightly
   lower limit with `memray`/`tracemalloc` running, and check whether it's a
   real leak or just a limit below the working set. In Kubernetes see
   [`04_kubernetes_debugging.md`](04_kubernetes_debugging.md).

---

## 3. The process is hung / not responding (~0% CPU)

1. **Get a stack dump from OUTSIDE the process first** - works even if the
   process never planned for this:
   ```bash
   py-spy dump --pid <PID>
   pystack remote <PID> --native      # also shows GIL holder / GC state / native frames
   ```
   See [`01_stack_dumps/06_py_spy_dump.md`](../01_stack_dumps/06_py_spy_dump.md)
   and [`01_stack_dumps/08_pystack.md`](../01_stack_dumps/08_pystack.md).

2. **Read every thread's frame**:
   - Multiple threads stuck in `Lock.acquire()` on **different** lock
     objects -> classic lock-ordering **deadlock**. See
     [`04_concurrency_debugging/04_deadlock_diagnosis.py`](../04_concurrency_debugging/04_deadlock_diagnosis.py).
   - All threads stuck in `Event.wait()` / `queue.get()` / `select` ->
     genuinely idle, waiting for upstream work. Check upstream (load
     balancer, message queue depth) rather than this process.
   - One thread deep in application code, others idle -> that ONE thread
     is the problem (infinite loop, waiting on a slow/unreachable
     dependency with no timeout - e.g. a DB call with no `statement_timeout`).

3. **The top frame is a syscall (`read`/`recv`/`acquire`/`poll`)?** Drop to
   the OS layer to see what it's *really* blocked on - `py-spy` shows the
   Python function, not the fd or peer:
   ```bash
   sudo strace -p <PID> -f            # futex=lock/GIL, recvfrom=network hang
   sudo lsof -p <PID> | grep TCP      # name the socket/DB it's stuck on
   cat /proc/<PID>/status | grep State  # D = uninterruptible I/O (infra problem)
   ```
   See [`01_stack_dumps/10_os_level_introspection.md`](../01_stack_dumps/10_os_level_introspection.md).

4. **If `py-spy` can't attach (ptrace denied, can't get sudo)**: `gdb -p
   <PID>` plus the CPython gdb extensions can still get a stack, even from a
   process stuck in a C call / native deadlock that `py-spy` can't symbolicate
   well. See [`01_stack_dumps/07_gdb_python_extension.md`](../01_stack_dumps/07_gdb_python_extension.md).

5. **If the process has a pre-armed watchdog** (see §5), it may have already
   written a dump to disk when it first got stuck - check the logs/diagnostics
   directory before doing anything live.

---

## 4. Thread / task count is growing unboundedly

1. `ls /proc/<PID>/task/ | wc -l` over time - confirm it's actually growing
   (vs. a fixed large pool).
2. Dump all threads and look for many threads with **identical stacks** -
   usually means something creates a new thread per request/connection and
   never joins/cleans it up (a `threading.Thread(...)` per request instead of
   a pool).
   ```bash
   py-spy dump --pid <PID> | sort | uniq -c | sort -rn | head
   ```
3. For asyncio, the equivalent is `len(asyncio.all_tasks())` growing -
   usually a task that's created but never awaited/cancelled (debug mode's
   "Task was destroyed but it is pending!" warning is the proactive version
   of this check). See [`04_concurrency_debugging/02_asyncio_debug_mode.py`](../04_concurrency_debugging/02_asyncio_debug_mode.py).

---

## 5. What to set up BEFORE the incident

Everything above is much easier if the process already has:

- [ ] `faulthandler.enable()` called at startup (free, always on - module 1).
- [ ] A `SIGUSR1`-triggered diagnostics dump to a file (threads + GC + memory
      + object counts in one shot) - see
      [`02_diagnostics_signal_server.py`](02_diagnostics_signal_server.py).
- [ ] `tracemalloc.start()` if memory is a known concern (small, constant
      overhead; lets you diff snapshots later without restarting).
- [ ] A remote pdb / debug console bound to `127.0.0.1` for emergency
      live inspection - see [`01_remote_pdb_server.py`](01_remote_pdb_server.py).
      **Internal-only, never exposed externally** (it's arbitrary code
      execution by design).
- [ ] Threads named meaningfully (`threading.Thread(..., name=...)`) so
      dumps are self-explanatory - see
      [`04_concurrency_debugging/01_thread_stack_dumps.py`](../04_concurrency_debugging/01_thread_stack_dumps.py).
- [ ] `gc.freeze()` after startup/warmup if you `fork()` worker processes -
      see [`03_memory_profiling/07_gc_module_demo.py`](../03_memory_profiling/07_gc_module_demo.py) §5.
- [ ] `py-spy`/`pystack` (and `gdb` + `python3-dbg`, `strace`, `lsof`)
      available on the HOST or a debug sidecar/ephemeral image - these need
      zero pre-planning in the target process, but the BINARIES still need to
      be installed somewhere you can reach (in k8s, a debug-tools image - see
      [`04_kubernetes_debugging.md`](04_kubernetes_debugging.md)).
- [ ] **Structured logging** with a trace/correlation ID on every line - often
      the diagnosis *is* in the logs. See
      [`../06_observability/05_logging.md`](../06_observability/05_logging.md).
- [ ] **Error tracking** (Sentry) so crashes are captured with locals/context
      across the fleet, and **distributed tracing** (OpenTelemetry) if the
      request crosses services - the "always recording" layers. See
      [`../06_observability/03_sentry.md`](../06_observability/03_sentry.md)
      and [`../06_observability/04_opentelemetry.md`](../06_observability/04_opentelemetry.md).
- [ ] A **continuous profiler** (Pyroscope/Parca) if you keep needing to ask
      "why was it slow last night" - the look-backwards version of `py-spy`.
