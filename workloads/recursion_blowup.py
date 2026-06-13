"""A program that recurses very deeply, used to demonstrate:

* what a deep stack looks like in a traceback / py-spy dump,
* ``sys.setrecursionlimit`` and ``RecursionError``,
* ``faulthandler`` printing a (truncated) stack on a fatal error.

Run it directly:

    python workloads/recursion_blowup.py
    python workloads/recursion_blowup.py --depth 50 --explode
"""

from __future__ import annotations

import argparse
import sys


def recurse(n: int, depth: int) -> int:
    """Recurse ``depth`` times, doing a little work at the bottom."""
    if n >= depth:
        return n
    return 1 + recurse(n + 1, depth)


def recurse_forever(n: int = 0) -> int:
    """Recurse without a base case until RecursionError (or a real crash)."""
    return 1 + recurse_forever(n + 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=int, default=50,
                         help="How deep to recurse for the bounded demo.")
    parser.add_argument("--explode", action="store_true",
                         help="Also run an unbounded recursion until RecursionError.")
    args = parser.parse_args()

    print(f"sys.getrecursionlimit() = {sys.getrecursionlimit()}")
    result = recurse(0, args.depth)
    print(f"recurse(0, {args.depth}) -> {result}")

    if args.explode:
        print("Now recursing without a base case (expect RecursionError)...")
        try:
            recurse_forever()
        except RecursionError as exc:
            print(f"Caught RecursionError: {exc}")
