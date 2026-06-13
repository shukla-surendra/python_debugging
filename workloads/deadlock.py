"""A program that (optionally) deadlocks itself with two threads acquiring
two locks in opposite order - the textbook "lock ordering" deadlock.

Used in 01_stack_dumps and 04_concurrency_debugging to demonstrate how to
diagnose a hung process using ``faulthandler``, ``py-spy dump``, and
``threading.enumerate()`` - none of which require the process to crash or
exit on its own.

Run it directly. By default it deadlocks within ~1 second and then just
hangs forever - that's the point! Use a separate terminal (or another tool)
to inspect it while it's stuck:

    python workloads/deadlock.py
    # in another terminal:
    py-spy dump --pid <pid>

Pass ``--safe`` to run the same two workers WITHOUT the lock-ordering bug,
so you can compare a healthy run to a deadlocked one.
"""

from __future__ import annotations

import argparse
import threading
import time

lock_a = threading.Lock()
lock_b = threading.Lock()


def worker_1(safe: bool) -> None:
    with lock_a:
        print("[worker-1] acquired lock_a")
        time.sleep(0.5)  # give worker-2 time to acquire lock_b
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


def run(safe: bool = False) -> None:
    t1 = threading.Thread(target=worker_1, args=(safe,), name="deadlock-worker-1")
    t2 = threading.Thread(target=worker_2, args=(safe,), name="deadlock-worker-2")
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    print("Both workers finished without deadlocking.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--safe", action="store_true",
                         help="Acquire locks in a consistent order (no deadlock).")
    args = parser.parse_args()

    print(f"PID = {__import__('os').getpid()}  (use this PID with py-spy / faulthandler)")
    if args.safe:
        run(safe=True)
    else:
        print("Running WITHOUT --safe: this will deadlock and hang forever.")
        run(safe=False)
