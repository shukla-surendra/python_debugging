"""tracemalloc - stdlib memory profiler with source-line attribution.

Unlike sys.getsizeof (one object at a time), tracemalloc tracks EVERY
allocation made by Python's memory allocator and remembers *where* (which
file/line, optionally full traceback) each allocation came from.

Core API:

- ``tracemalloc.start(nframes)`` - begin tracing; nframes = how many stack
  frames to remember per allocation (more frames = more detail, more overhead)
- ``tracemalloc.take_snapshot()`` - capture "everything allocated right now"
- ``snapshot.statistics(key_type)`` - group allocations by 'lineno',
  'filename', or 'traceback'
- ``tracemalloc.get_traced_memory()`` - quick (current, peak) totals

Run:
    python 02_tracemalloc_basics.py
"""

from __future__ import annotations

import sys
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workloads.memory_leak import (  # noqa: E402
    leak_via_global_cache,
    leak_via_reference_cycle,
)


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_basic_snapshot() -> None:
    section("1. tracemalloc.start() + take_snapshot() + top statistics")

    tracemalloc.start()

    leak_via_global_cache(iterations=500, item_size=8_000)
    leak_via_reference_cycle(pairs=100)

    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics("lineno")

    print("Top 5 allocations by line:")
    for stat in top_stats[:5]:
        print(f"  {stat}")

    tracemalloc.stop()


def demo_current_and_peak() -> None:
    """get_traced_memory() gives a cheap running total without a snapshot."""
    section("2. tracemalloc.get_traced_memory() - cheap running totals")

    tracemalloc.start()

    current, peak = tracemalloc.get_traced_memory()
    print(f"Before allocation: current={current} bytes, peak={peak} bytes")

    big_list = [bytearray(100_000) for _ in range(20)]

    current, peak = tracemalloc.get_traced_memory()
    print(f"After allocating 20x100KB: current={current} bytes, peak={peak} bytes")

    del big_list

    current, peak = tracemalloc.get_traced_memory()
    print(f"After del: current={current} bytes, peak={peak} bytes (peak doesn't decrease)")

    tracemalloc.stop()


def demo_traceback_grouping() -> None:
    """Group by 'traceback' (not just 'lineno') to see the FULL call chain."""
    section("3. Grouping by 'traceback' - see the full call stack of an allocation")

    tracemalloc.start(10)  # remember up to 10 frames per allocation

    def make_cache_entries():
        return leak_via_global_cache(iterations=200, item_size=4_000)

    make_cache_entries()

    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics("traceback")

    top = top_stats[0]
    print(f"#1 allocation site: {top.size / 1024:.1f} KiB in {top.count} blocks")
    print("Traceback (most recent call last):")
    for line in top.traceback.format():
        print(f"  {line}")

    tracemalloc.stop()


def demo_filters() -> None:
    """Filter out noise (e.g. tracemalloc's own frames, stdlib internals)."""
    section("4. Filtering snapshots to focus on YOUR code")

    tracemalloc.start()
    leak_via_global_cache(iterations=300, item_size=2_000)
    snapshot = tracemalloc.take_snapshot()

    # Only show allocations from our workloads/ package.
    workloads_filter = tracemalloc.Filter(inclusive=True, filename_pattern="*/workloads/*")
    filtered = snapshot.filter_traces([workloads_filter])

    print("Allocations from workloads/* only:")
    for stat in filtered.statistics("lineno")[:5]:
        print(f"  {stat}")

    tracemalloc.stop()


if __name__ == "__main__":
    demo_basic_snapshot()
    demo_current_and_peak()
    demo_traceback_grouping()
    demo_filters()
