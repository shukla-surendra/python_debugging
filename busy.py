"""A long-running, multi-threaded "victim" process that keeps itself busy
forever - CPU work, I/O waits, and steady memory growth all happening
concurrently in separate threads.

Unlike the scripts in workloads/ (which each isolate ONE failure mode and
then exit), busy.py is meant to be started once and left running so you
have a realistic target to practice against:

* stack dumps (py-spy dump/top, faulthandler, threading.enumerate()) across
  a mix of busy, sleeping, and permanently-parked threads
* memory profiling (tracemalloc, memray, objgraph, pympler) against a
  process whose RSS climbs steadily, like a real leaking service

It reuses the workload generators in workloads/ instead of reimplementing
CPU/IO/memory patterns.

Run it, note the PID it prints, and inspect it from another terminal.

Default mix (2 cpu, 2 io, 1 stuck, 1 leak worker):

    python busy.py

Heavier CPU load, e.g. to compare cProfile/py-spy top output across cores:

    python busy.py --cpu-workers 4 --io-workers 0 --stuck-workers 0 --no-leak

I/O-heavy, many threads parked in time.sleep - good for threading.enumerate()
and stack-dump practice:

    python busy.py --cpu-workers 0 --io-workers 12 --io-latency 0.5 --no-leak

Memory-profiling focus - fast, big steps so tracemalloc/memray/objgraph show
growth quickly (Ctrl+C once RSS has climbed enough):

    python busy.py --cpu-workers 1 --io-workers 0 --leak-batch 2000 --leak-interval 0.2

Several permanently-blocked threads next to busy ones - practice telling
"stuck" apart from "just slow" in a dump:

    python busy.py --stuck-workers 5

Attach tools from another terminal, using the PID busy.py printed at startup:

    py-spy dump --pid <pid>              # one-shot stack dump, all threads
    py-spy top --pid <pid>                 # live per-function CPU sampling
    py-spy record --pid <pid> -o out.svg   # flamegraph over time
    kill -USR1 <pid>                       # only if you've wired up a handler, see
                                            # 05_production_playbook/02_diagnostics_signal_server.py

Or arm the stdlib fatal-error watchdog from the outside (no source change
needed) so a crash also dumps every thread's stack:

    PYTHONFAULTHANDLER=1 python busy.py

Stop it with Ctrl+C (or `kill -TERM <pid>`) - it shuts threads down
cleanly instead of just dying mid-stack.
"""

from __future__ import annotations

import argparse
import os
import resource
import signal
import threading
import time

from workloads import cpu_bound, io_bound_sleep, memory_leak

stop = threading.Event()


def _handle_signal(signum, _frame) -> None:
    print(f"\n[busy] received signal {signum}, shutting down...")
    stop.set()


def cpu_worker(_worker_id: int) -> None:
    """Keep one CPU core busy with the cpu_bound workload."""
    while not stop.is_set():
        cpu_bound.one_round()


def io_worker(_worker_id: int, latency: float) -> None:
    """Simulate a steady stream of I/O-bound requests."""
    request_id = 0
    while not stop.is_set():
        io_bound_sleep.handle_request(request_id, latency)
        request_id += 1


def leak_worker(batch_size: int, interval: float) -> None:
    """Grow workloads.memory_leak's global cache forever, in batches."""
    round_number = 0
    while not stop.wait(interval):
        memory_leak.leak_via_global_cache(iterations=batch_size, start=round_number * batch_size)
        round_number += 1


def stuck_worker(_worker_id: int) -> None:
    """Park forever - a useful contrast in a stack dump against the busy
    and periodically-sleeping threads above (this one never moves)."""
    stop.wait()


def heartbeat(interval: float = 5.0) -> None:
    start = time.perf_counter()
    while not stop.wait(interval):
        elapsed = time.perf_counter() - start
        rss_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        print(f"[busy] alive for {elapsed:.0f}s, {threading.active_count()} threads, "
              f"RSS {rss_mib:.1f} MiB")


def run(cpu_workers: int, io_workers: int, io_latency: float, stuck_workers: int,
        leak: bool, leak_batch: int, leak_interval: float) -> None:
    print(f"PID = {os.getpid()}  (use this PID with py-spy / faulthandler)")

    threads: list[threading.Thread] = []
    for i in range(cpu_workers):
        threads.append(threading.Thread(target=cpu_worker, args=(i,), name=f"cpu-worker-{i}"))
    for i in range(io_workers):
        threads.append(threading.Thread(target=io_worker, args=(i, io_latency), name=f"io-worker-{i}"))
    for i in range(stuck_workers):
        threads.append(threading.Thread(target=stuck_worker, args=(i,), name=f"stuck-worker-{i}"))
    if leak:
        threads.append(threading.Thread(target=leak_worker, args=(leak_batch, leak_interval), name="leak-worker"))
    threads.append(threading.Thread(target=heartbeat, name="heartbeat"))

    for t in threads:
        t.start()

    print(f"[busy] started {len(threads)} threads "
          f"({cpu_workers} cpu, {io_workers} io, {stuck_workers} stuck"
          f"{', 1 leak' if leak else ''}, 1 heartbeat). Ctrl+C to stop.")

    for t in threads:
        t.join()

    print("[busy] all threads stopped cleanly.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-workers", type=int, default=2,
                         help="CPU-bound worker threads (workloads.cpu_bound).")
    parser.add_argument("--io-workers", type=int, default=2,
                         help="I/O-bound worker threads (workloads.io_bound_sleep).")
    parser.add_argument("--io-latency", type=float, default=0.2,
                         help="Simulated per-request latency in seconds.")
    parser.add_argument("--stuck-workers", type=int, default=1,
                         help="Threads that just park forever, for stack-dump contrast.")
    parser.add_argument("--no-leak", action="store_true",
                         help="Disable the steady memory-growth thread.")
    parser.add_argument("--leak-batch", type=int, default=200,
                         help="Cache entries added per leak-worker interval.")
    parser.add_argument("--leak-interval", type=float, default=1.0,
                         help="Seconds between leak-worker batches.")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    run(
        cpu_workers=args.cpu_workers,
        io_workers=args.io_workers,
        io_latency=args.io_latency,
        stuck_workers=args.stuck_workers,
        leak=not args.no_leak,
        leak_batch=args.leak_batch,
        leak_interval=args.leak_interval,
    )
