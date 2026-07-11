# `pdb` - the interactive debugger (deep dive)

`py-spy` and `pystack` take a **read-only snapshot** from outside a process.
`pdb` is the opposite tool: it runs **inside** your process and lets you
*interact* - pause execution, walk the stack, inspect and even **mutate**
locals, evaluate arbitrary expressions in a frame's context, and step
through code line by line.

The trade-off: `pdb` requires the process to cooperate. Something has to
call into it (`breakpoint()`, `pdb.post_mortem()`, or `python -m pdb`), and
while you're at the `(Pdb)` prompt **that thread is stopped**. That makes it
the wrong tool for a process you don't control, and a *careful* tool for
production - but the best tool when you own the process and want to poke at
its actual state.

The runnable companion to this doc is
[`05_pdb_post_mortem.py`](05_pdb_post_mortem.py) - run it with
`--interactive` to get real prompts.

## The four ways to get a `(Pdb)` prompt

**1. `breakpoint()` - pause *here* (the modern spelling).**

```python
values = load_things()
breakpoint()          # execution stops on this line, drops to (Pdb)
process(values)
```

`breakpoint()` (Python 3.7+) is preferred over the old
`import pdb; pdb.set_trace()` because it honors the `PYTHONBREAKPOINT`
environment variable:

```bash
PYTHONBREAKPOINT=0 python app.py            # disable ALL breakpoints, no edits
PYTHONBREAKPOINT=ipdb.set_trace python app.py   # use ipdb instead of pdb
```

That `PYTHONBREAKPOINT=0` escape hatch is exactly why you can leave
`breakpoint()` in code without it becoming a production landmine - though a
linter rule (ruff `T100`) to catch stray ones is still wise.

**2. `pdb.post_mortem(tb)` - debug an exception *after* it was raised.**

```python
try:
    risky()
except Exception:
    import pdb, sys
    pdb.post_mortem(sys.exc_info()[2])
```

This drops you into the frame **where the exception was raised**, with that
frame's locals still bound - even though normal control flow has already
unwound past it. `pdb.pm()` does the same for the *last* uncaught exception
in a REPL (`pdb.pm()` reads `sys.last_traceback`).

**3. `python -m pdb script.py` - run the whole thing under the debugger.**

```bash
python -m pdb app.py                 # stops before the first line
python -m pdb -c continue app.py     # run until it crashes, then post-mortem
```

The `-c continue` form is a great "just tell me where it dies" mode: it runs
normally and only hands you a prompt if there's an uncaught exception.

**4. Auto-post-mortem in an interactive session.** Run with `python -i`, and
after a crash call `import pdb; pdb.pm()`. Libraries like IPython do this
automatically with `%debug`.

## Essential commands at the `(Pdb)` prompt

| Command | Alias | Does |
|---|---|---|
| `list` | `l` | Show source around the current line (`ll` = whole function) |
| `where` | `w` | Print the full stack (a traceback of where you are) |
| `up` / `down` | `u` / `d` | Move to the caller's / callee's frame |
| `print` / `pp` | `p` / `pp` | Evaluate an expression; `pp` pretty-prints |
| `args` | `a` | Print the current function's arguments |
| `next` | `n` | Execute the current line, *step over* calls |
| `step` | `s` | Execute the current line, *step into* calls |
| `return` | `r` | Run until the current function returns |
| `continue` | `c` | Resume until the next breakpoint |
| `until` | `unt` | Run until a line past the current one (great for exiting loops) |
| `break` | `b` | Set a breakpoint: `b 42`, `b module.func`, `b 42, x > 5` (conditional) |
| `tbreak` | | One-shot breakpoint (auto-removed after it fires) |
| `commands` | | Attach commands to a breakpoint (e.g. auto-`print` then `continue`) |
| `display` | | Auto-print an expression whenever it changes as you step |
| `interact` | | Drop into a full Python REPL in the current frame's namespace |
| `!<stmt>` | | Run a statement (e.g. `!x = 5` to **mutate** a local) |

Two things beginners miss:

- **You can change state.** `!x = 0`, or call functions with side effects.
  Handy for testing a fix in place ("would setting this to `None` unstick
  it?") before editing code.
- **`p` shadows can bite.** To print a variable literally named `n`, `s`,
  `c`, etc. (which collide with commands), use `p n` / `!n` - `n` alone
  means *next*.

### `.pdbrc` and post-mortem-on-crash

A `.pdbrc` file (in your home dir or CWD) runs commands on every `pdb`
start - e.g. define aliases or set up `display`s. And to drop into
post-mortem automatically on *any* uncaught exception process-wide:

```python
import sys, pdb
def _hook(exc_type, exc, tb):
    import traceback; traceback.print_exception(exc_type, exc, tb)
    pdb.post_mortem(tb)
sys.excepthook = _hook
```

## Better front-ends (same engine)

Plain `pdb` works everywhere with zero installs, but the ergonomics are
dated. Drop-in upgrades:

- **`ipdb`** - `pdb` with IPython's tab-completion, syntax highlighting, and
  better tracebacks. `PYTHONBREAKPOINT=ipdb.set_trace`.
- **`pdb++`** (`pdbpp`) - a monkey-patching upgrade: install it and plain
  `pdb`/`breakpoint()` gains sticky mode, syntax highlighting, and smarter
  `list`. No code changes.
- **`web-pdb`**, **`remote-pdb`** - expose the prompt over a socket / browser
  so you can debug a process you can't attach a terminal to (see below).
- **IDE debuggers** (VS Code, PyCharm, `debugpy`) speak the Debug Adapter
  Protocol and give you the same capabilities with a GUI and remote-attach.

## `pdb` in production - use with care

The hard rule: **at a `(Pdb)` prompt, the thread is frozen.** In a web
server that can mean held connections, tripped healthchecks, and cascading
restarts. So plain `breakpoint()` is a **development** tool. For production
you have safer options:

**1. Keep it disabled by default.** Ship with `PYTHONBREAKPOINT=0` set in
the environment so any stray `breakpoint()` is a no-op. Flip it only on a
single instance you've drained.

**2. Post-mortem logging, not interactive prompts.** Instead of blocking,
capture the state and move on: on exception, log `traceback.format_exc()`
plus the failing frame's locals, or trigger a **core dump** and analyze it
later with `pystack core` (see [`08_pystack.md`](08_pystack.md)). You get
the forensic value of a debugger without stopping traffic.

**3. Remote pdb, on a drained instance.** When you genuinely need an
interactive session against a running service, expose `pdb` over a socket
rather than stdin/stdout, and only do it on an instance pulled out of the
load balancer. This repo has a worked example:
[`05_production_playbook/01_remote_pdb_server.py`](../05_production_playbook/01_remote_pdb_server.py).

**4. Signal-triggered, opt-in.** Rather than a hard-coded `breakpoint()`,
wire a signal handler that starts a (remote) debugger only when you send it
`SIGUSR1` - so the debugger exists but is dormant until you ask. See
[`05_production_playbook/02_diagnostics_signal_server.py`](../05_production_playbook/02_diagnostics_signal_server.py).

## When to reach for `pdb`

- You **own** the process and want to *interact* - inspect, test a fix in
  place, step through logic - not just snapshot it.
- You're chasing a bug you can reproduce locally or in a controlled env.
- You have an exception and want to poke at the exact state that caused it
  (`post_mortem`), which a bare traceback can't give you.

Reach for `py-spy`/`pystack` instead when the process is untouchable,
hung and can't run the debugger, or you must not stop it. The comparison
table lives in [`06_py_spy_dump.md`](06_py_spy_dump.md).
