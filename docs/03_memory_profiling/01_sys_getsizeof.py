"""sys.getsizeof - the simplest possible "how big is this?" tool, and why
it's often misleading.

``sys.getsizeof(obj)`` returns the number of bytes the object ITSELF
occupies - not including objects it refers to. For a `list`, that's the
size of the array of pointers, NOT the size of the items pointed to.

This is the #1 source of "but Python says my list is only 64 bytes, why is
my process using 500MB?!" confusion.

Run:
    python 01_sys_getsizeof.py
"""

from __future__ import annotations

import sys


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_basic_sizes() -> None:
    section("1. Shallow sizes of basic objects")
    for obj in [0, 1, 2**62, 2**63, "", "a", "hello world", [], [1, 2, 3], {}, {"a": 1}]:
        print(f"  sys.getsizeof({obj!r:20}) = {sys.getsizeof(obj)} bytes")
    print("\nNote: small ints, empty containers, etc. all have fixed")
    print("overhead - CPython objects always carry a type pointer + refcount")
    print("(16 bytes on 64-bit) at minimum.")


def demo_container_lies() -> None:
    """A list's reported size doesn't include the objects it points to."""
    section("2. Containers only report pointer storage, not contents")

    small_items = [0, 1, 2]
    big_items = [bytearray(100_000) for _ in range(3)]

    print(f"sys.getsizeof([0, 1, 2])                 = {sys.getsizeof(small_items)} bytes")
    print(f"sys.getsizeof([3x 100KB bytearrays])     = {sys.getsizeof(big_items)} bytes")
    print()
    print("Both lists report roughly the same size (just 3 pointers!) even")
    print("though the second one references 300,000 bytes of actual data.")
    print(f"\nActual data size: sum(sys.getsizeof(x) for x in big_items) = "
          f"{sum(sys.getsizeof(x) for x in big_items)} bytes")


def demo_deep_size_naive() -> None:
    """A naive recursive "deep size" - and why it's still not quite right."""
    section("3. A naive recursive deep-size function (and its limits)")

    def deep_size(obj, seen=None) -> int:
        """Recursively sum sizes, avoiding double-counting via `seen`."""
        if seen is None:
            seen = set()
        obj_id = id(obj)
        if obj_id in seen:
            return 0
        seen.add(obj_id)

        size = sys.getsizeof(obj)
        if isinstance(obj, dict):
            for k, v in obj.items():
                size += deep_size(k, seen) + deep_size(v, seen)
        elif isinstance(obj, (list, tuple, set, frozenset)):
            for item in obj:
                size += deep_size(item, seen)
        return size

    nested = {"a": [1, 2, 3], "b": {"c": [bytearray(10_000)]}}
    print(f"sys.getsizeof(nested)        = {sys.getsizeof(nested)} bytes (shallow)")
    print(f"deep_size(nested)            = {deep_size(nested)} bytes (recursive)")
    print()
    print("Caveats with hand-rolled deep_size:")
    print("- doesn't handle arbitrary objects (custom classes, __slots__, etc.)")
    print("- doesn't account for shared references correctly across separate")
    print("  top-level calls (only within one call, via `seen`)")
    print("- For real deep-size measurements, use pympler.asizeof - see")
    print("  06_pympler_demo.py")


def demo_shared_references() -> None:
    """Why 'sum of getsizeof' over-counts when objects are shared."""
    section("4. Shared references make naive summing double-count")

    shared = "x" * 10_000
    list_a = [shared, shared, shared]

    naive_sum = sum(sys.getsizeof(x) for x in list_a)
    print(f"3 references to the SAME 10KB string:")
    print(f"  naive sum of getsizeof()  = {naive_sum} bytes (looks like ~30KB)")
    print(f"  actual unique data        = {sys.getsizeof(shared)} bytes (it's the same object x3!)")
    print()
    print("This is exactly the kind of thing tracemalloc/objgraph/memray")
    print("handle correctly by tracking actual allocations, not by summing")
    print("getsizeof() over a container's contents.")


if __name__ == "__main__":
    demo_basic_sizes()
    demo_container_lies()
    demo_deep_size_naive()
    demo_shared_references()
