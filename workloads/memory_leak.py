"""A program with a few classic memory-growth patterns, used as the
"victim" for memory profilers (tracemalloc, memory_profiler, objgraph,
pympler, memray, gc).

Each pattern is isolated in its own function so you can profile them
independently:

* ``leak_via_global_cache``  - an ever-growing module-level dict (the most
  common real-world leak: an unbounded cache).
* ``leak_via_reference_cycle`` - objects that reference each other and rely
  on the cyclic GC to be collected.
* ``leak_via_closure``        - closures that capture (and keep alive) large
  objects far longer than intended.
* ``healthy_allocation``      - allocates and *correctly* releases memory,
  for contrast.

Run it directly to execute all patterns once each:

    python workloads/memory_leak.py
"""

from __future__ import annotations

import gc


# Module-level "cache" that we forget to bound -> classic leak.
_GLOBAL_CACHE: dict[str, bytes] = {}


def leak_via_global_cache(iterations: int = 1000, item_size: int = 10_000, start: int = 0) -> None:
    """Simulate an unbounded cache: each key is unique, nothing is evicted.

    ``start`` lets repeated calls add NEW keys instead of overwriting the
    same ``iterations`` keys every time - use an increasing ``start`` (e.g.
    ``round_number * iterations``) to simulate steady growth across many
    calls (requests/batches/jobs).
    """
    for i in range(start, start + iterations):
        _GLOBAL_CACHE[f"key-{i}"] = b"x" * item_size


class Node:
    """A node that can point at another node, forming a cycle."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.other: "Node | None" = None
        self.payload = bytearray(50_000)  # make each node "heavy"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Node({self.name!r})"


def leak_via_reference_cycle(pairs: int = 200) -> list[Node]:
    """Create reference cycles (a -> b -> a).

    These are NOT leaked permanently in CPython because the generational
    garbage collector *can* find and free cycles - but until ``gc.collect()``
    runs, they inflate memory, and if any object in the cycle defines
    ``__del__`` in old Python versions they could become truly uncollectable.
    Returned so callers can choose to drop references and/or call gc.collect().
    """
    created = []
    for i in range(pairs):
        a = Node(f"a{i}")
        b = Node(f"b{i}")
        a.other = b
        b.other = a
        created.append(a)
    return created


def leak_via_closure(big_objects: int = 50):
    """Return a list of closures that each capture a large buffer.

    If callers hold onto the returned closures, the buffers stay alive even
    though they look "out of scope" to a casual reader.
    """
    callbacks = []
    for i in range(big_objects):
        big_buffer = bytearray(100_000)  # 100 KB captured per closure

        def make_callback(buf=big_buffer, idx=i):
            def callback():
                return f"callback {idx} holding {len(buf)} bytes"
            return callback

        callbacks.append(make_callback())
    return callbacks


def healthy_allocation(iterations: int = 1000, item_size: int = 10_000) -> None:
    """Allocate and immediately release memory - should NOT show growth."""
    for _ in range(iterations):
        buf = bytearray(item_size)
        del buf


def clear_global_cache() -> None:
    """Reset the module-level cache (useful between profiling runs)."""
    _GLOBAL_CACHE.clear()
    gc.collect()


if __name__ == "__main__":
    print("Running healthy_allocation (should not grow heap)...")
    healthy_allocation()

    print("Running leak_via_global_cache (grows _GLOBAL_CACHE)...")
    leak_via_global_cache()
    print(f"  _GLOBAL_CACHE now has {len(_GLOBAL_CACHE)} entries")

    print("Running leak_via_reference_cycle (creates cyclic Node pairs)...")
    nodes = leak_via_reference_cycle()
    print(f"  created {len(nodes)} cycle pairs")

    print("Running leak_via_closure (closures capturing big buffers)...")
    callbacks = leak_via_closure()
    print(f"  created {len(callbacks)} closures")

    print("Done. _GLOBAL_CACHE, nodes, and callbacks are still referenced "
          "from this scope.")
