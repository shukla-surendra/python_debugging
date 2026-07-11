# 6. Observability & auxiliary tools - the layers around your code

Modules 1-5 are about pointing a tool at *one* process and asking "what is
it doing / where's the time / where's the RAM". This module is about the
tools that live in the **layers around** that:

- **Below** your Python code: already covered by the OS-level tools in
  [`../01_stack_dumps/10_os_level_introspection.md`](../01_stack_dumps/10_os_level_introspection.md)
  (`strace`/`lsof`/`/proc`).
- **Alongside** your code, as lightweight dev aids: trace-what-ran and
  print-debugging-done-right (`PySnooper`, `snoop`, `hunter`, `icecream`,
  `rich`), "which lines actually executed" (`coverage.py`), and debugging
  straight from a failing test (`pytest`).
- **Above** your code, across a whole fleet or request path: the always-on
  **logging** baseline, production **error tracking** (Sentry), and
  **distributed tracing** (OpenTelemetry).

```
above   logging / Sentry / OTel    what happened / crashed / which service   (03, 04, 05)
------  ------------------------------------------------------------------
your    py-spy / pystack / pdb     which function / line          (modules 1-5)
code    snoop / rich / coverage / pytest   which lines ran, with values   (01, 02, 06)
------  ------------------------------------------------------------------
below   strace / lsof / /proc      which syscall / fd             (module 1)
```

None of these replace the profilers and debuggers - they answer questions
those tools can't: *"what happened on that one failing request last night,
across three services, when I wasn't watching?"*

## Concepts

- **Aggregation over a fleet.** A traceback in your terminal helps one
  developer once. **Sentry** collects every exception across every instance,
  deduplicates them, and keeps the context (locals, request, release) - so
  you learn about bugs before users report them.
- **Correlation across services.** When a request touches web -> queue ->
  worker -> DB, no single-process tool can follow it. **OpenTelemetry**
  propagates a trace ID across service boundaries so the whole request is one
  connected timeline.
- **Dev-time visibility is cheap.** You don't always need a debugger. A
  `@snoop` decorator or an `ic()` call often answers "what value did this
  have and which branch ran" faster than attaching `pdb`.
- **Coverage is a debugging tool, not just a test metric.** "Which lines
  actually ran?" instantly disproves "but that code can't have executed".

## Files in this module

| File | Demonstrates |
|---|---|
| `01_lightweight_tracing.md` | `PySnooper`, `snoop`, `hunter`, `icecream`, `rich` - trace/print debugging without a debugger |
| `02_coverage.md` | `coverage.py` to prove which lines/branches ran |
| `03_sentry.md` | Production error tracking: aggregate exceptions with full context across a fleet |
| `04_opentelemetry.md` | Distributed tracing: follow one request across multiple services |
| `05_logging.md` | `logging` done right + structured logging + correlation IDs - the always-on baseline |
| `06_pytest_debugging.md` | Debugging from tests: `--pdb`, `--trace`, `--lf`, `--showlocals`, fixtures |

## When you're in this module

You've moved past "reproduce it locally and attach a tool" and into "it
happened in production, possibly across services, and I need to have been
recording". Wire these in *ahead of time* - the same philosophy as
[`../05_production_playbook/`](../05_production_playbook/README.md).
