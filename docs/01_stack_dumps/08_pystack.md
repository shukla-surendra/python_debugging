# `pystack` - stack dumps for live processes **and** core dumps, with native frames

`pystack` (from Bloomberg) answers the same question as `py-spy dump` -
"what is every thread doing right now?" - but it is the tool you reach for
when `py-spy` isn't enough:

- You only have a **core dump** (the process already crashed / was killed),
  not a live PID.
- The stall is in **native code** (a C extension, the interpreter, a
  syscall) and you need C/C++ frames interleaved with Python frames as a
  first-class feature, not a best-effort add-on.
- You want extra CPython-level context: which thread **holds the GIL**,
  whether a thread is **running the garbage collector**, and the full
  local variables at each frame.

Like `py-spy`, it needs **zero cooperation** from the target: no imports,
no signal handler, no restart. It reads the process's (or core file's)
memory and reconstructs CPython's internal state.

> **Linux only.** `pystack` relies on `process_vm_readv`/`ptrace` and ELF
> core parsing, so unlike `py-spy` it does not run on macOS or Windows.

## Install

Not in this repo's venv by default (it's Linux-only). Add it with:

```bash
pip install pystack
```

## Permissions

Same story as `py-spy`: attaching to a *running* process uses `ptrace`, so
you may need `sudo`, a relaxed `kernel.yama.ptrace_scope`, or the
`SYS_PTRACE` capability in a container. **Analyzing a core file needs none
of this** - you're reading a file, not another process's memory, which is a
big part of why core-dump analysis is so useful in locked-down prod.

## 1. `pystack remote <PID>` - dump a live process

The direct analogue of `py-spy dump`:

```bash
# Terminal 1
python ../workloads/deadlock.py        # prints: PID = 12345, then hangs

# Terminal 2
sudo pystack remote 12345
```

Expected output (abbreviated) - note it labels the GIL holder and thread
state, which a plain stack dump does not:

```
Traceback for thread 12346 [] (most recent call last):
    (Python) File "threading.py", line 1044, in _bootstrap
    (Python) File "threading.py", line 1082, in _bootstrap_inner
    (Python) File "threading.py", line 1024, in run
    (Python) File "deadlock.py", line 36, in worker_1
    (Python) File "threading.py", line 268, in __enter__
    (Python) File "threading.py", line 482, in acquire
```

Useful flags for `remote`:

| Flag | What it does |
|---|---|
| `--locals` | Print local variables for every frame - the *values* stuck in the call, e.g. which key/URL/SQL |
| `--native` | Interleave native (C/C++) frames with the Python frames |
| `--native-all` | Also show threads that have **only** native frames (no Python) - e.g. a pure-C worker thread |
| `--no-block` | Don't stop the process while reading it (default is to pause via `ptrace` for a consistent snapshot) |
| `--exhaustive` | Don't trust the usual heuristics; scan more aggressively (for corrupted/unusual memory layouts) |
| `--self` | Analyze the very process running `pystack` (mostly for testing) |

```bash
sudo pystack remote 12345 --locals            # values at each frame
sudo pystack remote 12345 --native            # + C/C++ frames
sudo pystack remote 12345 --native-all        # + pure-native threads
sudo pystack remote 12345 --no-block          # don't pause the target
```

## 2. `pystack core <corefile>` - dump from a crash, no live process needed

This is `pystack`'s headline feature. If a process crashed or you killed it
with a core-dumping signal, you can reconstruct its Python stacks *after the
fact* from the core file.

```bash
# Make sure the kernel will actually write cores:
ulimit -c unlimited
cat /proc/sys/kernel/core_pattern        # where cores go (or how they're piped)

# Force a core from a hung process without killing your only copy of "now":
#   gcore <pid>            # writes core.<pid> and lets the process continue
# ...or let a crash/SIGABRT/SIGSEGV/SIGQUIT produce one naturally.

pystack core ./core.12345
```

You usually don't need to pass the executable - `pystack` finds it from the
core's metadata - but you can be explicit and add native frames:

```bash
pystack core ./core.12345 /usr/bin/python3 --native
```

**Cores from another machine / container.** The tricky part of core
analysis is that the shared libraries the core references must be findable.
`pystack` has flags for this:

| Flag | What it does |
|---|---|
| `--native` / `--native-all` | Same as for `remote` - include C/C++ frames |
| `--locals` | Local variables at each frame |
| `--lib-search-path <paths>` | Colon-separated dirs to look for the `.so` files referenced by the core |
| `--lib-search-root <dir>` | A directory tree (e.g. an unpacked container rootfs) to search recursively for matching libraries |

A common workflow: a pod OOM-kills or segfaults, you copy out `core.<pid>`
**and** the container's rootfs (or just re-run `pystack core` inside an
image built from the same layers), then:

```bash
pystack core ./core.12345 --native --lib-search-root ./rootfs
```

## What `pystack` shows that a bare stack dump doesn't

- **GIL holder**: which thread currently owns the Global Interpreter Lock -
  invaluable when threads are starving because one thread won't let go.
- **GC state**: whether a thread is in the middle of a garbage-collection
  pass (a surprisingly common "why did everything pause?" answer).
- **Merged native + Python stacks**: for a stall inside numpy, a database
  driver, `ssl`, or CPython itself, you see the C frames *and* the Python
  frames that called into them, in one stack.

## `pystack` in production

- **Post-mortem is the killer use case.** Configure your service to leave a
  core dump on crash (`ulimit -c unlimited`, a sane `core_pattern`, or a
  crash handler), ship the core to an artifact store, and analyze it later
  with `pystack core` on a workstation. You get the exact Python stack of
  the crash **without** having had a debugger attached and **without**
  ptrace access to prod.
- **`gcore` a wedged process, then keep serving.** `gcore <pid>` snapshots a
  core *without* killing the process. Grab the core, let the process limp
  along or get restarted, and do the analysis offline - the stall is
  frozen in the file.
- **Container debugging.** Because core analysis is just file reading, it
  sidesteps the `SYS_PTRACE` capability you'd otherwise need to attach to a
  live pod. Capture the core in the running container, analyze it anywhere.
- **Native crashes.** When the crash is a segfault deep in a C extension,
  `pystack core --native` is often the *only* tool that ties the native
  fault back to the Python line that triggered it. `py-spy` can't read a
  core at all, and `gdb` alone shows you C frames but not the Python
  call stack without the CPython gdb helpers (see
  [`07_gdb_python_extension.md`](07_gdb_python_extension.md)).

## When to reach for `pystack` (vs. `py-spy`)

Reach for **`pystack`** when:

- You have a **core dump**, not a live process (`py-spy` can't do this).
- You need **reliable native frames** and CPython context (GIL/GC).
- You're on Linux and the extra detail is worth being Linux-only.

Reach for **`py-spy`** when:

- You want **continuous/sampling profiling** or a live `top`-style view.
- You need macOS/Windows support.
- You just want the fastest possible "what's it doing right now" with the
  least ceremony.

They complement each other - many teams keep both in their prod debug
image. See the side-by-side table in
[`06_py_spy_dump.md`](06_py_spy_dump.md), and the incident workflow in
[`05_production_playbook/`](../05_production_playbook/README.md).
