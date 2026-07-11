"""pyinstrument - low-overhead statistical profiler with a readable call tree.

Unlike cProfile (which records every call), pyinstrument samples the call
stack at a fixed interval (default ~1ms) and reconstructs a **call tree**.
Benefits:

- Overhead is low enough to leave on during normal development/testing.
- Output is a tree, not a flat sorted table - it directly shows you
  "function A spent 80% of its time inside function B", which in cProfile
  output you'd have to reconstruct by reading `print_callees` repeatedly.
- Renders nicely as text, HTML, or JSON.

Three ways to use it:

1. ``Profiler()`` as a context manager (shown below)
2. ``profiler.start()`` / ``profiler.stop()`` manually
3. CLI: ``pyinstrument myscript.py`` (reference, not run here)

Run:
    python 05_pyinstrument_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from pyinstrument import Profiler

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workloads.cpu_bound import run  # noqa: E402


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_context_manager() -> Profiler:
    section("1. Profiler() as a context manager")

    profiler = Profiler(interval=0.001)
    with profiler:
        run(rounds=10)

    return profiler


def demo_text_output(profiler: Profiler) -> None:
    section("2. Text call-tree output")
    # color=False so the output looks right in plain-text logs/CI.
    print(profiler.output_text(unicode=True, color=False, show_all=False))


def demo_html_report(profiler: Profiler) -> None:
    section("3. HTML report (interactive, open in a browser)")
    html_path = Path(__file__).parent / "pyinstrument_report.html"
    html_path.write_text(profiler.output_html())
    print(f"Wrote {html_path}")
    print("Open it in a browser for an interactive, collapsible call tree")
    print("with color-coded 'time spent' bars per function.")


def demo_cli_reference() -> None:
    section("4. CLI usage (reference, not run here)")
    print("pyinstrument workloads/cpu_bound.py --rounds 10")
    print("pyinstrument -r html -o report.html workloads/cpu_bound.py --rounds 10")
    print("pyinstrument -m mymodule  # profile a module like `python -m`")
    print()
    print("pyinstrument can also profile async code correctly (it's aware")
    print("of asyncio's event loop and won't attribute 'await' time to the")
    print("wrong coroutine) - see 04_concurrency_debugging/.")


if __name__ == "__main__":
    profiler = demo_context_manager()
    demo_text_output(profiler)
    demo_html_report(profiler)
    demo_cli_reference()
