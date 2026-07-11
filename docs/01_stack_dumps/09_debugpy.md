# `debugpy` - interactive debugging over the network (IDE + remote attach)

`pdb` ([`05_pdb_deep_dive.md`](05_pdb_deep_dive.md)) is interactive but tied
to whatever terminal owns the process's stdin/stdout. That falls apart the
moment the process is a container, a `gunicorn` worker, a systemd service,
or anything you can't just type into. `debugpy` fixes that: it's the
Microsoft-maintained debug engine behind **VS Code** and (optionally)
**PyCharm**, and it speaks the **Debug Adapter Protocol (DAP)** over a
socket. Same capabilities as `pdb` - breakpoints, stepping, watches,
inspect/mutate locals - but you attach a **GUI from anywhere**.

Think of it as the grown-up, remote-attachable `pdb`.

## Install

```bash
pip install debugpy
```

## 1. Launch a script under the debugger, waiting for an IDE

```bash
python -m debugpy --listen 5678 --wait-for-client myapp.py
#   --listen 5678          open a DAP server on 127.0.0.1:5678
#   --wait-for-client      block at startup until your IDE attaches
#   --listen 0.0.0.0:5678  (for containers/remote - bind all interfaces)
```

Then in VS Code, add an **attach** configuration (`.vscode/launch.json`):

```json
{
  "name": "Attach",
  "type": "debugpy",
  "request": "attach",
  "connect": { "host": "127.0.0.1", "port": 5678 },
  "pathMappings": [
    { "localRoot": "${workspaceFolder}", "remoteRoot": "/app" }
  ]
}
```

`pathMappings` is the part people miss: when the code runs in a container at
`/app` but lives locally at your workspace root, this tells the IDE how to
line up breakpoints. Omit it when local and remote paths are identical.

## 2. Attach to a process you already wrote (programmatic)

Add a few lines to your own app so it can be debugged on demand:

```python
import debugpy

debugpy.listen(("127.0.0.1", 5678))   # start the DAP server
debugpy.wait_for_client()             # (optional) block until IDE attaches
debugpy.breakpoint()                  # a code breakpoint that fires in the IDE
```

`debugpy.breakpoint()` is the DAP equivalent of `breakpoint()` - execution
stops there and control appears in your editor. You can also just set
breakpoints in the IDE gutter after attaching; no code marker needed.

Like `pdb`, you can gate this behind `PYTHONBREAKPOINT`:

```bash
PYTHONBREAKPOINT=debugpy.breakpoint python myapp.py
```

## 3. Subprocesses and multiprocessing

Web servers and worker pools fork children; a debugger attached to the
parent sees nothing the children do. `debugpy` can follow them:

- VS Code: set `"subProcess": true` in the launch config.
- CLI: `python -m debugpy --listen 5678 --configure-subProcess true ...`

This mirrors `py-spy --subprocesses` (module 1) but for *interactive*
debugging - vital for `gunicorn`/`uvicorn`/`celery`, where the real work
happens in the children (see also
[`../04_concurrency_debugging/`](../04_concurrency_debugging/README.md)).

## `debugpy` in production - same cautions as `pdb`, plus a network

Everything in the "pdb in production" section of
[`05_pdb_deep_dive.md`](05_pdb_deep_dive.md) applies: **a hit breakpoint
freezes that thread**, which in a live server means stalled requests and
tripped healthchecks. On top of that, `debugpy` opens a socket that grants
**arbitrary code execution** to whoever connects. So:

- **Bind to `127.0.0.1` only.** Never `0.0.0.0` on a public interface.
  Reach a remote/container instance through an **SSH tunnel** or
  `kubectl port-forward`, not an exposed port. (Same rule as the remote-pdb
  console in [`../05_production_playbook/`](../05_production_playbook/README.md).)
- **Only on a drained instance.** Pull it out of the load balancer first, so
  a paused thread doesn't take traffic down with it.
- **Off by default.** Don't leave `wait_for_client()` in a startup path - a
  crashed/restarted pod would hang forever waiting for a debugger. Gate the
  whole thing behind a flag or a signal handler so it's dormant until asked.

For a "connect and poke at a live service" workflow that's designed for
production from the start, the stdlib remote-pdb console in
[`../05_production_playbook/01_remote_pdb_server.py`](../05_production_playbook/01_remote_pdb_server.py)
is a lighter-weight alternative when you don't need the GUI.

## When to reach for `debugpy`

- You want a **real IDE debugger** (breakpoints in the gutter, variable
  panes, watch expressions) instead of the `(Pdb)` prompt.
- The process is **remote or containerized** and you can't attach a terminal.
- You need to debug **subprocesses/workers** interactively.

Reach for `pdb` when you just want a zero-install prompt in a terminal you
already control, and for `py-spy`/`pystack` when the process is untouchable,
hung, or must not be stopped.
