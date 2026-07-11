"""line_profiler - per-LINE timing (not just per-function).

cProfile tells you "sum_of_squares took 9ms total". It can't tell you
*which line* of `sum_of_squares` is expensive - for that you need
line-by-line instrumentation, which is what `line_profiler` does.

Two ways to use it:

1. **Programmatic** (shown here): ``LineProfiler().add_function(fn)`` then
   call the function through the profiler. Works in any script, no special
   invocation needed.
2. **`@profile` decorator + `kernprof`** (the more common workflow):
   decorate the function(s) you care about with a bare `@profile` (no
   import needed - `kernprof` injects it), then run:

       kernprof -lv myscript.py

   `kernprof` builds a `LineProfiler`, wraps every `@profile`-decorated
   function, runs the script, and prints/saves the report. The `@profile`
   name only exists while running under kernprof - running the script
   normally (`python myscript.py`) would raise `NameError` unless you
   guard it (see the snippet at the bottom of this file).

Overhead warning: line_profiler can slow down decorated functions by
10-100x. Only decorate the specific function(s) you're investigating, never
your whole program.

Run:
    python 04_line_profiler_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from line_profiler import LineProfiler

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from workloads.cpu_bound import one_round, string_churn, sum_of_squares  # noqa: E402


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_profile_single_function() -> None:
    section("1. Profile sum_of_squares() line-by-line")

    lp = LineProfiler()
    lp.add_function(sum_of_squares)

    wrapped = lp(sum_of_squares)
    wrapped(200_000)

    lp.print_stats()


def demo_profile_multiple_functions() -> None:
    """Profile several functions in one pass by calling through one_round()."""
    section("2. Profile multiple functions reached via one_round()")

    lp = LineProfiler()
    for fn in (one_round, sum_of_squares, string_churn):
        lp.add_function(fn)

    wrapped = lp(one_round)
    wrapped(size=100_000, fib_n=10)

    lp.print_stats()


def demo_kernprof_workflow() -> None:
    section("3. The @profile + kernprof workflow (reference)")
    print("Add this to a script (no import of `profile` needed):\n")
    print("    @profile")
    print("    def sum_of_squares(n):")
    print("        total = 0")
    print("        for i in range(n):")
    print("            total += i * i")
    print("        return total\n")
    print("Then run:")
    print("    kernprof -lv workloads/cpu_bound.py")
    print()
    print("kernprof writes a `<script>.lprof` file AND (with -v) prints the")
    print("same per-line table you saw above, directly to the terminal.")
    print()
    print("To make a script runnable BOTH normally and under kernprof, guard")
    print("the decorator:")
    print()
    print("    if 'profile' not in dir(__builtins__):")
    print("        def profile(func):")
    print("            return func")


if __name__ == "__main__":
    demo_profile_single_function()
    demo_profile_multiple_functions()
    demo_kernprof_workflow()
