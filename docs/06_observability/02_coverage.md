# `coverage.py` - proving which lines actually ran

`coverage.py` is filed under "testing tools", but it's also a sharp
**debugging** tool. It answers a question that ends arguments instantly:
*"which lines of code actually executed?"* When someone insists "but that
branch can't have run", coverage settles it with data - and it reveals dead
code, unreachable error handlers, and config that silently skips a code path.

Under the hood it uses the same tracing machinery as the debuggers
(`sys.monitoring` on 3.12+, `sys.settrace` before), so it sees exactly what
ran.

## Install

```bash
pip install coverage
```

## 1. Which lines ran during a run?

Run *any* program under coverage - it doesn't have to be a test suite:

```bash
coverage run myscript.py                 # or: coverage run -m pytest
coverage report -m                       # text report, -m lists missed lines
coverage html && open htmlcov/index.html # annotated source: green=ran, red=didn't
```

```
Name              Stmts   Miss  Cover   Missing
-----------------------------------------------
myapp/orders.py     120     14    88%   45-52, 88, 201-205
```

The **Missing** column is the debugging payload: lines `45-52` never
executed. If that's your "this should have handled the error" block, you've
just learned the error path was never taken - the bug is *upstream*, in why
you didn't reach it.

## 2. Branch coverage - did both sides of the `if` run?

Line coverage can lie: a line ran, but only ever down one branch. `--branch`
catches the branch that never fired:

```bash
coverage run --branch myscript.py
coverage report -m
# Missing might show "88->92" meaning: line 88's branch to line 92 never taken
```

This is how you find the `else` that never happens, or the loop body that's
skipped because the collection is always empty.

## 3. Debugging use cases

- **"Is this code even reachable?"** Run the app through the failing
  scenario under coverage; if the suspect lines show as missed, they never
  ran - stop debugging them and look at why control never got there.
- **Dead code / dead config.** A whole module or branch at 0% after a
  realistic run is a candidate for deletion or a misconfiguration hiding a
  feature.
- **"Which code path does this input take?"** Run one input under coverage,
  `coverage report` - the executed lines *are* the path, no stepping needed.
- **Contexts** (`coverage run --context=<label>`) let you record *which
  test/request* hit each line, so you can ask "what exercised this line?".

## When to reach for `coverage.py`

- You need to **prove** whether a line/branch executed (or didn't).
- You suspect **dead or unreachable** code and want evidence.
- You want the **executed path** for a given input without single-stepping.

It won't tell you *why* a line ran or what the values were - pair it with the
[lightweight tracers](01_lightweight_tracing.md) (`snoop`/`hunter`) for the
values, or a debugger for interaction. Coverage answers the prior question:
*did it run at all?*
