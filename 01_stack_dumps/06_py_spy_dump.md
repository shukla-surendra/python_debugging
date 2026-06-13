# `py-spy dump` / `py-spy top` - stack dumps with ZERO code changes

Every tool so far required you to **plan ahead**: call `faulthandler.enable()`,
register a signal handler, etc. `py-spy` needs none of that. It's a
separate Rust binary that reads the target process's memory directly and
reconstructs the Python call stack from CPython's internal data structures.
This means it works on:

- processes you don't control the source of (third-party services, workers)
- processes that are already hung and never called `faulthandler.enable()`
- processes where the GIL itself might be the problem

It's already installed in this repo's venv (`pip install py-spy`).

## Permissions (read this first)

`py-spy` uses `ptrace` (Linux) to read another process's memory. Depending
on your system's `kernel.yama.ptrace_scope` setting, you may need:

```bash
# Run py-spy as root / with sudo:
sudo py-spy dump --pid <PID>

# ...or temporarily relax ptrace restrictions (requires root):
sudo sysctl -w kernel.yama.ptrace_scope=0

# In Docker, you need:
docker run --cap-add=SYS_PTRACE ...
```

If you don't have permission, you'll see exactly this:

```
$ py-spy dump --pid 30788
Permission Denied: Try running again with elevated permissions by going 'sudo env "PATH=$PATH" !!'
```

`py-spy record` and `py-spy top` can avoid this entirely by **launching**
the target process themselves (so py-spy is the parent and ptrace is
allowed) - just put the command after `--`. We use that approach below
for the parts of this guide that don't need `sudo`.

## 1. `py-spy dump --pid <PID>` - one-shot stack dump

This is the direct equivalent of `faulthandler.dump_traceback()`, but from
**outside** the process.

```bash
# Terminal 1
python ../workloads/deadlock.py
# prints: PID = 12345
#         Running WITHOUT --safe: this will deadlock and hang forever.

# Terminal 2
sudo py-spy dump --pid 12345
```

Expected output (abbreviated) - notice **both** worker threads are stuck on
`acquire`, each holding the lock the other one wants:

```
Process 12345: python ../workloads/deadlock.py
Python v3.14.4

Thread 0x7F... (active): "deadlock-worker-1"
    acquire (threading.py:482)
    __enter__ (threading.py:268)
    worker_1 (deadlock.py:36)
    run (threading.py:1024)
    _bootstrap_inner (threading.py:1082)
    _bootstrap (threading.py:1044)

Thread 0x7F... (active): "deadlock-worker-2"
    acquire (threading.py:482)
    __enter__ (threading.py:268)
    worker_2 (deadlock.py:50)
    run (threading.py:1024)
    _bootstrap_inner (threading.py:1082)
    _bootstrap (threading.py:1044)

Thread 0x7F... (idle): "MainThread"
    join (threading.py:1097)
    run (deadlock.py:60)
    <module> (deadlock.py:76)
```

Both threads are blocked at `__enter__` (i.e. `lock.acquire()`) inside
`worker_1`/`worker_2`. Cross-referencing `deadlock.py`:

- `worker_1` holds `lock_a`, waiting for `lock_b`
- `worker_2` holds `lock_b`, waiting for `lock_a`

That's the deadlock, diagnosed **without stopping the process or having
added a single line of diagnostic code**.

Useful flags:

```bash
sudo py-spy dump --pid 12345 --locals       # show local variables per frame
sudo py-spy dump --pid 12345 --json         # machine-readable output
sudo py-spy dump --pid 12345 --subprocesses # also dump child processes
```

## 2. `py-spy top --pid <PID>` - live "top" for Python call stacks

```bash
sudo py-spy top --pid 12345
```

This repeatedly samples the process (default 100 Hz) and shows a live,
`top`-style table of which functions are currently "%Own Time" / "%Total
Time" busiest - across **all threads**, updated in place. Press `q` to quit.

For a CPU-bound workload, point it at `cpu_bound.py`:

```bash
python ../workloads/cpu_bound.py --seconds 30 &
sudo py-spy top --pid $!
```

You'll see `fibonacci`, `sum_of_squares`, and `string_churn` near the top,
roughly proportional to the time spent in each.

## 3. `py-spy record` - flamegraphs without `sudo` (spawn mode)

If you don't have `ptrace` permissions, let `py-spy` launch the process
itself - this was verified to work in this repo's sandbox:

```bash
cd 01_stack_dumps
py-spy record -o profile.svg -- \
    ../.venv/bin/python ../workloads/cpu_bound.py --seconds 3
```

Output:

```
py-spy> Sampling process 100 times a second. Press Control-C to exit.
py-spy> Stopped sampling because process exited
py-spy> Wrote flamegraph data to 'profile.svg'. Samples: 317 Errors: 0
```

Open `profile.svg` in a browser - it's an interactive flamegraph. Each box
is a function; width = fraction of samples where that function was on the
stack. You should see three towers rising from `one_round`: one for
`sum_of_squares`, one for `string_churn`, and a deep, narrow recursive
tower for `fibonacci`.

This is covered in more depth as a *profiling* tool (not just a stack-dump
tool) in [`02_cpu_profiling/README.md`](../02_cpu_profiling/README.md).

## When to reach for `py-spy`

- A production process is hung and you need an answer **now**, without
  restarting it (which would lose the evidence).
- You suspect a deadlock between threads.
- You want a CPU profile of a process you didn't start under a profiler.
- The process is too slow under `cProfile`'s overhead to reproduce the
  issue (sampling has near-zero overhead).
