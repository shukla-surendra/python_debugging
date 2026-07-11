"""Saving profile data to disk and visualizing it.

For a quick look, `pstats.Stats` printed to the terminal is fine. For a
real investigation you usually want to:

1. Save the raw profile data (`.prof` file) so you can re-analyze it
   without re-running the (possibly slow) program.
2. Visualize it as a call graph or flamegraph - much easier to spot "the
   one wide box" than to scan a table of 200 functions.

This script does (1) and explains (2) (the visualizers are separate tools
you install on demand).

Run:
    python 02_save_and_load_profile.py
"""

from __future__ import annotations

import cProfile
import pstats
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from workloads.cpu_bound import run  # noqa: E402


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def main() -> None:
    prof_path = Path(__file__).parent / "cpu_bound.prof"

    section("1. Profile and save to a .prof file")
    profiler = cProfile.Profile()
    profiler.enable()
    run(rounds=5)
    profiler.disable()
    profiler.dump_stats(str(prof_path))
    print(f"Wrote {prof_path}")

    section("2. Reload the .prof file later (no need to re-run the program)")
    stats = pstats.Stats(str(prof_path))
    stats.strip_dirs()  # shorten paths for readability
    stats.sort_stats(pstats.SortKey.CUMULATIVE)
    stats.print_stats(6)

    section("3. Visualizing .prof files (external tools)")
    print("This .prof file uses the same format the stdlib `profile`/`cProfile`")
    print("modules have always used (marshalled pstats data). Two popular")
    print("viewers:\n")
    print("  pip install snakeviz")
    print(f"  snakeviz {prof_path.name}")
    print("  -> opens an interactive, zoomable 'icicle' chart in your browser.\n")
    print("  pip install gprof2dot && sudo apt-get install graphviz")
    print(f"  gprof2dot -f pstats {prof_path.name} | dot -Tpng -o cpu_bound.png")
    print("  -> renders a call graph PNG, with edges weighted by time.\n")
    print("Or do it without any extra dependency using pyinstrument's HTML")
    print("output - see 05_pyinstrument_demo.py.")


if __name__ == "__main__":
    main()
