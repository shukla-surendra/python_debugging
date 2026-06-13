"""traceback - the building block for every other stack-dump tool.

The ``traceback`` module turns frame objects / exception objects into
human-readable (or structured) stack traces. Three scenarios:

1. You caught an exception and want to print/log it          -> print_exc / format_exc
2. You want to know the call stack *right now*, no exception  -> extract_stack / print_stack
3. You have a traceback object and want to walk it yourself    -> extract_tb / StackSummary

Run:
    python 01_traceback_module.py
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workloads.cpu_bound import fibonacci  # noqa: E402


def divide(a: int, b: int) -> float:
    return a / b


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_print_exc() -> None:
    """The classic: print the traceback of the exception being handled."""
    section("1. traceback.print_exc() - print the *current* exception")
    try:
        divide(1, 0)
    except ZeroDivisionError:
        traceback.print_exc()  # writes to stderr by default


def demo_format_exc() -> None:
    """Like print_exc, but returns a string - useful for logging."""
    section("2. traceback.format_exc() - get the traceback as a string")
    try:
        divide(1, 0)
    except ZeroDivisionError:
        text = traceback.format_exc()
        print(f"Captured {len(text.splitlines())} lines, e.g. for logging:")
        print(text)


def demo_print_stack() -> None:
    """Dump the CURRENT call stack - no exception needed at all.

    This is the core trick behind ad-hoc "what is this thread doing"
    diagnostics: call this from anywhere and you get every frame from
    `<module>` down to the current line.
    """
    section("3. traceback.print_stack() - dump the call stack with NO exception")

    def inner():
        traceback.print_stack()

    def middle():
        inner()

    def outer():
        middle()

    outer()


def demo_extract_stack_structured() -> None:
    """extract_stack() gives you a StackSummary you can inspect/filter/serialize."""
    section("4. traceback.extract_stack() - structured access to frames")

    def a():
        return b()

    def b():
        return traceback.extract_stack()

    stack = a()
    print(f"Stack has {len(stack)} frames. Last 3:")
    for frame_summary in stack[-3:]:
        print(f"  {frame_summary.filename}:{frame_summary.lineno} "
              f"in {frame_summary.name}()  -> {frame_summary.line!r}")


def demo_walk_tb_during_recursion() -> None:
    """Combine extract_tb with a deliberately raised exception inside recursion."""
    section("5. Inspecting a deep traceback (recursive call chain)")

    def boom(n: int) -> int:
        if n == 0:
            raise RuntimeError("boom from the bottom of the recursion")
        return 1 + boom(n - 1)

    try:
        boom(5)
    except RuntimeError:
        tb = sys.exc_info()[2]
        frames = traceback.extract_tb(tb)
        print(f"Traceback has {len(frames)} frames (depth 5 recursion):")
        for fs in frames:
            print(f"  {fs.name}() at line {fs.lineno}: {fs.line!r}")


if __name__ == "__main__":
    demo_print_exc()
    demo_format_exc()
    demo_print_stack()
    demo_extract_stack_structured()
    demo_walk_tb_during_recursion()

    section("Bonus: fibonacci(5) result (just to show workloads/ import works)")
    print(f"fibonacci(5) = {fibonacci(5)}")
