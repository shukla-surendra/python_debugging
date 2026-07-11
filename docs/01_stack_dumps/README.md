# 1. Stack Dumps - "What is my process doing right now?"

A **stack dump** answers a single question: *for each thread in this
process, what call stack is it currently executing?* That's it. No timing,
no aggregation - just a snapshot of frames.

Stack dumps are your first tool for:

- A process that's **hung** (100% CPU on nothing, or 0% CPU forever)
- A process that's **slow but you can't reproduce it** under a profiler
- Understanding **where an exception came from** (the most familiar case)
- Diagnosing a **deadlock** between threads

## Concepts

- **Frame**: one function call's local state (locals, instruction pointer,
  link to caller's frame). A *call stack* is a linked list of frames from
  the currently-executing one back to `<module>`.
- **Traceback**: Python's name for a stack (specifically, the chain of
  frames associated with an exception, but the term gets used loosely for
  "a stack dump" too).
- `sys._current_frames()`: returns `{thread_id: frame}` for **every**
  thread in the process - this is how you dump stacks for threads that
  aren't the one running your dumping code.
- A dump is **non-deterministic** for things like I/O waits - the frame
  will show `time.sleep` or `lock.acquire`, but not *why* it's been
  waiting 10 minutes. For that you need to correlate with logs/metrics.

## Tool comparison

| Tool | Requires editing target source? | Works if process is hung? | Works from outside the process? |
|---|---|---|---|
| `traceback` | yes | only at the point of a raised exception | no |
| `faulthandler` | yes (call `enable()` once at startup) | yes | no (signal-based, needs cooperative process) |
| `signal` + handler | yes | yes, if the GIL is free enough to run the handler | no |
| `sys._current_frames()` | yes | yes | no |
| `pdb` | yes | n/a (interactive debugging, not a snapshot) | no |
| `py-spy dump` | **no** | **yes** | **yes** (reads process memory) |
| `gdb` | **no** | **yes**, even if the GIL is stuck | **yes** |

The big takeaway: stdlib tools require you to have **planned ahead** (added
`faulthandler.enable()`, a signal handler, etc.) *before* the process got
into trouble. `py-spy` and `gdb` work on **any** running Python process,
which is why they're indispensable for production incidents - see
[`05_production_playbook/`](../05_production_playbook/README.md).

## Files in this module

| File | Demonstrates |
|---|---|
| `01_traceback_module.py` | `traceback.print_exc`, `format_exc`, `extract_stack`, `print_stack` |
| `02_faulthandler_basics.py` | `faulthandler.enable()`, `dump_traceback()`, `dump_traceback_later()` (watchdog) |
| `03_signal_handler_dump.py` | A `SIGUSR1` handler that dumps **all threads'** stacks on demand |
| `04_threading_enumerate_dump.py` | `threading.enumerate()` + `sys._current_frames()` without signals |
| `05_pdb_post_mortem.py` | `pdb.set_trace()`, `breakpoint()`, `pdb.post_mortem()` |
| `06_py_spy_dump.md` | Using `py-spy dump` / `py-spy top` on a live process (no code changes) |
| `07_gdb_python_extension.md` | Using `gdb` + the CPython gdb helpers as a last resort |

## Run order

```bash
cd 01_stack_dumps
python 01_traceback_module.py
python 02_faulthandler_basics.py
python 03_signal_handler_dump.py      # then, in another terminal: kill -USR1 <pid>
python 04_threading_enumerate_dump.py
python 05_pdb_post_mortem.py
```

Then read `06_py_spy_dump.md` and `07_gdb_python_extension.md` and follow
along - those require a second terminal.
