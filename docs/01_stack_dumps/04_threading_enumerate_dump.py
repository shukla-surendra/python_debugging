"""Dump thread stacks from WITHIN your own code - no signals required.

Sometimes you don't want (or can't rely on) a signal: maybe you're on
Windows (no SIGUSR1/SIGUSR2), maybe you want to log a dump periodically from
a background "watchdog" thread, or embed it in a health-check endpoint.

The combination of:

* ``threading.enumerate()``   - every Thread object that's still alive
* ``sys._current_frames()``   - {thread_ident: top frame} for every thread
* ``traceback.format_stack()``- render a frame chain as text

...gives you a full stack dump on demand, callable as a plain function.

This is exactly what tools like Django's "thread dump" admin pages and
many APM agents do under the hood.

Run:
    python 04_threading_enumerate_dump.py
"""

from __future__ import annotations

import sys
import threading
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from workloads.cpu_bound import one_round  # noqa: E402
from workloads.io_bound_sleep import handle_request  # noqa: E402


def dump_all_threads(out=sys.stdout) -> None:
    """Print a stack dump for every live thread, with names and states."""
    threads_by_ident = {t.ident: t for t in threading.enumerate()}
    frames = sys._current_frames()

    print(f"=== Thread dump: {len(frames)} threads ===", file=out)
    for ident, frame in frames.items():
        thread = threads_by_ident.get(ident)
        name = thread.name if thread else "<unknown>"
        daemon = thread.daemon if thread else "?"
        print(f"\n--- Thread '{name}' (ident={ident}, daemon={daemon}) ---", file=out)
        stack = traceback.format_stack(frame)
        # Print innermost frame first (reverse), like faulthandler/py-spy do.
        for line in reversed(stack):
            print(line, end="", file=out)


def watchdog_thread(stop: threading.Event, interval: float = 0.5) -> None:
    """A background thread that periodically dumps everyone's stacks.

    This is the "self-monitoring" pattern: run this thread in every
    long-lived service and pipe its output to a ring-buffer log file. If
    the service hangs, the last dump in the ring buffer shows you why.
    """
    n = 0
    while not stop.wait(timeout=interval):
        n += 1
        print(f"\n############ Watchdog dump #{n} ############")
        dump_all_threads()


def cpu_worker(stop: threading.Event) -> None:
    while not stop.is_set():
        one_round(size=50_000, fib_n=12)


def io_worker(stop: threading.Event) -> None:
    i = 0
    while not stop.is_set():
        handle_request(i, 0.3)
        i += 1


def main() -> None:
    stop = threading.Event()

    workers = [
        threading.Thread(target=cpu_worker, args=(stop,), name="cpu-worker"),
        threading.Thread(target=io_worker, args=(stop,), name="io-worker"),
        threading.Thread(target=watchdog_thread, args=(stop, 0.4), name="watchdog", daemon=True),
    ]
    for t in workers:
        t.start()

    # Let everything run for a moment, then take one manual dump too.
    time.sleep(0.2)
    print("\n############ Manual dump (from main thread) ############")
    dump_all_threads()

    time.sleep(1.0)
    stop.set()
    for t in workers:
        if t.name != "watchdog":
            t.join()


if __name__ == "__main__":
    main()
