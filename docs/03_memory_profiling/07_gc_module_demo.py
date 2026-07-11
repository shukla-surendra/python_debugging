"""The ``gc`` module - CPython's cyclic garbage collector, up close.

Most Python objects are freed the instant their reference count hits zero
(deterministic, no "GC pause"). **Reference cycles** (a -> b -> a) never hit
zero on their own - that's what the generational cyclic GC in the ``gc``
module is for. This script makes that machinery visible:

- ``gc.collect()`` - run a collection now; returns the number of unreachable
  objects it found and freed.
- ``gc.get_count()`` / ``gc.get_threshold()`` - the three-generation counters
  that decide when automatic collections happen.
- ``gc.get_referrers(obj)`` / ``gc.get_referents(obj)`` - walk the object
  graph backwards ("who points at this?") or forwards ("what does this point
  at?"). objgraph's backref chains (see 05) are built on top of these.
- ``gc.set_debug(gc.DEBUG_STATS)`` - have the collector narrate its own work.
- ``gc.garbage`` - objects the collector found in cycles but could not free
  (rare since Python 3.4's PEP 442, but still worth knowing about).
- ``gc.freeze()`` - move all currently-tracked objects to a permanent
  generation, so a `fork()`-ed worker's copy-on-write pages for them are
  never touched by the child's collector.

Run:
    python 07_gc_module_demo.py
"""

from __future__ import annotations

import gc
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from workloads.memory_leak import Node, leak_via_reference_cycle  # noqa: E402


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_generations_and_thresholds() -> None:
    """The cyclic GC runs automatically based on allocation counts, not time."""
    section("1. Generations and thresholds - when does gc.collect() run itself?")

    gen0, gen1, gen2 = gc.get_threshold()
    print(f"gc.isenabled() = {gc.isenabled()}")
    print(f"gc.get_threshold() = {(gen0, gen1, gen2)}")
    print(f"  -> (gen0, gen1, gen2): collect gen0 every {gen0} net allocations;")
    print(f"     gen1 every {gen1} gen0 collections; gen2 every {gen2 or 'N'} gen1 collections.")
    print(f"gc.get_count() = {gc.get_count()}  (current allocations since last collection)")
    print()
    print("Every new container object (list, dict, custom instance, ...) starts")
    print("in generation 0. Objects that survive a gen0 collection are promoted")
    print("to gen1, then gen2. This is why long-lived cycles cost more to find:")
    print("they end up in the generation that's scanned least often.")


def demo_cycle_collection() -> None:
    """Reference cycles are invisible to refcounting - only gc.collect() finds them."""
    section("2. Reference cycles need gc.collect() - refcounting alone won't free them")

    gc.disable()  # so nothing gets swept up before we can measure it
    gc.collect()  # start from a clean slate

    before = len(gc.get_objects())

    nodes = leak_via_reference_cycle(pairs=200)  # 200 a<->b pairs = 400 Nodes
    # Drop the only reference that came from OUTSIDE the cycle (the list
    # `leak_via_reference_cycle` returned). Each pair now only references
    # itself: a.other -> b, b.other -> a. Refcounts never reach 0.
    del nodes

    after_drop = len(gc.get_objects())
    print(f"Live objects before:                     {before}")
    print(f"Live objects after creating+dropping 200 cycle pairs: {after_drop} "
          f"(+{after_drop - before})")
    print("These 400 Node objects (plus their __dict__s and 50KB payloads) are")
    print("unreachable from any root, but NOT freed yet - nothing's refcount")
    print("dropped to zero, because each Node is kept alive by its partner.")

    collected = gc.collect()
    after_collect = len(gc.get_objects())
    print(f"\ngc.collect() returned: {collected}  (unreachable objects it found and freed)")
    print(f"Live objects after collect:              {after_collect}")

    gc.enable()


