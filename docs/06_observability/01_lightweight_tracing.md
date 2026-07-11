# Lightweight tracing - trace/print debugging done right

Sometimes attaching `pdb` is overkill and `print()` is too crude. This
family of tools sits in between: drop in one decorator or one call and get a
readable record of **what ran and what the values were**, with zero debugger
ceremony. Great for code you can't easily pause (tight loops, async
callbacks, subprocesses, "it only fails in CI").

## `PySnooper` - a line-by-line execution log

Decorate a function and `PySnooper` logs every line as it executes, plus
every variable that changes:

```python
import pysnooper

@pysnooper.snoop()
def compute(values):
    total = sum(values)
    count = len(values)
    return total / count
```

Output (to stderr) shows each line, the new/changed locals, and timing:

```
Starting var:.. values = [1, 2, 3]
23:11:01.001  call         4 def compute(values):
23:11:01.001  line         5     total = sum(values)
New var:....... total = 6
23:11:01.001  line         6     count = len(values)
New var:....... count = 3
23:11:01.002  line         7     return total / count
23:11:01.002  return       7     return total / count
Return value:. 2.0
```

Useful options: `@pysnooper.snoop("/tmp/trace.log")` (write to a file),
`depth=2` (also trace called functions), `watch=("obj.attr",)` (track an
expression). It's the fastest way to answer "which branch ran and what was
the value" without a debugger.

## `snoop` - a richer successor

`snoop` is the same idea with nicer output, syntax highlighting, and extras:

```python
import snoop

@snoop
def compute(values):
    ...

# Also standalone helpers:
snoop.pp(some_expression)   # print an expression AND its value, return it
```

`pp()` (pretty-print-and-return) is handy inline: `x = snoop.pp(compute(v))`
logs the value and passes it through unchanged.

## `hunter` - predicate-based tracing, no code edits

When you don't know *where* to put a decorator, `hunter` traces broadly and
**filters**. You can even enable it from the environment without touching
code:

```bash
PYTHONHUNTER='module="myapp.orders", action=CallPrinter()' python app.py
```

Or programmatically, with precise predicates:

```python
import hunter
hunter.trace(
    module="myapp.orders",
    kind="call",
    action=hunter.CallPrinter(),
)
```

`hunter` is the power tool of the three: filter by module, function, depth,
or arbitrary predicate to trace exactly the slice you care about across a
big codebase - without editing it.

## `icecream` - a better `print()`

`ic()` prints the expression **and** its value (no more
`print("x =", x)`), and prints the call location when given no args:

```python
from icecream import ic

ic(user.id, order.total)     # ic| user.id: 42, order.total: 19.99
def handler():
    ic()                     # ic| app.py:88 in handler()  -> "did we get here?"
```

`ic()` returns its argument, so you can wrap an expression in place:
`return ic(compute(values))`. Disable globally with `ic.disable()` (or
`ic.configureOutput(...)` to redirect/format).

## `rich` - readable tracebacks and object inspection

`rich` isn't a tracer, but two features are everyday debugging wins:

```python
from rich.traceback import install
install(show_locals=True)    # every uncaught traceback now shows locals,
                             # syntax-highlighted, per frame
```

```python
from rich import inspect, print
inspect(some_object, methods=True)   # attributes, methods, docstring, nicely laid out
print(some_dict)                     # pretty, colorized structures
```

`install(show_locals=True)` alone often turns a cryptic crash into an
obvious one - you see the variable values at each frame without reproducing
anything.

## Install

```bash
pip install pysnooper snoop hunter icecream rich
```

## How this compares to the debuggers

| Want to... | Reach for |
|---|---|
| Pause and *interact* (inspect, mutate, step) | `pdb` / `debugpy` (module 1) |
| Log **what ran + values** with no pausing | `PySnooper` / `snoop` |
| Trace a slice of a big codebase, no edits | `hunter` |
| A better `print()` for a quick value check | `icecream` |
| Readable tracebacks / object dumps | `rich` |

These shine exactly where debuggers are awkward: code that can't stop (async
callbacks, hot loops), failures that only happen in CI or a subprocess, and
"just tell me the value and which branch" questions where a full `(Pdb)`
session is more friction than the bug is worth.
