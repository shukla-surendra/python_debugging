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

### Full option reference for `dump`

| Flag | What it does | When you want it |
|---|---|---|
| `--pid <PID>` / `-p` | Target an already-running process | The normal case |
| `--locals` / `-l` | Show local variables in each frame | You need the *arguments*, not just the function - e.g. *which* URL / SQL / key is stuck. Repeat (`-ll`) to expand nested objects |
| `--full-filenames` | Print absolute paths instead of shortened ones | Disambiguating same-named modules |
| `--json` | Machine-readable output | Feeding an alerting/automation pipeline (see production section) |
| `--subprocesses` / `-s` | Also walk child processes | `multiprocessing`, `gunicorn`/`celery` worker pools - the parent PID alone tells you nothing |
| `--native` / `-n` | Interleave native C/C++ frames with Python frames | The stall is inside a C extension (numpy, a DB driver) or CPython itself; requires debug symbols to be useful |
| `--nonblocking` | Don't pause the process while reading | A latency-critical process you must not stop for even ~1ms; trade-off is you can get a slightly inconsistent stack |

By default `py-spy dump` **briefly pauses** the target (via `ptrace`) to
read a consistent snapshot, then resumes it - typically sub-millisecond.
`--nonblocking` skips the pause at the cost of possibly catching a thread
mid-transition.

```bash
sudo py-spy dump --pid 12345 --locals       # show local variables per frame
sudo py-spy dump --pid 12345 --json         # machine-readable output
sudo py-spy dump --pid 12345 --subprocesses # also dump child processes
sudo py-spy dump --pid 12345 --native       # include C/C++ frames
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

## Using `py-spy` in production

`py-spy` is the single most useful "attach to a running prod process"
tool because it needs **zero** cooperation from the target - no imports,
no signal handler, no restart. Common real-world patterns:

**1. Bundle it in your image, invoke on demand.** Add `py-spy` to the
container/host so it's already there during an incident. Then, when a pod
is wedged:

```bash
kubectl exec -it <pod> -- py-spy dump --pid 1
```

The main app is usually PID 1 in a container. This needs
`SYS_PTRACE` - add it to the pod's `securityContext.capabilities` (or run
the debug step as a sidecar/ephemeral container with that capability)
*before* you need it; you can't add a capability to a running container.

**2. Non-disruptive sampling of a live service.** Because sampling is
out-of-process and low-overhead, you can safely run `py-spy record` against
a real production process for 30-60s to capture a flamegraph of an
*ongoing* slowness, then let it go - no redeploy, no profiler wrapper in
the hot path.

**3. Automated capture on your own alert.** Wire `py-spy dump --json` into
a watchdog: when your healthcheck / p99-latency alert fires, have it grab
a JSON stack dump of every worker and attach it to the incident. You get
the stack *at the moment things were bad*, not after you've SSH'd in and
the process has recovered.

**4. Continuous profiling.** Managed continuous profilers (Grafana Pyroscope,
Datadog, Polar Signals) use the same `py-spy`/eBPF sampling approach to
keep a rolling flamegraph of every service - so you can look *backwards* at
a past latency spike. `py-spy` is the manual, no-infrastructure version of
the same idea.

### Production gotchas

- **`ptrace` permission.** See the top of this doc. In k8s/Docker you need
  `SYS_PTRACE`; on bare hosts you may need `sudo` or a relaxed
  `kernel.yama.ptrace_scope`. Sort this out in advance.
- **Musl / Alpine images.** `py-spy` ships glibc and musl wheels, but very
  stripped images sometimes need the `--full-filenames` / symbol info to
  resolve frames. Prefer `-slim` (glibc) base images if you can.
- **Pausing.** The default brief pause is fine for almost everything; reach
  for `--nonblocking` only on a hard-realtime path.
- **Native frames need symbols.** `--native` is only useful if debug info
  for the C extension / interpreter is present; on a stripped production
  build you'll get addresses, not names. `pystack` (next doc) and `gdb`
  are stronger for the native side - see
  [`08_pystack.md`](08_pystack.md) and
  [`07_gdb_python_extension.md`](07_gdb_python_extension.md).

## When to reach for `py-spy`

- A production process is hung and you need an answer **now**, without
  restarting it (which would lose the evidence).
- You suspect a deadlock between threads.
- You want a CPU profile of a process you didn't start under a profiler.
- The process is too slow under `cProfile`'s overhead to reproduce the
  issue (sampling has near-zero overhead).

## `py-spy` vs. `pystack` vs. `pdb`

| | `py-spy` | `pystack` | `pdb` |
|---|---|---|---|
| Attaches to a running process | yes | yes | no (must be in-process) |
| Needs code changes | no | no | yes (`breakpoint()`) |
| Interactive (step/inspect/mutate) | no | no | **yes** |
| Reads a **core dump** | no | **yes** | no |
| Native (C/C++) frames | with symbols | **yes, first-class** | no |
| Continuous / sampling profile | **yes** | no (snapshot only) | no |
| OS support | Linux/macOS/Windows | **Linux only** | anywhere |

Rule of thumb: **`py-spy`** for "what's it doing / where's the time going"
on a live process across any OS; **`pystack`** when you need native frames
or you only have a core dump; **`pdb`** when you want to *interact* with a
process you control. The next two docs cover `pystack` and a deeper `pdb`
walkthrough.
