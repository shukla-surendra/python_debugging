"""tracemalloc snapshot diffing - finding what GREW between two points in time.

A single snapshot tells you "what's allocated now". A *diff* between two
snapshots tells you "what changed" - which is what you actually want when
hunting a leak: take a baseline, run some iterations, take another
snapshot, and look at `snapshot2.compare_to(snapshot1, ...)`.

This script simulates a realistic debugging session:

1. Take a baseline snapshot.
2. Run several "request" iterations against a leaky function.
3. Take another snapshot and diff - the leaking line should dominate.
4. Repeat for a HEALTHY function and confirm the diff shows ~nothing.

Run:
    python 03_tracemalloc_snapshot_diff.py
"""

from __future__ import annotations

import sys
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workloads.memory_leak import (  # noqa: E402
    clear_global_cache,
    healthy_allocation,
    leak_via_global_cache,
)


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_diff_leaky_loop() -> None:
    section("1. Diffing across iterations of a LEAKY function")

    clear_global_cache()
    tracemalloc.start()

    snapshot_before = tracemalloc.take_snapshot()

    for iteration in range(3):
        # start= ensures each iteration inserts NEW keys, so the cache
        # (and the diff vs. the very first snapshot) keeps growing.
        leak_via_global_cache(iterations=200, item_size=5_000, start=iteration * 200)
        snapshot_after = tracemalloc.take_snapshot()

        diff = snapshot_after.compare_to(snapshot_before, "lineno")
        top = diff[0]
        print(f"After iteration {iteration + 1}: top growth = {top}")

        # Note: we deliberately do NOT update snapshot_before, so each diff
        # is "vs. the very start" - growth should be roughly linear with
        # iteration count if the leak is steady.

    tracemalloc.stop()
    clear_global_cache()


def demo_diff_healthy_loop() -> None:
    section("2. Diffing across iterations of a HEALTHY function (for contrast)")

    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()

    for iteration in range(3):
        healthy_allocation(iterations=200, item_size=5_000)
        snapshot_after = tracemalloc.take_snapshot()

        diff = snapshot_after.compare_to(snapshot_before, "lineno")
        # Only show entries with non-trivial growth.
        significant = [d for d in diff if d.size_diff > 1024]
        if significant:
            print(f"After iteration {iteration + 1}: {significant[0]}")
        else:
            print(f"After iteration {iteration + 1}: no significant growth "
                  f"(largest diff: {diff[0].size_diff} bytes)")

    tracemalloc.stop()


def demo_consecutive_diffs_show_steady_growth() -> None:
    """Diff consecutive snapshots (not vs. a fixed baseline) to see PER-ROUND growth."""
    section("3. Consecutive (rolling) diffs - growth PER ROUND, not cumulative")

    clear_global_cache()
    tracemalloc.start()

    previous = tracemalloc.take_snapshot()
    for iteration in range(3):
        # start= ensures each round inserts NEW keys (real growth), not
        # overwrites of the same 100 keys.
        leak_via_global_cache(iterations=100, item_size=10_000, start=iteration * 100)
        current = tracemalloc.take_snapshot()

        diff = current.compare_to(previous, "lineno")
        top = diff[0]
        print(f"Round {iteration + 1} added: {top.size_diff / 1024:.1f} KiB "
              f"({top.count_diff} blocks) at {top.traceback}")

        previous = current  # roll forward - next diff is vs. THIS snapshot

    tracemalloc.stop()
    clear_global_cache()
    print("\nSteady ~1000 KiB growth per round (100 * 10_000 bytes) is the")
    print("signature of an unbounded cache: a real bug would look exactly")
    print("like this in production metrics (RSS climbing by a fixed amount")
    print("per request/batch/job).")


if __name__ == "__main__":
    demo_diff_leaky_loop()
    demo_diff_healthy_loop()
    demo_consecutive_diffs_show_steady_growth()
