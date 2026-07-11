"""Dump every thread's stack on demand via a Unix signal.

This is the pattern you want in a long-running service: register a signal
handler once at startup, then whenever the process seems stuck, run

    kill -USR1 <pid>

and the process prints a full stack dump for every thread to stderr -
without stopping, without a debugger attached, without restarting.

Two ways to do it:

1. ``faulthandler.register(signal.SIGUSR1)`` - one stdlib call, dumps via
   the same machinery as ``dump_traceback()``. Simplest option, use this
   by default.
2. A hand-written ``signal.signal(signal.SIGUSR1, handler)`` that walks
   ``sys._current_frames()`` and ``threading.enumerate()`` yourself - more
   verbose, but you control the formatting (e.g. JSON for log aggregation),
   and you can include thread names (faulthandler only shows them since
   Python 3.10, and only if the thread was created via `threading`).

Run interactively (recommended - open two terminals):

    Terminal 1: python 03_signal_handler_dump.py
    Terminal 2: kill -USR1 <pid printed by terminal 1>

If run non-interactively (e.g. piped, or no TTY), the script sends itself
SIGUSR1 automatically after 1 second so you still see the output.
"""

from __future__ import annotations

import faulthandler
import os
import signal
import sys
import threading
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from workloads.cpu_bound import one_round  # noqa: E402
from workloads.io_bound_sleep import handle_request  # noqa: E402


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}", flush=True)


# --- Option 1: stdlib one-liner -------------------------------------------

def install_faulthandler_signal() -> None:
    """faulthandler.register(sig) -> dump all stacks when `sig` is received.

    chain=False (the default) is important: it means faulthandler's C-level
    handler *replaces* the default SIGUSR1 action (terminate) instead of
    calling it afterwards. With chain=True and no other handler installed,
    the process would dump its stacks and then die from the default action.
    """
    faulthandler.register(signal.SIGUSR1, chain=False)


# --- Option 2: hand-rolled handler with custom formatting ------------------

def custom_dump_handler(signum, frame) -> None:
    """Print a labeled stack dump for every live thread.

    Unlike faulthandler, we can attach the human-readable thread name
    (`threading.current_thread().name`) to each stack, and we have full
    control over the output format.
    """
    print(f"\n--- custom signal dump (signal {signum}) ---", flush=True)

    # Map thread ident -> Thread object, so we can print names.
    threads_by_ident = {t.ident: t for t in threading.enumerate()}

    for thread_id, stack_frame in sys._current_frames().items():
        thread = threads_by_ident.get(thread_id)
        name = thread.name if thread else f"thread-{thread_id}"
        print(f"\nThread '{name}' (id={thread_id}):")
        # format_stack walks frame.f_back, so pass the frame directly.
        for line in traceback.format_stack(stack_frame):
            print(line, end="")

    print("--- end of dump ---\n", flush=True)


def install_custom_signal() -> None:
    signal.signal(signal.SIGUSR2, custom_dump_handler)


# --- Background work so the dump has something interesting to show --------

def cpu_worker(stop: threading.Event) -> None:
    while not stop.is_set():
        one_round(size=20_000, fib_n=10)


def io_worker(stop: threading.Event) -> None:
    i = 0
    while not stop.is_set():
        handle_request(i, 0.2)
        i += 1


def main() -> None:
    install_faulthandler_signal()
    install_custom_signal()

    pid = os.getpid()
    section("Signal-based stack dumps")
    print(f"PID = {pid}")
    print("This process registered:")
    print("  SIGUSR1 -> faulthandler.dump_traceback() for ALL threads")
    print("  SIGUSR2 -> custom handler with thread names")
    print()
    print("Try, from another terminal:")
    print(f"  kill -USR1 {pid}")
    print(f"  kill -USR2 {pid}")

    stop = threading.Event()
    threads = [
        threading.Thread(target=cpu_worker, args=(stop,), name="cpu-worker", daemon=True),
        threading.Thread(target=io_worker, args=(stop,), name="io-worker", daemon=True),
    ]
    for t in threads:
        t.start()

    if sys.stdin.isatty():
        print("\nRunning for up to 60s. Send SIGUSR1/SIGUSR2, or Ctrl+C to stop.")
        try:
            time.sleep(60)
        except KeyboardInterrupt:
            pass
    else:
        print("\nNon-interactive run detected: sending SIGUSR1 and SIGUSR2 to "
              "ourselves after a short delay so the demo is self-contained.")
        time.sleep(0.3)
        os.kill(pid, signal.SIGUSR1)
        time.sleep(0.3)
        os.kill(pid, signal.SIGUSR2)
        time.sleep(0.1)

    stop.set()
    for t in threads:
        t.join(timeout=2)


if __name__ == "__main__":
    main()