def demo_get_referrers_and_referents() -> None:
    """get_referents = forward edges ('what do I point at'), get_referrers = backward edges."""
    section("3. gc.get_referents() and gc.get_referrers() - walking the object graph")

    a = Node("a")
    b = Node("b")
    a.other = b
    b.other = a
    holder = {"first": a}

    print(f"a = {a!r}, b = {b!r}, a.other is b: {a.other is b}")

    print(f"\ngc.get_referents(a) - objects 'a' directly points to:")
    for ref in gc.get_referents(a):
        # An instance's referents include its __dict__ (which itself
        # references `other`, `name`, `payload`) and its type.
        print(f"  {type(ref).__name__}: {ref!r:.80}")

    print(f"\ngc.get_referrers(b) - objects that point AT 'b':")
    for ref in gc.get_referrers(b):
        if ref is a:
            print(f"  Node instance: {ref!r} (via its __dict__, a.other -> b)")
        elif isinstance(ref, dict) and "first" in ref:
            print(f"  dict: {{'first': <a>}} (our 'holder' local variable)")
        else:
            # Frames, module globals, etc. - keep the output short.
            print(f"  {type(ref).__name__} (frame/locals/other - omitted)")

    print("\nobjgraph.find_backref_chain() (see 05_objgraph_demo.py) is just")
    print("repeated gc.get_referrers() calls with a stopping predicate.")

    del holder


def demo_debug_flags_and_garbage() -> None:
    """gc.set_debug() makes collections narrate themselves; gc.garbage holds the leftovers."""
    section("4. gc.set_debug() and gc.garbage")

    print("gc.set_debug(gc.DEBUG_STATS) makes every gc.collect() print timing")
    print("and counts to stderr, e.g.:")
    print("    gc: collecting generation 2...")
    print("    gc: objects in each generation: 1 1 8526")
    print("    gc: objects in permanent generation: 0")
    print("    gc: done, 42 unreachable, 0 uncollectable, 0.0009s elapsed")
    print()
    print("(stderr is unbuffered, so when you run this script those 'gc:' lines")
    print("may print BEFORE earlier sections' stdout output appears - that's a")
    print("buffering artifact, not a sign the collection happened earlier.)")

    sys.stdout.flush()
    gc.set_debug(gc.DEBUG_STATS)
    leak_via_reference_cycle(pairs=20)  # returned list dropped immediately
    gc.collect()
    gc.set_debug(0)  # turn it back off - very noisy otherwise

    print(f"\ngc.garbage currently holds {len(gc.garbage)} object(s).")
    print("Since Python 3.4 (PEP 442), objects with __del__ in a cycle CAN be")
    print("collected normally - gc.garbage is now almost always empty. It only")
    print("fills up for cycles involving certain C-extension objects whose")
    print("deallocation order can't be determined safely. If you ever see")
    print("gc.garbage non-empty in production, that memory is leaked for good")
    print("until process restart.")


def demo_freeze_for_fork_workers() -> None:
    """gc.freeze() - relevant for pre-fork servers (gunicorn, uwsgi, multiprocessing)."""
    section("5. gc.freeze() - reducing copy-on-write churn in forked workers")

    gc.collect()
    print(f"Frozen object count before freeze: {gc.get_freeze_count()}")
    gc.freeze()
    print("gc.freeze() moves every currently-tracked object into a 'permanent'")
    print("generation that gc.collect() will never scan again.")
    print(f"Frozen object count after freeze:   {gc.get_freeze_count()}")
    print()
    print("Why this matters: a typical pre-fork pattern is")
    print("    load app + warm caches  ->  gc.freeze()  ->  fork() N workers")
    print("Without freeze(), each worker's gen2 collections walk through ALL")
    print("of the parent's long-lived objects (the loaded app). Since gc.collect()")
    print("writes to each object's header (refcount bookkeeping) as it scans,")
    print("this touches and copies pages that fork() had shared copy-on-write")
    print("with the parent - bloating every worker's RSS for no benefit.")
    print("freeze() tells the GC 'these objects are permanent, never scan them',")
    print("so forked workers' collections only touch their OWN new objects.")

    gc.unfreeze()  # restore normal behaviour for the rest of this process


if __name__ == "__main__":
    demo_generations_and_thresholds()
    demo_cycle_collection()
    demo_get_referrers_and_referents()
    demo_debug_flags_and_garbage()
    demo_freeze_for_fork_workers()
