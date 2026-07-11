"""pympler - heap composition snapshots, growth tracking, and deep sizes.

pympler overlaps with tracemalloc/objgraph but focuses on **class-level**
heap composition rather than line-of-allocation. Three pieces used here:

- ``pympler.asizeof.asizeof(obj)``  - DEEP size of an object, following
  references (unlike `sys.getsizeof`, which is shallow).
- ``pympler.muppy`` + ``pympler.summary`` - "summarize everything on the
  heap right now, grouped by type".
- ``pympler.tracker.SummaryTracker`` - the diffing tool: `print_diff()`
  shows what changed in the heap since the last call.

Run:
    python 06_pympler_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from pympler import asizeof, muppy, summary, tracker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from workloads.memory_leak import (  # noqa: E402
    Node,
    clear_global_cache,
    leak_via_global_cache,
    leak_via_reference_cycle,
)


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_asizeof() -> None:
    """asizeof follows references - the 'deep size' sys.getsizeof can't give you."""
    section("1. asizeof.asizeof() - deep size, following references")

    plain_list = [0, 1, 2]
    list_of_buffers = [bytearray(50_000) for _ in range(10)]
    node = Node("demo")

    print(f"asizeof([0, 1, 2])                 = {asizeof.asizeof(plain_list)} bytes")
    print(f"asizeof([10x 50KB bytearrays])      = {asizeof.asizeof(list_of_buffers)} bytes")
    print(f"asizeof(Node instance)              = {asizeof.asizeof(node)} bytes "
          f"(includes its 50KB payload bytearray)")


def demo_heap_summary() -> None:
    """summary.summarize() - a snapshot of the whole heap by type."""
    section("2. muppy + summary - 'what's on the heap right now, by type'")

    all_objects = muppy.get_objects()
    summ = summary.summarize(all_objects)
    # print_ sorts by total size descending.
    summary.print_(summ, limit=8)


def demo_summary_tracker() -> None:
    """SummaryTracker.print_diff() - the pympler equivalent of a tracemalloc diff."""
    section("3. tracker.SummaryTracker - diff the heap across a leaky call")

    clear_global_cache()
    tr = tracker.SummaryTracker()

    leak_via_global_cache(iterations=500, item_size=8_000)

    print("Heap diff after leak_via_global_cache(iterations=500, item_size=8000):")
    tr.print_diff()


def demo_summary_tracker_multiple_rounds() -> None:
    """Call print_diff() repeatedly to watch growth round over round."""
    section("4. Repeated SummaryTracker.print_diff() across rounds")

    clear_global_cache()
    tr = tracker.SummaryTracker()

    for round_num in range(2):
        leak_via_reference_cycle(pairs=40)
        print(f"\n--- Diff after round {round_num + 1} (40 more Node pairs) ---")
        tr.print_diff()

    print("\nNotice: no 'Node' or 'bytearray' growth shows up here, even")
    print("though leak_via_reference_cycle() creates 80 Nodes with 50KB")
    print("payloads per round! That's because its return value (the `created`")
    print("list) is discarded immediately - the only remaining references are")
    print("the a<->b cycle itself, which CPython's generational cyclic GC")
    print("finds and frees on its own. This is the key difference from")
    print("leak_via_global_cache() in section 3: that one has an EXTERNAL")
    print("reference (_GLOBAL_CACHE) keeping every entry alive forever - no")
    print("amount of gc.collect() will free it. See 07_gc_module_demo.py.")


if __name__ == "__main__":
    demo_asizeof()
    demo_heap_summary()
    demo_summary_tracker()
    demo_summary_tracker_multiple_rounds()
