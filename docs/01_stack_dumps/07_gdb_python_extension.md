# `gdb` - the last resort

`py-spy` covers ~95% of "what is this process doing" questions and is
much easier to use. Reach for `gdb` when:

- `py-spy` itself can't attach (some sandboxes/containers block it, or it
  doesn't support your platform/architecture)
- the problem is **inside a C extension** (native deadlock, native crash,
  segfault) and you need C-level frames mixed with Python frames
- you need to actually **interact** with the stuck process (call
  functions, modify memory) rather than just observe it
- you're debugging a **core dump** from a process that already crashed

This file is reference documentation - it's not exercised by an automated
script because it needs system packages (`python3-dbg` / debug symbols)
that may not be installed on your machine.

## Setup

CPython ships a gdb extension script (commonly installed as
`/usr/share/gdb/auto-load/.../python3.X-gdb.py` or similar) that teaches
gdb how to read CPython's internal frame structures and print Python-level
backtraces. On Debian/Ubuntu:

```bash
sudo apt-get install gdb python3-dbg
```

Check it's loaded:

```bash
gdb -p <PID> -batch -ex "python print('gdb python extension OK')"
```

If gdb says `No symbol "PyEval_EvalFrameEx" in current context` or similar
when you try `py-bt`, the extension script isn't loaded for your Python
build - you likely need matching debug symbols (`python3-dbg`, or a
`debuginfod`-enabled gdb on newer distros, which fetches symbols
automatically).

## Attaching to a running process

```bash
sudo gdb -p <PID>
```

Once attached, the process is **paused**. Useful commands:

| Command | What it shows |
|---|---|
| `bt` | Native (C) backtrace - every C stack frame, including the CPython interpreter loop itself |
| `py-bt` | **Python-level** backtrace - just the Python frames, like a traceback |
| `py-list` | Source lines around the current Python frame |
| `py-locals` | Local variables of the current Python frame |
| `thread apply all py-bt` | Python backtrace for **every thread** - the gdb equivalent of `py-spy dump` |
| `continue` | Resume the process (don't forget this!) |
| `detach` | Detach without killing the process |

### Example session against `workloads/deadlock.py`

```bash
# Terminal 1
python workloads/deadlock.py
# PID = 12345

# Terminal 2
sudo gdb -p 12345
```

```
(gdb) thread apply all py-bt

Thread 3 (Thread 0x7f...  "deadlock-worker-2"):
Traceback (most recent call first):
  File "workloads/deadlock.py", line 50, in worker_2
    with second:
  File "threading.py", line 1024, in run
    self._target(*self._args, **self._kwargs)
  ...

Thread 2 (Thread 0x7f...  "deadlock-worker-1"):
Traceback (most recent call first):
  File "workloads/deadlock.py", line 36, in worker_1
    with lock_b:
  File "threading.py", line 1024, in run
    self._target(*self._args, **self._kwargs)
  ...

Thread 1 (Thread 0x7f...  "MainThread"):
Traceback (most recent call first):
  File "threading.py", line 1097, in join
  File "workloads/deadlock.py", line 60, in run
  File "workloads/deadlock.py", line 76, in <module>
```

```
(gdb) detach
(gdb) quit
```

Same diagnosis as `py-spy dump`, but gdb also lets you go one level deeper:

```
(gdb) bt
#0  0x00007f... in __lll_lock_wait () from /lib/x86_64-linux-gnu/libpthread.so.0
#1  0x00007f... in pthread_mutex_lock () from ...
#2  0x00007f... in PyThread_acquire_lock_timed (...)
#3  0x00007f... in lock_PyThread_acquire_lock (...)
#4  0x00007f... in _PyEval_EvalFrameDefault (...)
...
```

This is the only tool in this repo that can show you **both** "the Python
function is `lock.acquire()`" **and** "which libc/pthread call that's
actually blocked in" - essential when the hang is inside a C extension
(e.g. a native mutex held by NumPy/psycopg2/etc.) that py-spy can't fully
symbolicate.

## Debugging a core dump

If a process segfaults and dumps core (`ulimit -c unlimited` beforehand):

```bash
gdb python core
(gdb) py-bt
```

This is often the **only** way to see a Python-level traceback for a crash
that happened entirely inside C code (e.g. a buggy C extension), since by
the time you have a core file the process is gone - `py-spy` and
`faulthandler` both require a live process.

## Summary: pick the right tool

```
Need a Python traceback for a hung/slow process?
├── Can you edit the source and restart?       -> faulthandler.register() / dump_traceback_later
├── No source edits, process still running?    -> py-spy dump / py-spy top   (start here!)
├── py-spy can't attach, or need C-level info? -> gdb + py-bt / thread apply all py-bt
└── Process already crashed, have a core file? -> gdb python core, then py-bt
```
