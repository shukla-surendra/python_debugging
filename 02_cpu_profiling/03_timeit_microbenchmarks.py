"""timeit - accurately measuring small pieces of code.

cProfile/line_profiler tell you where time goes *within a program*.
``timeit`` answers a narrower question: "of these two ways to write this
one line, which is faster?" It does this by:

- running the snippet many times in a loop (amortizing measurement overhead)
- disabling the garbage collector during the run (so a GC pause in the
  middle doesn't randomly inflate one trial)
- taking the MINIMUM of several repeats (the minimum is the closest you'll
  get to "how fast can this run with no interference" - means/medians get
  pulled up by OS noise)

Run:
    python 03_timeit_microbenchmarks.py
"""

from __future__ import annotations

import timeit


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_basic_timeit() -> None:
    section("1. timeit.timeit() - run a snippet N times, return total seconds")

    n = 100_000
    t_loop = timeit.timeit("x = []\nfor i in range(100): x.append(i)", number=n)
    t_comp = timeit.timeit("x = [i for i in range(100)]", number=n)

    print(f"for-loop + append : {t_loop:.4f}s for {n} runs")
    print(f"list comprehension: {t_comp:.4f}s for {n} runs")
    print(f"comprehension is ~{t_loop / t_comp:.2f}x faster")


def demo_timer_repeat() -> None:
    """Timer.repeat() runs the whole measurement multiple times; take min()."""
    section("2. Timer.repeat() - take the MIN of several runs to reduce noise")

    setup = "data = list(range(1000))"
    stmt_concat = "result = ''.join(str(x) for x in data)"
    stmt_fstring_loop = (
        "parts = []\n"
        "for x in data:\n"
        "    parts.append(str(x))\n"
        "result = ''.join(parts)"
    )

    timer_a = timeit.Timer(stmt_concat, setup=setup)
    timer_b = timeit.Timer(stmt_fstring_loop, setup=setup)

    repeats_a = timer_a.repeat(repeat=5, number=1000)
    repeats_b = timer_b.repeat(repeat=5, number=1000)

    print(f"generator + join : min={min(repeats_a):.5f}s  all={['%.5f' % t for t in repeats_a]}")
    print(f"loop + join      : min={min(repeats_b):.5f}s  all={['%.5f' % t for t in repeats_b]}")


def demo_compare_string_building() -> None:
    """A classic micro-benchmark: string concatenation strategies."""
    section("3. String building: += vs join vs f-string accumulation")

    n = 1000
    number = 2000

    t_plus = timeit.timeit(
        "s = ''\nfor i in range(n): s += str(i)",
        globals={"n": n}, number=number,
    )
    t_join = timeit.timeit(
        "''.join(str(i) for i in range(n))",
        globals={"n": n}, number=number,
    )
    t_list_join = timeit.timeit(
        "''.join([str(i) for i in range(n)])",
        globals={"n": n}, number=number,
    )

    print(f"'+=' in a loop          : {t_plus:.4f}s")
    print(f"''.join(generator)      : {t_join:.4f}s")
    print(f"''.join([list comp])    : {t_list_join:.4f}s")
    print("\nNote: CPython optimizes 'str += str' in a loop reasonably well")
    print("nowadays, but join() is still the idiomatic choice and wins for")
    print("larger N or when building from non-contiguous pieces.")


def demo_command_line_equivalent() -> None:
    section("4. Command-line usage (for reference, not run here)")
    print("python -m timeit '\"-\".join(str(n) for n in range(100))'")
    print("python -m timeit -s 'data = list(range(1000))' 'sum(data)'")
    print()
    print("The -s/--setup flag's code runs once per repeat, NOT once per")
    print("loop iteration - put expensive setup there, not in the statement.")


def demo_pitfalls() -> None:
    section("5. Common pitfalls")
    print("- Don't benchmark functions that print/log/do I/O - you're")
    print("  measuring the terminal, not your code.")
    print("- Global lookups are slower than local ones; timeit's default")
    print("  'globals' isolation can make a snippet look slower than it")
    print("  really is inside a function. Pass `globals=globals()` to use")
    print("  your real module namespace if that matters.")
    print("- For anything longer than ~1 line, profile the whole program")
    print("  instead (01_cprofile_basics.py / 04_line_profiler_demo.py) -")
    print("  micro-benchmarks of snippets in isolation can mislead once")
    print("  branch prediction / cache effects from the real program matter.")


if __name__ == "__main__":
    demo_basic_timeit()
    demo_timer_repeat()
    demo_compare_string_building()
    demo_command_line_equivalent()
    demo_pitfalls()
