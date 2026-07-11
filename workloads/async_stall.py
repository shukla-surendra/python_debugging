"""An asyncio program that (optionally) stalls its own event loop.

asyncio is single-threaded cooperative concurrency: exactly one coroutine
runs at a time, until it hits an ``await`` that yields control. If a
coroutine does blocking work WITHOUT awaiting - a synchronous ``time.sleep``,
a CPU-bound loop, a blocking DB/HTTP call - it freezes the ENTIRE event
loop. Every other task, timer, and callback waits behind it.

This is the "one slow request delayed ALL requests" bug. It's the asyncio
victim program for:

- 04_concurrency_debugging/02_asyncio_debug_mode.py  (debug-mode warnings)
- 04_concurrency_debugging/05_viztracer_timeline.md  (see the stall on a timeline)

Run it and watch the heartbeat: it should tick every 0.1s, but each request
that calls the BLOCKING handler freezes it for ~1s.

    python workloads/async_stall.py
    # in another terminal, see the slow-callback warnings it logs, or:
    #   viztracer --log_async -o result.json workloads/async_stall.py

Pass ``--safe`` to run the same workload correctly (blocking work pushed to a
thread executor, real awaits), so the heartbeat stays smooth - compare the
two runs, especially on a VizTracer timeline.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time


def cpu_bound_work(n: int) -> int:
    """Deliberately synchronous, blocking CPU work (no awaits)."""
    total = 0
    for i in range(n):
        total += i * i
    return total


async def heartbeat() -> None:
    """Should tick every 0.1s. Stutters whenever the loop is blocked."""
    last = time.perf_counter()
    while True:
        await asyncio.sleep(0.1)
        now = time.perf_counter()
        drift = (now - last) - 0.1
        # ~tens of ms of jitter is normal (GIL contention); a real loop stall
        # is hundreds of ms to seconds.
        flag = "  <-- STALLED" if drift > 0.1 else ""
        print(f"[heartbeat] tick (drift {drift * 1000:6.1f} ms){flag}")
        last = now


async def handle_request(req_id: int, safe: bool) -> None:
    print(f"[request {req_id}] start")
    if safe:
        # Correct: hand blocking work to a thread so the loop keeps running.
        await asyncio.to_thread(cpu_bound_work, 20_000_000)
    else:
        # Bug: run blocking work directly in the coroutine - freezes the loop.
        cpu_bound_work(20_000_000)
    print(f"[request {req_id}] done")


async def main(safe: bool) -> None:
    hb = asyncio.create_task(heartbeat(), name="heartbeat")
    # Simulate several requests arriving while the heartbeat runs.
    for req_id in range(5):
        await handle_request(req_id, safe)
        await asyncio.sleep(0.05)
    hb.cancel()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--safe", action="store_true",
                        help="Push blocking work to a thread executor (no loop stall).")
    args = parser.parse_args()

    print(f"PID = {os.getpid()}")
    print(f"Running {'WITH --safe (smooth heartbeat)' if args.safe else 'WITHOUT --safe: the heartbeat will stall'}")
    # debug=True makes asyncio log 'Executing <...> took X seconds' for slow callbacks.
    asyncio.run(main(args.safe), debug=True)
