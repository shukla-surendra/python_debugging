"""cProfile + pstats - the stdlib deterministic profiler.

cProfile instruments every function call/return (implemented in C, so it's
much faster than the pure-Python `profile` module, but still has real
overhead - typically slows code down by 30-100%, more for code with many
small function calls).

Three ways to invoke it, all shown below:

1. ``cProfile.run("expr")``           - quick and dirty, profiles a string of code
2. ``cProfile.Profile()`` as a context - profile an arbitrary block
3. ``@profile`` style via ``runcall``  - profile a single function call

Then ``pstats.Stats`` lets you sort and filter the results.

Run:
    python 01_cprofile_basics.py
"""

from __future__ import annotations

import cProfile
import pstats
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workloads.cpu_bound import one_round  # noqa: E402


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_profile_context_manager() -> pstats.Stats:
    """cProfile.Profile() used as a context manager (Python 3.8+)."""
    section("1. cProfile.Profile() as a context manager")

    profiler = cProfile.Profile()
    with profiler:
        for _ in range(3):
            one_round(size=100_000, fib_n=16)

    stats = pstats.Stats(profiler)
    return stats


def demo_sort_by_cumulative(stats: pstats.Stats) -> None:
    """Sort by CUMULATIVE time (time in function + all functions it called).

    Cumulative time is what you want when hunting for "which top-level call
    is expensive" - it tells you where to start digging.
    """
    section("2. Top functions by CUMULATIVE time")
    stats.sort_stats(pstats.SortKey.CUMULATIVE)
    stats.print_stats(8)


def demo_sort_by_tottime(stats: pstats.Stats) -> None:
    """Sort by TOTTIME (time in the function itself, excluding sub-calls).

    Tottime is what you want when hunting for "which function's OWN code
    is the bottleneck" - e.g. a tight loop, vs. a thin wrapper that just
    calls something else.
    """
    section("3. Top functions by TOTTIME (own time, excludes sub-calls)")
    stats.sort_stats(pstats.SortKey.TIME)
    stats.print_stats(8)


def demo_callers_callees(stats: pstats.Stats) -> None:
    """Who calls `fibonacci`, and what does `one_round` call?"""
    section("4. print_callees() - what does one_round() call, and how much time?")
    stats.sort_stats(pstats.SortKey.CUMULATIVE)
    stats.print_callees("one_round")

    section("5. print_callers() - who calls fibonacci(), and how often?")
    stats.print_callers("fibonacci")


def demo_runcall() -> None:
    """cProfile.Profile().runcall(fn, *args) - profile a single call directly."""
    section("6. Profile.runcall() - profile one function call")
    profiler = cProfile.Profile()
    profiler.runcall(one_round, size=200_000, fib_n=18)
    stats = pstats.Stats(profiler)
    stats.sort_stats(pstats.SortKey.CUMULATIVE)
    stats.print_stats(5)


def demo_cprofile_run_string() -> None:
    """cProfile.run("code string") - quickest way to profile a snippet."""
    section("7. cProfile.run('code string') - profile a code snippet")
    cProfile.run(
        "from workloads.cpu_bound import fibonacci; fibonacci(20)",
        sort=pstats.SortKey.CUMULATIVE,
    )


if __name__ == "__main__":
    stats = demo_profile_context_manager()
    demo_sort_by_cumulative(stats)
    demo_sort_by_tottime(stats)
    demo_callers_callees(stats)
    demo_runcall()
    demo_cprofile_run_string()
