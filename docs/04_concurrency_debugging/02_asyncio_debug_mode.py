"""Debugging asyncio programs: task names, task stacks, and debug mode.

asyncio has its own "thread dump" equivalent - a running event loop has a set
of `Task` objects, each wrapping a coroutine with its own suspended call
stack. The tools here are the asyncio analogues of module 1 and of
`01_thread_stack_dumps.py`:

- ``asyncio.all_tasks()``      - like `threading.enumerate()`, but for tasks.
- ``task.get_name()``          - like naming threads; set it via
  ``asyncio.create_task(coro(), name=...)``.
- ``task.get_stack()`` / ``task.print_stack()`` - like a per-thread stack
  dump, but for a SUSPENDED coroutine (shows where it's paused on an
  ``await``, not where it's "running" - only one coroutine runs at a time).
- **Debug mode** (``asyncio.run(..., debug=True)`` or
  ``PYTHONASYNCIODEBUG=1``) - the event loop starts timing every callback and
  warns when one blocks the loop too long, which is THE most common asyncio
  performance bug: accidentally calling blocking code (``time.sleep``,
  a synchronous `requests.get`, CPU-heavy work) from inside a coroutine.

Run:
    python 02_asyncio_debug_mode.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


async def named_worker(name: str, delay: float) -> str:
    await asyncio.sleep(delay)
    return f"{name} done"


async def stuck_forever(event: asyncio.Event) -> None:
    await event.wait()  # suspends here until someone sets `event`


async def demo_task_names_and_stacks() -> None:
    """asyncio.all_tasks() + get_stack() - the event-loop equivalent of a thread dump."""
    section("1. Naming tasks and inspecting their suspended stacks")

    never = asyncio.Event()  # never set - keeps `stuck` suspended on purpose
    stuck = asyncio.create_task(stuck_forever(never), name="stuck-worker")
    fast = asyncio.create_task(named_worker("fast-worker", 0.05), name="fast-worker")

    await asyncio.sleep(0.01)  # let both tasks start and reach their first await

    print("asyncio.all_tasks() while both tasks are suspended:\n")
    for task in asyncio.all_tasks():
        if task is asyncio.current_task():
            continue
        print(f"Task '{task.get_name()}':")
        stack = task.get_stack(limit=5)
        for frame in stack:
            print(f"  File \"{frame.f_code.co_filename}\", line {frame.f_lineno}, "
                  f"in {frame.f_code.co_qualname}")
        print()

    await fast
    never.set()
    await stuck

    print("'fast-worker' was suspended inside asyncio.sleep(); 'stuck-worker'")
    print("was suspended on event.wait(). In a stuck production service, dumping")
    print("all_tasks() like this (e.g. from a debug HTTP endpoint or signal")
    print("handler - see 05_production_playbook/) tells you exactly which")
    print("coroutines are waiting on what, the same way a thread dump does for")
    print("threads.")


async def demo_slow_callback_warning() -> None:
    """Debug mode warns when a coroutine blocks the event loop for too long."""
    section("2. Debug mode: detecting a coroutine that blocks the event loop")

    loop = asyncio.get_running_loop()
    loop.set_debug(True)
    loop.slow_callback_duration = 0.1  # warn if a callback takes > 100ms (default 0.1s)

    async def well_behaved() -> None:
        await asyncio.sleep(0.05)  # cooperative - releases control to the loop

    async def accidentally_blocking() -> None:
        # BUG: time.sleep() is SYNCHRONOUS - it does not await, so it blocks
        # the entire event loop (and every other task) for its duration.
        time.sleep(0.2)

    print("Running a well-behaved coroutine (asyncio.sleep) - no warning expected:")
    await well_behaved()

    print("\nRunning a coroutine that calls time.sleep() (blocks the loop) -")
    print("watch for a 'Executing ... took X.XXX seconds' warning on stderr:\n")
    sys.stdout.flush()  # stderr is unbuffered - flush so the warning prints AFTER this
    await accidentally_blocking()

    loop.set_debug(False)

    print("\n(^ that 'Executing <Task ...> took 0.200 seconds' line is the")
    print("warning - it may appear ABOVE this whole section if stdout wasn't")
    print("flushed in time; that's a buffering artifact, not ordering.)")
    print("\nThe warning fires because debug mode wraps every callback with a")
    print("timer; if a single step of the event loop takes longer than")
    print("`loop.slow_callback_duration`, EVERYTHING else scheduled on this")
    print("loop (other tasks, timers, I/O callbacks) was also delayed by that")
    print("much. In production this shows up as a latency spike across")
    print("unrelated requests handled by the same event loop.")


async def demo_debug_mode_other_checks() -> None:
    """Other things debug mode catches, summarized (not all easy to demo cleanly)."""
    section("3. Other checks enabled by asyncio debug mode")

    print("Beyond slow-callback warnings, `debug=True` / PYTHONASYNCIODEBUG=1 also:")
    print()
    print("- Logs 'Task was destroyed but it is pending!' if a Task is garbage")
    print("  collected while still running - usually means you forgot to await")
    print("  or cancel it (a common cause of silently-dropped work).")
    print("- Checks that coroutines are awaited at all - calling an async")
    print("  function without `await` (a frequent typo) produces a")
    print("  'coroutine was never awaited' RuntimeWarning even WITHOUT debug")
    print("  mode, but debug mode adds the full creation traceback.")
    print("- Makes `loop.call_soon`/`call_later` capture the caller's stack,")
    print("  so exceptions raised later in a callback show WHERE it was")
    print("  scheduled from, not just where it failed.")
    print()
    print("Enable it for an entire program with an environment variable - no")
    print("code changes needed:")
    print("    PYTHONASYNCIODEBUG=1 python myapp.py")


if __name__ == "__main__":
    asyncio.run(demo_task_names_and_stacks())
    asyncio.run(demo_slow_callback_warning())
    asyncio.run(demo_debug_mode_other_checks())
