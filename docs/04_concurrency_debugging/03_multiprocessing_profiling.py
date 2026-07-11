"""Profiling code that runs across multiple PROCESSES.

Every profiler in module 2 (`cProfile`, `line_profiler`, `pyinstrument`,
`py-spy record`, `scalene`) profiles a single process. The moment your
program uses `multiprocessing` (or `ProcessPoolExecutor`, or `os.fork`), the
parent process's profiler sees NOTHING the child processes do - they have
separate memory, separate GILs, separate everything.

There are two practical approaches:

1. **Profile inside each worker** - have each child run its own
   `cProfile.Profile()`, dump a `.prof` file, then merge the files in the
   parent with `pstats.Stats().add()`. Works everywhere, no extra tools.
2. **Attach an external sampler to each child PID** - `py-spy` (and `austin`)
   can target a specific PID, and `py-spy`'s `--subprocesses` flag will
   automatically attach to all descendants of a PID too.

Run:
    python 03_multiprocessing_profiling.py
"""

from __future__ import annotations

import cProfile
import multiprocessing
import pstats
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from workloads.cpu_bound import fibonacci, sum_of_squares  # noqa: E402


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def _profiled_worker(args: tuple[int, str]) -> None:
    """Run in a child process: profile this process's own work and save it."""
    n, out_path = args
    profiler = cProfile.Profile()
    profiler.enable()
    sum_of_squares(n)
    for _ in range(3):
        fibonacci(20)
    profiler.disable()
    profiler.dump_stats(out_path)


def demo_per_process_profiles(tmpdir: Path) -> list[str]:
    """Each worker process writes its own .prof file - the parent writes none."""
    section("1. Each process profiles ITSELF and dumps its own .prof file")

    n_workers = 4
    work = [(20_000_000, str(tmpdir / f"worker-{i}.prof")) for i in range(n_workers)]

    start = time.perf_counter()
    with multiprocessing.Pool(n_workers) as pool:
        pool.map(_profiled_worker, work)
    elapsed = time.perf_counter() - start

    prof_files = [path for _, path in work]
    print(f"{n_workers} worker processes finished in {elapsed:.2f}s.")
    print("Files written:")
    for f in prof_files:
        size = Path(f).stat().st_size
        print(f"  {f}  ({size:,} bytes)")
    print()
    print("Note: cProfile.Profile() created in the PARENT process before")
    print("`pool.map()` would capture NOTHING about the workers - it has to be")
    print("created and enabled INSIDE the worker function (or in a pool")
    print("initializer), because each worker is a separate process with its")
    print("own profiler state.")

    return prof_files


def demo_merge_profiles(prof_files: list[str]) -> None:
    """pstats.Stats().add() sums multiple profiles into one aggregate report."""
    section("2. Merging N per-process profiles with pstats.Stats().add()")

    stats = pstats.Stats(prof_files[0])
    for f in prof_files[1:]:
        stats.add(f)

    print(f"Combined stats from {len(prof_files)} worker processes "
          f"(sorted by cumulative time):\n")
    stats.strip_dirs().sort_stats("cumulative").print_stats(6)

    print("Each row's call count and time are now the SUM across all workers -")
    print("e.g. `fibonacci` shows ~4x the calls of a single worker's profile,")
    print("since all 4 workers ran the same loop. This answers 'in aggregate,")
    print("where did our worker pool spend its CPU', without needing every")
    print("worker's profile inspected individually.")


def demo_py_spy_subprocesses_reference() -> None:
    """Reference: attaching an external sampler to live worker processes."""
    section("3. py-spy / austin against a running multiprocessing program")

    print("For a LONG-RUNNING worker pool, internal cProfile means restarting")
    print("the process with profiling enabled. To inspect workers that are")
    print("ALREADY running, attach externally by PID:")
    print()
    print("  # Find the parent PID, then dump every worker process under it:")
    print("  py-spy dump --pid <PARENT_PID> --subprocesses")
    print()
    print("  # Record a combined flamegraph across the parent + all children:")
    print("  py-spy record -o out.svg --pid <PARENT_PID> --subprocesses")
    print()
    print("  # Or target one specific worker directly:")
    print("  py-spy dump --pid <WORKER_PID>")
    print()
    print("As with single-process py-spy (see 01_stack_dumps/06_py_spy_dump.md),")
    print("attaching to an EXISTING pid needs ptrace permission (sudo, or")
    print("`/proc/sys/kernel/yama/ptrace_scope` set to 0). `py-spy record --")
    print("<cmd>` (spawn mode) avoids that for programs you can restart, and")
    print("its `--subprocesses` flag covers any children the command spawns.")


if __name__ == "__main__":
    tmpdir = Path(tempfile.mkdtemp(prefix="mp_profiling_demo_"))
    try:
        prof_files = demo_per_process_profiles(tmpdir)
        demo_merge_profiles(prof_files)
        demo_py_spy_subprocesses_reference()
    finally:
        shutil.rmtree(tmpdir)
