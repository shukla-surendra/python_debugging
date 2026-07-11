"""Stack dumps for multi-threaded programs: naming threads, spotting idle vs
busy workers, and seeing the GIL's effect on parallelism.

Module 1 (`01_stack_dumps/`) covered the MECHANICS of dumping stacks
(`faulthandler`, `sys._current_frames`, `threading.enumerate`). This script
applies those mechanics to questions specific to THREADED programs:

1. **"Which worker is which?"** - dumps are useless if every thread shows up
   as `Thread-7 (cpu_worker)`. Naming threads makes dumps self-explanatory.
2. **"Is this thread stuck, or just idle waiting for work?"** - a thread
   blocked on `Event.wait()` / `queue.get()` has a recognizable frame, totally
   different from one spinning in a loop.
3. **"Why doesn't adding more threads make my CPU-bound code faster?"** - the
   GIL means only one thread runs Python bytecode at a time. A stack dump
   alone won't show you this directly, but a timing comparison
   (threads vs. processes) makes it concrete.

Run:
    python 01_thread_stack_dumps.py
"""

from __future__ import annotations

import faulthandler
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workloads.cpu_bound import sum_of_squares  # noqa: E402
from workloads.io_bound_sleep import handle_request  # noqa: E402


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_named_thread_dump() -> None:
    """Name your threads - it's the difference between a useless and a useful dump."""
    section("1. Named threads in a faulthandler dump")

    stop = threading.Event()

    def cpu_worker() -> None:
        while not stop.is_set():
            sum_of_squares(2_000_000)

    def io_worker() -> None:
        while not stop.is_set():
            handle_request(request_id=0, latency=0.05)

    threads = [
        threading.Thread(target=cpu_worker, name="cpu-worker-0", daemon=True),
        threading.Thread(target=cpu_worker, name="cpu-worker-1", daemon=True),
        threading.Thread(target=io_worker, name="io-worker-0", daemon=True),
    ]
    for t in threads:
        t.start()

    time.sleep(0.1)  # let them all get into their loops
    print("faulthandler.dump_traceback(all_threads=True):\n")
    faulthandler.dump_traceback(all_threads=True, file=sys.stdout)

    stop.set()
    for t in threads:
        t.join()

    print("\nWithout `name=...`, these would show up as 'Thread-1 (cpu_worker)',")
    print("'Thread-2 (cpu_worker)', 'Thread-3 (io_worker)' - same function name,")
    print("indistinguishable. `threading.Thread(..., name='cpu-worker-0')` costs")
    print("nothing and turns every future dump/py-spy/gdb backtrace into")
    print("self-documenting output. Set it for every long-lived worker thread.")


def demo_blocked_vs_busy_thread() -> None:
    """A thread's stack frame tells you whether it's WORKING or WAITING."""
    section("2. Distinguishing a busy worker from an idle one via its stack")

    busy_stop = threading.Event()
    idle_release = threading.Event()

    def busy_worker() -> None:
        while not busy_stop.is_set():
            sum_of_squares(2_000_000)

    def idle_worker() -> None:
        idle_release.wait()  # blocks here until released - simulates "no work queued"

    t_busy = threading.Thread(target=busy_worker, name="busy-worker", daemon=True)
    t_idle = threading.Thread(target=idle_worker, name="idle-worker", daemon=True)
    t_busy.start()
    t_idle.start()

    time.sleep(0.1)
    print("faulthandler.dump_traceback(all_threads=True):\n")
    faulthandler.dump_traceback(all_threads=True, file=sys.stdout)

    busy_stop.set()
    idle_release.set()
    t_busy.join()
    t_idle.join()

    print("\n'busy-worker' is deep inside sum_of_squares (the for-loop in")
    print("workloads/cpu_bound.py). 'idle-worker' is sitting in")
    print("threading.Event.wait() -> Condition.wait() -> a stdlib lock primitive.")
    print()
    print("This is the FIRST thing to check when a thread pool 'isn't doing")
    print("anything': are the worker threads parked in Event.wait/queue.get")
    print("(genuinely idle - no work submitted) or are they all busy in")
    print("application code (saturated - need more workers or faster code)?")


def demo_gil_limits_thread_parallelism() -> None:
    """Threads vs. processes for the SAME pure-Python CPU work."""
    section("3. The GIL: why threads don't speed up CPU-bound Python")

    n = 8_000_000
    work_items = [n] * 4

    start = time.perf_counter()
    for item in work_items:
        sum_of_squares(item)
    sequential_time = time.perf_counter() - start

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(sum_of_squares, work_items))
    threaded_time = time.perf_counter() - start

    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=4) as pool:
        list(pool.map(sum_of_squares, work_items))
    process_time = time.perf_counter() - start

    print(f"4x sum_of_squares({n:,}), one after another (1 thread): {sequential_time:.2f}s")
    print(f"Same 4x, spread across 4 THREADS:                        {threaded_time:.2f}s")
    print(f"Same 4x, spread across 4 PROCESSES:                      {process_time:.2f}s")
    print()
    print("Threads finish in roughly the SAME time as sequential, or even WORSE")
    print("(GIL hand-off between threads has real overhead - the OS keeps waking")
    print("up threads that immediately find the GIL held and go back to sleep).")
    print("The Global Interpreter Lock only lets ONE thread execute Python")
    print("bytecode at a time. Processes have their own GIL each, so they run")
    print("genuinely in parallel on multi-core machines and finish faster.")
    print()
    print("A stack dump of the threaded version would show all 4 threads with")
    print("valid-looking frames inside sum_of_squares - dumps don't directly")
    print("show 'who currently holds the GIL'. The TELL is in timing/CPU%:")
    print("`top -H` would show ~100% total CPU for the threaded version")
    print("(one core maxed) vs. ~400% for the multiprocess version (4 cores).")
    print()
    print("This is why CPU-bound work uses multiprocessing/subprocesses, while")
    print("threads remain useful for I/O-bound work (the GIL is released during")
    print("blocking I/O - see workloads/io_bound_sleep.py and module 2's notes).")


if __name__ == "__main__":
    demo_named_thread_dump()
    demo_blocked_vs_busy_thread()
    demo_gil_limits_thread_parallelism()
