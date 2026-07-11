# Debugging with `pytest`

A failing test is the cheapest, most reproducible bug you'll ever get - it
runs the broken code on demand in isolation. `pytest` has debugging
affordances that turn "this test fails" into "here's exactly where and why"
without adding a single `print`. These pair directly with the debuggers from
module 1 (`pdb`/`debugpy`) and the tracers from
[`01_lightweight_tracing.md`](01_lightweight_tracing.md).

## Drop into a debugger on failure

```bash
pytest --pdb                 # open (Pdb) at the point of each failure/error
pytest --pdb -x              # ...and stop at the FIRST failure (-x = exitfirst)
```

`--pdb` gives you a post-mortem prompt (module 1's `pdb.post_mortem`) at the
exact frame the assertion or exception blew up, with all locals bound - so
you can inspect the values that caused it. Use a nicer front-end if you like:

```bash
pytest --pdb --pdbcls=IPython.terminal.debugger:TerminalPdb   # ipdb-style
```

## Break at the *start* of a test

```bash
pytest --trace                # drop into pdb at the beginning of each selected test
```

Combine with selection so you only stop in the one you care about:

```bash
pytest --trace -k test_charge_declines_expired_card
```

You can also just put `breakpoint()` in the test or the code under test -
pytest handles it correctly even though it captures output by default (no
need for `-s` anymore).

## Narrow down to the failing test fast

| Flag | Does |
|---|---|
| `-x` / `--exitfirst` | Stop after the first failure |
| `--lf` / `--last-failed` | Run only the tests that failed last time |
| `--ff` / `--failed-first` | Run everything, but failures first |
| `-k EXPR` | Select tests by name substring/expression |
| `--sw` / `--stepwise` | Stop at the first failure, resume there next run |

Typical loop: `pytest --lf -x --pdb` - re-run just what broke, stop at the
first one, and land in a debugger there.

## See more when a test fails

```bash
pytest -l            # --showlocals: print local variables in the traceback
pytest -rA           # summary of ALL outcomes (including passed/xfailed) at the end
pytest --tb=long     # fuller tracebacks (or --tb=short / --tb=line to shrink them)
pytest -s            # don't capture stdout/stderr - see your prints/logs live
pytest --log-cli-level=DEBUG   # stream logging output during the test (see 05_logging.md)
```

`-l` alone often solves the bug: `pytest`'s assertion rewriting already shows
you the compared values, and `--showlocals` adds every other variable in the
frame - frequently enough to see the cause without a debugger.

## Debugging fixtures and setup

```bash
pytest --setup-show          # show fixture setup/teardown order around each test
```

When the bug is in *test wiring* (a fixture producing the wrong value, wrong
scope, ordering), `--setup-show` makes the otherwise-invisible fixture
lifecycle visible.

## Flaky / order-dependent failures

- `pytest -p no:randomly` (or the inverse with `pytest-randomly` installed)
  to control test ordering when a failure only appears in a certain order -
  a sign of shared state between tests.
- `pytest -x --lf` repeatedly to see whether a failure is deterministic.

## When you're here

- A bug is reproducible in a test → `pytest --lf -x --pdb` to land in a
  debugger at the failure with full state.
- You just need the values → `pytest -l` (`--showlocals`) is often enough.
- The test itself is suspect → `--setup-show` for fixtures, `-s` /
  `--log-cli-level` to see output.

Everything you learn at the `(Pdb)` prompt here uses the same commands as
[`../01_stack_dumps/05_pdb_deep_dive.md`](../01_stack_dumps/05_pdb_deep_dive.md);
for an IDE experience, run the tests under `debugpy`
([`../01_stack_dumps/09_debugpy.md`](../01_stack_dumps/09_debugpy.md)).
