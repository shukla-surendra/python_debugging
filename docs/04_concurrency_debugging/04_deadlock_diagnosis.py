"""Diagnosing (and fixing) a classic lock-ordering deadlock.

`workloads/deadlock.py` is a standalone script you can run in another
terminal and inspect with `py-spy dump` (see `01_stack_dumps/06_py_spy_dump.md`
for that exercise). This script demonstrates the IN-PROCESS diagnosis tool:
``faulthandler.dump_traceback_later()`` as an automatic "if we're not done in
N seconds, dump every thread's stack" watchdog - the thing you'd leave armed
in a production service so a hang produces a diagnostic dump in the logs
instead of just... silence.

It then shows the fix (consistent lock ordering) and the
"detect and recover" alternative (`Lock.acquire(timeout=...)`).

Run:
    python 04_deadlock_diagnosis.py
"""

from __future__ import annotations

import faulthandler
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def make_workers(lock_a: threading.Lock, lock_b: threading.Lock):
    """Build worker_1/worker_2 closures over a FRESH pair of locks.

    Mirrors workloads/deadlock.py, but parameterized so each demo gets its
    own locks - reusing the module-level locks across demos would mean a
    deadlocked demo leaves them held forever, wedging every later demo too.
    """

    def worker_1() -> None:
        with lock_a:
            print("[worker-1] acquired lock_a")
            time.sleep(0.5)
            print("[worker-1] waiting for lock_b...")
            with lock_b:
                print("[worker-1] acquired lock_b")
        print("[worker-1] done")

    def worker_2(safe: bool) -> None:
        first, second, first_name, second_name = (
            (lock_b, lock_a, "lock_b", "lock_a") if not safe
            else (lock_a, lock_b, "lock_a", "lock_b")
        )
        with first:
            print(f"[worker-2] acquired {first_name}")
            time.sleep(0.5)
            print(f"[worker-2] waiting for {second_name}...")
            with second:
                print(f"[worker-2] acquired {second_name}")
        print("[worker-2] done")

    return worker_1, worker_2


def demo_watchdog_catches_deadlock() -> None:
    """Arm a dump-traceback watchdog BEFORE triggering the deadlock."""
    section("1. faulthandler.dump_traceback_later() as a hang watchdog")

    lock_a = threading.Lock()
    lock_b = threading.Lock()
    worker_1, worker_2 = make_workers(lock_a, lock_b)

    print("Arming a 2-second watchdog, then starting two workers that will")
    print("deadlock by acquiring lock_a/lock_b in opposite orders...\n")

    # If the process is still running 2s from now, dump every thread's stack
    # to stdout, once (repeat=False), without exiting the process.
    faulthandler.dump_traceback_later(2.0, repeat=False, exit=False, file=sys.stdout)

    t1 = threading.Thread(target=worker_1, name="deadlock-worker-1", daemon=True)
    t2 = threading.Thread(target=worker_2, args=(False,), name="deadlock-worker-2", daemon=True)
    t1.start()
    t2.start()

    time.sleep(2.5)  # long enough for the deadlock AND the watchdog dump
    faulthandler.cancel_dump_traceback_later()

    print("\n(The two threads above are now permanently deadlocked - they are")
    print("daemon threads, so this script can still exit normally without")
    print("waiting for them.)")
    print()
    print("Notice both threads show as '[deadlock-worker]', NOT")
    print("'deadlock-worker-1'/'-2' - on Linux, OS thread names are truncated")
    print("to 15 characters (pthread_setname_np's limit). Keep thread name")
    print("PREFIXES short and put the distinguishing part first, e.g.")
    print("'w1-deadlock'/'w2-deadlock', if you need dumps to disambiguate them.")


def demo_reading_the_dump() -> None:
    """Explain what to look for in the watchdog dump from demo 1."""
    section("2. Reading the dump: spotting a lock-ordering deadlock")

    print("In the dump above, both 'deadlock-worker-1' and 'deadlock-worker-2'")
    print("show a frame like:")
    print()
    print('  File ".../04_deadlock_diagnosis.py", line NN in worker_N')
    print('  File "/usr/lib/python3.X/threading.py", line NN in __enter__')
    print('  File "/usr/lib/python3.X/threading.py", line NN in acquire')
    print()
    print("Both threads are stuck in `Lock.acquire()` (called via `with lock:`).")
    print("The diagnostic questions:")
    print()
    print("  1. Are multiple threads stuck in `acquire`, each on a DIFFERENT")
    print("     lock object? -> likely lock-ordering deadlock (this case).")
    print("  2. Is only ONE thread stuck in `acquire`, others idle? -> that")
    print("     lock is just being held too long by whoever has it (check")
    print("     which thread's dump frame is NOT in `acquire` - that's the")
    print("     holder; look at what IT is doing).")
    print()
    print("To confirm WHICH locks: print `id(lock_a)`/`id(lock_b)` (or give")
    print("locks names via a small wrapper class) so the dump's '<...>' repr")
    print("can be matched back to source - bare `threading.Lock` objects don't")
    print("show useful reprs by default.")


def demo_consistent_lock_ordering_fixes_it() -> None:
    """The real fix: every thread acquires locks in the SAME order."""
    section("3. The fix: a global, consistent lock-acquisition order")

    lock_a = threading.Lock()
    lock_b = threading.Lock()
    worker_1, worker_2 = make_workers(lock_a, lock_b)

    print("Same two workers, but worker_2 now acquires lock_a THEN lock_b -")
    print("the same order as worker_1 (safe=True):\n")

    t1 = threading.Thread(target=worker_1, name="safe-worker-1")
    t2 = threading.Thread(target=worker_2, args=(True,), name="safe-worker-2")
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    if t1.is_alive() or t2.is_alive():
        print("\nStill stuck?! (unexpected)")
    else:
        print("\nBoth workers finished - no deadlock. The rule: if ANY two")
        print("threads might hold lock_a and lock_b at the same time, EVERY")
        print("such thread must acquire them in the same order (e.g. always")
        print("alphabetical/ID order). This is the standard fix and has zero")
        print("runtime cost.")


def demo_timeout_based_avoidance() -> None:
    """Alternative: acquire(timeout=...) turns a deadlock into a recoverable failure."""
    section("4. Alternative: Lock.acquire(timeout=...) - detect and back off")

    lock_a = threading.Lock()

    lock_a.acquire()
    print("Main thread holds lock_a.")

    got_it = lock_a.acquire(timeout=0.2)
    print(f"Second acquire(timeout=0.2) from the same thread returned: {got_it}")
    if not got_it:
        print("(returned False after ~0.2s instead of blocking forever)")

    lock_a.release()

    print()
    print("In a real lock-ordering scenario, `acquire(timeout=...)` lets a")
    print("thread give up, RELEASE any locks it already holds, and retry -")
    print("turning a permanent deadlock into a transient slowdown (with")
    print("retries/backoff). It doesn't prevent the underlying ordering bug,")
    print("but it keeps the process alive and visible in metrics/logs instead")
    print("of silently hanging forever - often the pragmatic first mitigation")
    print("while the real fix (consistent ordering) is rolled out.")


if __name__ == "__main__":
    demo_watchdog_catches_deadlock()
    demo_reading_the_dump()
    demo_consistent_lock_ordering_fixes_it()
    demo_timeout_based_avoidance()
