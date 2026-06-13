"""A deliberately CPU-heavy program used as the "victim" for CPU profilers
and stack-sampling tools (cProfile, line_profiler, pyinstrument, py-spy, scalene).

It mixes three different hot spots so that profilers have something
interesting to report:

1. ``sum_of_squares``      - a tight numeric loop (pure CPU, no allocations)
2. ``string_churn``        - lots of small string allocations (object churn)
3. ``fibonacci``            - recursive function calls (call-graph depth)

Run it directly to just burn CPU for a while:

    python workloads/cpu_bound.py
    python workloads/cpu_bound.py --seconds 5
"""

from __future__ import annotations

import argparse
import time


def sum_of_squares(n: int) -> int:
    """Pure numeric loop - dominated by interpreter bytecode dispatch."""
    total = 0
    for i in range(n):
        total += i * i
    return total


def string_churn(n: int) -> int:
    """Allocate and discard many small strings/lists."""
    total = 0
    for i in range(n):
        s = f"row-{i}-{i * i}"
        total += len(s)
    return total


def fibonacci(n: int) -> int:
    """Naive recursive fibonacci - exercises the call stack heavily."""
    if n < 2:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)


def one_round(size: int = 200_000, fib_n: int = 18) -> None:
    """One unit of work combining all three hot spots."""
    sum_of_squares(size)
    string_churn(size // 4)
    fibonacci(fib_n)


def run(seconds: float | None = None, rounds: int | None = None) -> None:
    """Run rounds of work either for a fixed duration or a fixed count.

    Exactly one of ``seconds`` / ``rounds`` should be given. If neither is
    given, run forever (useful for attaching py-spy/scalene to a live PID).
    """
    start = time.perf_counter()
    completed = 0
    while True:
        one_round()
        completed += 1
        if rounds is not None and completed >= rounds:
            break
        if seconds is not None and (time.perf_counter() - start) >= seconds:
            break
        if rounds is None and seconds is None and completed % 5 == 0:
            # Heartbeat so it's obvious the process is alive when run forever.
            print(f"... completed {completed} rounds, "
                  f"{time.perf_counter() - start:.1f}s elapsed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=None,
                         help="Run for this many seconds, then exit.")
    parser.add_argument("--rounds", type=int, default=None,
                         help="Run this many rounds, then exit.")
    args = parser.parse_args()

    if args.seconds is None and args.rounds is None:
        args.rounds = 20  # sensible default so the script terminates

    run(seconds=args.seconds, rounds=args.rounds)
