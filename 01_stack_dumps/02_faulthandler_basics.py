"""faulthandler - stdlib module for dumping tracebacks on fatal errors,
timeouts, or a user signal - WITHOUT pdb or any third-party tool.

Three superpowers, demonstrated below:

1. ``faulthandler.enable()``        - on a segfault/abort/fatal error, dump
   all thread stacks before the process dies. (We can't easily segfault
   CPython safely here, so this is explained rather than triggered.)
2. ``faulthandler.dump_traceback()`` - dump all thread stacks RIGHT NOW,
   on demand, like a manual stack dump.
3. ``faulthandler.dump_traceback_later(timeout, ...)`` - a "dead man's
   switch": if the process is still alive after ``timeout`` seconds, dump
   all stacks (and optionally exit). This is how you catch a HANG without
   attaching any external tool.

Run:
    python 02_faulthandler_basics.py
"""

from __future__ import annotations

import faulthandler
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workloads.io_bound_sleep import handle_request  # noqa: E402


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_enable() -> None:
    section("1. faulthandler.enable() - safety net for fatal errors")
    faulthandler.enable()
    print("faulthandler.enable() called.")
    print("From now on, if the interpreter crashes with a segfault, SIGABRT,")
    print("SIGBUS, SIGFPE, or SIGILL, Python will print all thread stacks to")
    print("stderr before dying - even though the crash is in C code that")
    print("would normally give you nothing but 'Segmentation fault'.")
    print("(We don't trigger a real crash here - too disruptive for a demo -")
    print(" but try: faulthandler.enable(); import ctypes; ctypes.string_at(0)")


def demo_dump_traceback_now() -> None:
    """dump_traceback() prints stacks for ALL threads immediately."""
    section("2. faulthandler.dump_traceback() - dump ALL thread stacks now")

    # Start a couple of background threads doing "work" so the dump has
    # more than one stack to show.
    stop = threading.Event()

    def background_worker(name: str) -> None:
        while not stop.is_set():
            time.sleep(0.05)

    threads = [
        threading.Thread(target=background_worker, args=(f"bg-{i}",), name=f"bg-{i}", daemon=True)
        for i in range(2)
    ]
    for t in threads:
        t.start()

    time.sleep(0.1)  # let them get into time.sleep
    print("Dumping tracebacks for the main thread + 2 background threads:\n")
    faulthandler.dump_traceback()  # writes to sys.stderr by default

    stop.set()
    for t in threads:
        t.join()


def demo_dump_traceback_to_file(tmp_path: Path) -> None:
    """You can also redirect the dump to a file descriptor (e.g. a log file)."""
    section("3. faulthandler.dump_traceback(file=...) - dump to a file")
    with open(tmp_path, "w") as f:
        faulthandler.dump_traceback(file=f)
    print(f"Wrote a stack dump to {tmp_path}")
    print("--- file contents ---")
    print(tmp_path.read_text())


def demo_dump_traceback_later() -> None:
    """The 'dead man's switch': dump stacks if we're still running after N seconds.

    In production you'd set this to something like 30-60 seconds at the top
    of a request handler, and call ``cancel()`` when the request finishes
    normally. If the handler hangs, you get a stack dump in your logs
    without any manual intervention.
    """
    section("4. faulthandler.dump_traceback_later(timeout) - hang watchdog")

    print("Arming a 1-second watchdog...")
    faulthandler.dump_traceback_later(1.0, exit=False)

    print("Simulating slow work (sleeping 1.5s, so the watchdog fires)...")
    time.sleep(1.5)

    # In real code you'd call this as soon as the "request" finishes
    # successfully, so the watchdog never fires for healthy requests.
    faulthandler.cancel_dump_traceback_later()
    print("Work finished; watchdog cancelled.")


def demo_io_bound_dump() -> None:
    """Dump stacks while threads are parked in time.sleep (I/O simulation)."""
    section("5. Dumping stacks while threads sleep (I/O-bound workload)")

    threads = [
        threading.Thread(target=handle_request, args=(i, 0.3), name=f"io-{i}")
        for i in range(3)
    ]
    for t in threads:
        t.start()

    time.sleep(0.05)  # let them enter time.sleep
    faulthandler.dump_traceback()

    for t in threads:
        t.join()


if __name__ == "__main__":
    demo_enable()
    demo_dump_traceback_now()
    demo_dump_traceback_to_file(Path(__file__).parent / "_faulthandler_dump.txt")
    demo_dump_traceback_later()
    demo_io_bound_dump()
