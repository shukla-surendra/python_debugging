"""A signal-triggered diagnostics dump - combine modules 1, 3, and 4 into one
"break glass" endpoint for a live process.

This is the pattern you actually want running in production: register ONE
signal handler that, on `kill -USR1 <pid>`, writes a single timestamped
report covering:

1. **Every thread's stack** (module 1 - `faulthandler.dump_traceback`)
2. **GC state** (module 3 - generation counts, collection stats)
3. **Memory usage** (RSS via `resource`, plus `tracemalloc` top allocations
   if it's running)
4. **Live object counts** (module 3 - `objgraph.most_common_types`, useful
   for spotting an object-count leak at a glance)

...to a FILE (not stdout - stdout may be redirected somewhere unhelpful, and
you want the report to persist after the signal). Operators then run
`kill -USR1 <pid>` and `cat /tmp/diag-<pid>-*.txt`.

Run:
    python 02_diagnostics_signal_server.py
"""

from __future__ import annotations

import faulthandler
import gc
import os
import resource
import signal
import sys
import threading
import time
import tracemalloc
from datetime import datetime
from pathlib import Path

import objgraph


def write_diagnostics_report(out_dir: Path) -> Path:
    """Write a full diagnostics snapshot to a timestamped file and return its path."""
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out_path = out_dir / f"diag-{os.getpid()}-{timestamp}.txt"

    with open(out_path, "w") as f:
        f.write(f"=== Diagnostics report: PID {os.getpid()} at {datetime.now().isoformat()} ===\n\n")

        f.write("--- 1. Thread stacks (faulthandler.dump_traceback) ---\n")
        faulthandler.dump_traceback(file=f, all_threads=True)
        f.write("\n")

        f.write("--- 2. GC state ---\n")
        f.write(f"gc.get_count() = {gc.get_count()}\n")
        f.write(f"gc.get_threshold() = {gc.get_threshold()}\n")
        for gen, stats in enumerate(gc.get_stats()):
            f.write(f"gen{gen}: collections={stats['collections']} "
                    f"collected={stats['collected']} uncollectable={stats['uncollectable']}\n")
        f.write("\n")

        f.write("--- 3. Memory usage ---\n")
        rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        f.write(f"Peak RSS (ru_maxrss): {rss_kb / 1024:.1f} MiB\n")
        if tracemalloc.is_tracing():
            current, peak = tracemalloc.get_traced_memory()
            f.write(f"tracemalloc: current={current / 1024 / 1024:.1f} MiB, "
                    f"peak={peak / 1024 / 1024:.1f} MiB\n")
            f.write("Top 5 allocations by line:\n")
            for stat in tracemalloc.take_snapshot().statistics("lineno")[:5]:
                f.write(f"  {stat}\n")
        else:
            f.write("tracemalloc: not started (call tracemalloc.start() at "
                    "process startup to enable this section)\n")
        f.write("\n")

        f.write("--- 4. Live object counts (objgraph.most_common_types) ---\n")
        for name, count in objgraph.most_common_types(limit=8):
            f.write(f"  {name:20s} {count:8d}\n")

    return out_path


def install_diagnostics_handler(out_dir: Path, sig: signal.Signals = signal.SIGUSR1) -> None:
    """Register a signal handler that writes a diagnostics report on receipt."""

    def handler(signum, frame) -> None:
        path = write_diagnostics_report(out_dir)
        # Keep the handler itself minimal and signal-safe-ish: just print the
        # path. The heavy lifting already happened in write_diagnostics_report.
        print(f"[diagnostics] wrote {path}", file=sys.stderr)

    signal.signal(sig, handler)
    print(f"[diagnostics] PID {os.getpid()}: send {sig.name} to dump diagnostics "
          f"to {out_dir}/  (e.g. `kill -{sig.value} {os.getpid()}`)")


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_diagnostics_on_signal(out_dir: Path) -> None:
    section("Signal-triggered diagnostics dump")

    tracemalloc.start()

    # A few named background threads with different "states" to make the
    # report interesting (mirrors 04_concurrency_debugging/01).
    stop = threading.Event()
    idle = threading.Event()

    def cpu_worker() -> None:
        total = 0
        while not stop.is_set():
            for i in range(100_000):
                total += i * i

    def idle_worker() -> None:
        idle.wait()

    # Allocate something for objgraph/tracemalloc to see.
    _retained = [bytearray(10_000) for _ in range(200)]  # noqa: F841

    threads = [
        threading.Thread(target=cpu_worker, name="cpu-worker-0", daemon=True),
        threading.Thread(target=idle_worker, name="idle-worker-0", daemon=True),
    ]
    for t in threads:
        t.start()
    time.sleep(0.1)

    install_diagnostics_handler(out_dir)

    print("\nSending SIGUSR1 to ourselves (simulating `kill -USR1 <pid>` from")
    print("another terminal)...")
    sys.stdout.flush()  # the handler's stderr print is unbuffered - flush first
    os.kill(os.getpid(), signal.SIGUSR1)
    time.sleep(0.2)  # let the handler run

    report_files = sorted(out_dir.glob(f"diag-{os.getpid()}-*.txt"))
    report = report_files[-1]
    print(f"\n--- Contents of {report.name} ---\n")
    print(report.read_text())

    stop.set()
    idle.set()
    for t in threads:
        t.join()
    tracemalloc.stop()


if __name__ == "__main__":
    out_dir = Path("/tmp")
    written = []
    try:
        before = set(out_dir.glob(f"diag-{os.getpid()}-*.txt"))
        demo_diagnostics_on_signal(out_dir)
        after = set(out_dir.glob(f"diag-{os.getpid()}-*.txt"))
        written = sorted(after - before)
    finally:
        for f in written:
            f.unlink(missing_ok=True)
