"""objgraph - object counts, growth tracking, and REFERENCE CHAINS.

tracemalloc and memory_profiler tell you WHERE bytes were allocated.
objgraph answers a different, often more useful question for "leaks" in
the Python sense (objects still reachable, but shouldn't be):

    "WHO is holding a reference to this object, keeping it alive?"

Key functions:

- ``objgraph.show_most_common_types()``  - histogram of all live objects by type
- ``objgraph.count("ClassName")``        - how many instances of a class exist
- ``objgraph.growth()`` / ``show_growth()`` - object count deltas since last call
- ``objgraph.find_backref_chain(obj, predicate)`` - walk backwards from an
  object to something matching `predicate` (e.g. a module, a known root)
- ``objgraph.show_backrefs(obj)`` / ``show_refs(obj)`` - render a graphviz
  image of references (requires the `dot` binary; not used here)

Run:
    python 05_objgraph_demo.py
"""

from __future__ import annotations

import gc
import sys
from pathlib import Path

import objgraph

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from workloads.memory_leak import Node, leak_via_reference_cycle  # noqa: E402


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_most_common_types() -> None:
    section("1. show_most_common_types() - histogram of all live objects")
    objgraph.show_most_common_types(limit=8)


def demo_count_and_growth() -> None:
    section("2. count() and growth() - track a specific class over time")

    print(f"Node instances before: {objgraph.count('Node')}")

    # objgraph.growth() establishes a baseline on first call.
    objgraph.growth(limit=3)

    batch1 = leak_via_reference_cycle(pairs=50)
    print(f"\nAfter creating 50 Node pairs:")
    print(f"  Node instances: {objgraph.count('Node')}")
    print("  growth() since baseline:")
    for name, count, delta in objgraph.growth(limit=5):
        print(f"    {name:20s} count={count:6d}  (+{delta})")

    batch2 = leak_via_reference_cycle(pairs=30)
    print(f"\nAfter creating 30 MORE Node pairs:")
    print(f"  Node instances: {objgraph.count('Node')}")
    print("  growth() since last call:")
    for name, count, delta in objgraph.growth(limit=5):
        print(f"    {name:20s} count={count:6d}  (+{delta})")

    return batch1, batch2


def demo_backref_chain(batches) -> None:
    """The killer feature: find out WHY an object is still alive."""
    section("3. find_backref_chain() - 'why is this Node still alive?'")

    batch1, _ = batches
    target = batch1[0].other  # a Node referenced only via batch1[0].other

    print(f"Target object: {target!r}")
    print("Looking for a reference chain from a module-level name down to it...\n")

    chain = objgraph.find_backref_chain(target, objgraph.is_proper_module)
    for i, obj in enumerate(chain):
        indent = "  " * i
        type_name = type(obj).__name__
        # Keep the repr short and avoid dumping huge dict contents.
        try:
            r = repr(obj)
        except Exception:
            r = "<unrepr-able>"
        if len(r) > 70:
            r = r[:70] + "..."
        print(f"{indent}-> {type_name}: {r}")

    print("\nThis chain is the answer to 'why hasn't this been garbage")
    print("collected': something at the top of the chain (a module/global,")
    print("a list, a frame's locals...) transitively references it.")


def demo_reference_cycle_visibility(batches) -> None:
    """Show that the cycle pairs reference EACH OTHER (a<->b)."""
    section("4. Confirming the A<->B reference cycle")

    batch1, _ = batches
    a = batch1[0]
    b = a.other
    print(f"a = {a!r}, a.other = {b!r}")
    print(f"b.other = {b.other!r}")
    print(f"a is b.other? {a is b.other}")
    print()
    print("a -> b -> a is a reference cycle. Without the cyclic GC, these")
    print("would only be freed if SOMETHING ELSE breaks the cycle (e.g.")
    print("setting a.other = None). gc.collect() can find and free such")
    print("cycles even with no external references - see 07_gc_module_demo.py.")


def demo_show_chain_text() -> None:
    """A lighter-weight alternative to show_backrefs() that doesn't need graphviz."""
    section("5. Manually walking gc.get_referrers() (what show_backrefs visualizes)")

    n = Node("standalone")
    holder = {"my_node": n}

    referrers = gc.get_referrers(n)
    print(f"Objects directly referring to {n!r}:")
    for ref in referrers:
        # Frames and the local 'holder'/'n' bindings will show up too.
        if isinstance(ref, dict) and ref is not globals() and ref is not locals():
            print(f"  dict: {dict(list(ref.items())[:3])}{'...' if len(ref) > 3 else ''}")
    del holder


if __name__ == "__main__":
    demo_most_common_types()
    batches = demo_count_and_growth()
    demo_backref_chain(batches)
    demo_reference_cycle_visibility(batches)
    demo_show_chain_text()
