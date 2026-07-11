"""pdb - interactive stack inspection.

A stack *dump* is read-only and non-interactive. ``pdb`` gives you the same
stack, but interactive: you can move between frames (`u`/`d`), inspect
locals (`p`, `pp`, `ll`), and even evaluate expressions in that frame's
context.

Three entry points:

1. ``breakpoint()`` / ``pdb.set_trace()`` - pause execution HERE, drop into
   a debugger. The modern, preferred spelling is ``breakpoint()`` (it
   respects the ``PYTHONBREAKPOINT`` env var, so it can be disabled in prod
   by setting ``PYTHONBREAKPOINT=0``).
2. ``pdb.post_mortem(traceback)`` - after an exception, inspect the stack
   at the point it was raised (like a debugger attached to a crash).
3. ``python -m pdb script.py`` - run a whole script under the debugger from
   the start (not demoed here since it needs a separate process, but
   documented below).

This script is written to be run NON-interactively by default (so it
doesn't block CI / automated runs), printing what the interactive session
WOULD show you. Run with ``--interactive`` to actually get a `(Pdb)` prompt.

Run:
    python 05_pdb_post_mortem.py                # non-interactive walkthrough
    python 05_pdb_post_mortem.py --interactive  # real pdb prompts
"""

from __future__ import annotations

import argparse
import pdb
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def compute(values: list[int]) -> float:
    total = sum(values)
    count = len(values)
    average = total / count  # ZeroDivisionError if values == []
    return average


def demo_breakpoint(interactive: bool) -> None:
    section("1. breakpoint() / pdb.set_trace() - pause and inspect")
    if interactive:
        print("Dropping into pdb. Try: `pp values`, `n`, `c` (continue).")
        values = [1, 2, 3]
        breakpoint()  # noqa: T100 - intentional for this demo
        print(f"average = {compute(values)}")
    else:
        print("(skipped - rerun with --interactive to actually hit a (Pdb) prompt)")
        print("If you had run `breakpoint()` here, you'd get a (Pdb) prompt")
        print("with `values` available, and could type e.g.:")
        print("  (Pdb) p values")
        print("  (Pdb) pp compute(values)")
        print("  (Pdb) c          # continue execution")


def demo_post_mortem(interactive: bool) -> None:
    section("2. pdb.post_mortem() - debug an exception AFTER it happens")
    try:
        compute([])
    except ZeroDivisionError:
        exc_tb = sys.exc_info()[2]
        if interactive:
            print("Entering post-mortem debugger at the point of the exception.")
            print("Try: `l` (list source), `p total`, `p count`, `u` (move up a frame).")
            pdb.post_mortem(exc_tb)
        else:
            print("(skipped interactive prompt - showing what post_mortem gives you access to)")
            print("post_mortem(tb) drops you into the frame where the exception was")
            print("raised, i.e. inside `compute()`, with `total` and `count` already")
            print("bound as locals - even though the exception has already propagated")
            print("out of that function in normal control flow.")
            # We can still demonstrate frame inspection without an interactive prompt:
            while exc_tb.tb_next:
                exc_tb = exc_tb.tb_next
            frame = exc_tb.tb_frame
            print(f"  frame locals at point of failure: {frame.f_locals}")


def demo_pdbrc_and_cli() -> None:
    section("3. Other ways to launch pdb (not run here, for reference)")
    print("Run an entire script under pdb from the start:")
    print("  python -m pdb 05_pdb_post_mortem.py")
    print()
    print("Drop into pdb automatically on ANY uncaught exception:")
    print("  python -m pdb -c continue myscript.py")
    print()
    print("Post-mortem an uncaught exception after the fact (in a REPL):")
    print("  >>> import pdb; pdb.pm()   # debugs sys.last_traceback")
    print()
    print("Disable all breakpoint() calls without editing code (e.g. in prod):")
    print("  PYTHONBREAKPOINT=0 python myscript.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interactive", action="store_true",
                         help="Actually drop into (Pdb) prompts.")
    args = parser.parse_args()

    demo_breakpoint(args.interactive)
    demo_post_mortem(args.interactive)
    demo_pdbrc_and_cli()
