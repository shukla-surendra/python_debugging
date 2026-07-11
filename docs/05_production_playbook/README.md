# 5. Production Playbook - debugging without restarting

Modules 1-4 are mostly "run this tool against a process". This module is
about **what to wire into a long-running service ahead of time** so that
when something goes wrong, you have hooks to diagnose it live - and a runbook
for using everything in this repo under incident pressure.

## Concepts

- **External vs. internal tools**: `py-spy`/`gdb` need NO cooperation from
  the target process (read its memory from outside) - they work on ANY
  Python process, planned for or not. Everything else
  (`faulthandler`, `tracemalloc`, remote pdb, signal handlers) needs to be
  **armed before the incident** - a few lines at process startup.
- **Low, constant overhead is the budget**: `faulthandler.enable()` and
  `tracemalloc.start()` cost very little and are safe to leave on in
  production permanently. A remote pdb console costs nothing until someone
  connects. None of this is "turn on heavy profiling and hope".
- **Output to FILES, not stdout**: a signal handler that prints to stdout is
  useless if stdout is `/dev/null` or a pipe nobody's reading. Diagnostics
  handlers should write to a known path.
- **Security**: anything that gives remote code execution (a pdb console)
  must bind to `127.0.0.1` only and be reached via SSH tunnel / internal
  network - never exposed publicly.

## Files in this module

| File | Demonstrates |
|---|---|
| `01_remote_pdb_server.py` | A socket-based `pdb` console for live state inspection/mutation, stdlib only |
| `02_diagnostics_signal_server.py` | One `SIGUSR1` handler that dumps threads + GC + memory + object counts to a file |
| `03_incident_checklist.md` | Runbook: symptom -> tool -> module, tying modules 1-4 together |
| `04_kubernetes_debugging.md` | Running the whole toolbox inside k8s: `exec`/ephemeral containers, `SYS_PTRACE`, probes, core dumps, OOMKilled, `port-forward` |

## Run order

```bash
cd 05_production_playbook
python 01_remote_pdb_server.py
python 02_diagnostics_signal_server.py
```

Then read `03_incident_checklist.md` - it's a reference document for when
something is actually on fire, not a script to run - and
`04_kubernetes_debugging.md` if your service runs in Kubernetes (how to get
the tools *to* the process without the pod getting restarted under you).

## Putting it all together

A service that's "debuggable by default" does this at startup:

```python
import faulthandler
import gc
import signal
import threading
import tracemalloc

faulthandler.enable()                     # module 1 - free
tracemalloc.start()                       # module 3 - cheap, enables diffing later

# ... load config, warm caches, etc ...

gc.collect()
gc.freeze()                               # module 3 - if you fork() workers after this

threading.Thread(
    target=serve_remote_pdb, args=(globals(),), daemon=True, name="debug-console"
).start()                                 # this module, file 01 - 127.0.0.1 only!

install_diagnostics_handler(Path("/var/log/myapp/"), signal.SIGUSR1)
                                           # this module, file 02
```

Total cost: a few milliseconds at startup, negligible steady-state overhead,
and an incident that used to require "redeploy with profiling enabled and
wait for it to happen again" now takes one `kill -USR1` and a `cat`.
