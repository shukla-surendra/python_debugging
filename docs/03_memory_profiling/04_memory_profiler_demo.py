"""memory_profiler - per-line RSS (process memory) over time.

Where ``tracemalloc`` tracks Python-level allocations,
``memory_profiler`` samples the **process's actual RSS** (via `psutil`) -
closer to what `top`/`ps`/your container's memory limit sees. It has two
modes:

1. ``memory_usage()`` - sample a function's RSS over time as a list of
   (MiB) values, programmatically. Good for plotting / asserting "this
   function doesn't grow memory by more than X MiB".
2. ``@profile`` decorator + ``python -m memory_profiler script.py`` -
   per-line RSS deltas, the memory equivalent of `line_profiler`. Requires
   running via `-m memory_profiler` (or `mprof`) because it needs to read
   the source file.

Run:
    python 04_memory_profiler_demo.py          # programmatic API only
    python -m memory_profiler 04_memory_profiler_demo.py   # also runs @profile section
"""

from __future__ import annotations

import sys
from pathlib import Path

from memory_profiler import memory_usage

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from workloads.memory_leak import (  # noqa: E402
    clear_global_cache,
    healthy_allocation,
    leak_via_global_cache,
)


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_memory_usage_leaky() -> None:
    section("1. memory_usage() on a LEAKY function - RSS climbs and stays up")

    clear_global_cache()
    mem = memory_usage(
        (leak_via_global_cache, (), {"iterations": 5000, "item_size": 50_000}),
        interval=0.02,
        timeout=10,
    )
    print(f"Samples: {len(mem)}")
    print(f"Start RSS: {mem[0]:.1f} MiB")
    print(f"End RSS:   {mem[-1]:.1f} MiB")
    print(f"Peak RSS:  {max(mem):.1f} MiB")
    print(f"Growth:    {mem[-1] - mem[0]:.1f} MiB (this stays allocated - it's a cache)")


def demo_memory_usage_healthy() -> None:
    section("2. memory_usage() on a HEALTHY function - allocates then frees")

    mem = memory_usage(
        (healthy_allocation, (), {"iterations": 5000, "item_size": 50_000}),
        interval=0.02,
        timeout=10,
    )
    print(f"Samples: {len(mem)}")
    print(f"Start RSS: {mem[0]:.1f} MiB")
    print(f"End RSS:   {mem[-1]:.1f} MiB")
    print(f"Peak RSS:  {max(mem):.1f} MiB (transient spike during allocation)")
    print(f"Net growth: {mem[-1] - mem[0]:.1f} MiB (should be near zero)")
    print()
    print("Note: CPython doesn't always return freed memory to the OS")
    print("immediately, so 'end == start' isn't guaranteed even for healthy")
    print("code - but unlike the leaky case, it won't keep climbing on")
    print("repeated calls.")


# --- @profile section: per-line RSS, only runs under `python -m memory_profiler` ---
#
# `kernprof`-style tools inject a `profile` name into builtins. Guard the
# decorator so this file still runs normally with plain `python`.
if "profile" not in dir(__builtins__):
    def profile(func):  # type: ignore[no-redef]
        return func


@profile
def annotated_leak_demo() -> None:
    """Run under `python -m memory_profiler` to see a per-line RSS table."""
    clear_global_cache()
    a = [0] * 1_000_000          # ~8MB of pointers
    b = [bytearray(10_000) for _ in range(500)]   # ~5MB of bytearrays
    leak_via_global_cache(iterations=2000, item_size=20_000)  # ~40MB into the cache
    del a
    del b


def demo_decorator_reference() -> None:
    section("3. @profile + `python -m memory_profiler` (per-line RSS)")
    print("This file defines `annotated_leak_demo()` decorated with @profile.")
    print("Run it like this to see a per-line memory delta table:\n")
    print("    python -m memory_profiler 04_memory_profiler_demo.py")
    print()
    print("Real output looks like this (this is an actual captured run):")
    print("    Line #    Mem usage    Increment  Occurrences   Line Contents")
    print("    =============================================================")
    print("        87  267.6 MiB    267.6 MiB           1   @profile")
    print("        88   45.2 MiB   -222.4 MiB           1       clear_global_cache()")
    print("        89   45.2 MiB      0.0 MiB           1       a = [0] * 1_000_000")
    print("        90   45.2 MiB      0.0 MiB         501       b = [bytearray(10_000) ...]")
    print("        91   79.5 MiB     34.3 MiB           1       leak_via_global_cache(...)")
    print("        92   79.5 MiB      0.0 MiB           1       del a")
    print("        93   79.5 MiB      0.0 MiB           1       del b")
    print()
    print("(The big -222 MiB on `clear_global_cache()` is from earlier demo")
    print(" functions in this same script clearing their caches - in")
    print(" isolation that line would show ~0.)")
    print()
    print("Each line's 'Increment' is the RSS delta caused by THAT line -")
    print("this is the fastest way to find 'which line of this function")
    print("allocates the big chunk'.")


def demo_mprof_cli() -> None:
    section("4. `mprof` - record + plot memory over the WHOLE program's life")
    print("mprof run python ../../workloads/memory_leak.py")
    print("mprof plot          # opens a matplotlib graph of RSS vs time")
    print()
    print("Useful for long-running services: run `mprof run` in place of")
    print("`python`, let it run for a while, then `mprof plot` to SEE the")
    print("shape of the leak (steady ramp = unbounded growth, sawtooth =")
    print("healthy alloc/free cycles).")


if __name__ == "__main__":
    demo_memory_usage_leaky()
    demo_memory_usage_healthy()
    annotated_leak_demo()  # runs normally too, just without per-line stats
    demo_decorator_reference()
    demo_mprof_cli()
