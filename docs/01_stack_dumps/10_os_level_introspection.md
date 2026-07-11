# OS-level introspection - `strace`, `lsof`, `/proc` (below Python)

`py-spy` and `pystack` tell you a thread is parked in `read()`, `acquire()`,
or `poll()`. They **don't** tell you *which* file descriptor, *which* remote
host, or *why it never returns*. For that you drop below Python to the OS,
where these tools are indispensable - and they work on **any** process,
Python or not, with zero code changes.

These are Linux tools (macOS has `dtruss`/`dtrace` analogues). Like `py-spy`,
attaching to another process needs `ptrace` permission - `sudo` or a relaxed
`kernel.yama.ptrace_scope` (see [`06_py_spy_dump.md`](06_py_spy_dump.md)).

## `strace` - watch the system calls a process makes

`strace` traces every syscall a process makes. Point it at a running PID:

```bash
sudo strace -p 12345 -f
#   -p 12345   attach to this PID
#   -f         follow threads AND forked children (almost always want this)
```

If a hung process prints nothing, that itself is the answer - it's **blocked
in a syscall**, and `strace` shows which one it's waiting inside:

```
[pid 12346] futex(0x..., FUTEX_WAIT_PRIVATE, 0, NULL      <-- blocked, no return
[pid 12347] recvfrom(7,                                    <-- blocked reading fd 7
```

- `futex(..., FUTEX_WAIT...)` that never returns = waiting on a lock / the
  **GIL**. Cross-reference with a `py-spy dump` to see which Python lock.
- `recvfrom` / `read` on a socket that hangs = a network peer that isn't
  answering (a slow DB, a dead upstream). `lsof` (below) tells you *who*.
- A tight loop of `epoll_wait` returning immediately = a busy event loop.

Essential `strace` flags:

| Flag | Does |
|---|---|
| `-f` | Follow threads and child processes |
| `-e trace=network` | Only network syscalls (also `file`, `memory`, `signal`, `desc`) |
| `-T` | Show time spent **in** each syscall - find the slow one |
| `-c` | Don't trace live; print a **summary table** of syscall counts + time on exit/detach |
| `-y` | Annotate file descriptors with their paths/sockets |
| `-s 200` | Show up to 200 bytes of string arguments (default truncates at 32) |
| `-tt` | Timestamp every line (microseconds) |
| `-o out.txt` | Write to a file instead of stderr |

The `-c` summary is a fast triage tool - "what is this process spending its
syscall time on?":

```bash
sudo strace -c -f -p 12345      # Ctrl-C after a while to print the table
```

```
% time     seconds  usecs/call     calls    errors syscall
------ ----------- ----------- --------- --------- ----------------
 91.2    4.512000        4512      1000           epoll_wait
  6.1    0.301000          30     10000        50 recvfrom
  ...
```

> `ltrace` does the same for **library** calls rather than syscalls, but it's
> often broken on modern glibc/PIE binaries - reach for it only if `strace`
> plus a Python-level stack dump hasn't answered the question.

## `lsof` - what files/sockets does the process hold open?

Once `strace` shows a hang on "fd 7", `lsof` tells you what fd 7 *is*:

```bash
sudo lsof -p 12345          # every fd this process holds
sudo lsof -p 12345 | grep TCP
```

```
COMMAND   PID  USER   FD   TYPE  DEVICE   NODE NAME
python  12345 app     7u   IPv4  0x...    TCP  10.0.0.5:54210->db-primary:5432 (ESTABLISHED)
```

There's your answer: fd 7 is a Postgres connection to `db-primary` that's
stuck. Also useful:

```bash
sudo lsof -i :8080          # who is listening on / connected to port 8080
sudo lsof +D /var/log       # which processes have files open under a dir
```

Common real-world use: diagnosing **fd leaks** (`lsof -p <pid> | wc -l`
climbing over time → you're not closing sockets/files) - a frequent cause of
`Too many open files` (`EMFILE`) crashes.

## `/proc/<pid>/` - the kernel's live view, no tools required

Everything the kernel knows about a process is a readable file under
`/proc/<pid>/`. Just `cat` it:

| Path | Tells you |
|---|---|
| `status` | Process state (R/S/D/Z), thread count, `VmRSS` (memory) |
| `wchan` | The kernel function the process is sleeping in (one word) |
| `task/` | One subdir **per thread** - drill into individual threads |
| `task/<tid>/stack` | The thread's **kernel** stack (needs root) |
| `fd/` | Symlinks for every open fd (the `lsof` data, tool-free) |
| `io` | Bytes read/written - is it actually doing I/O or truly idle? |
| `limits` | Effective ulimits (open-file cap, etc.) |
| `smaps` / `smaps_rollup` | Detailed memory map (complements module 3) |

```bash
cat /proc/12345/status | grep -E 'State|Threads|VmRSS'
# State:  D (disk sleep)      <-- stuck in uninterruptible I/O
# Threads:        8
# VmRSS:   1048576 kB

ls -l /proc/12345/fd          # tool-free lsof
cat /proc/12345/task/*/stack  # kernel stack per thread (root)
```

A process in state **`D` (uninterruptible sleep)** is blocked on I/O the
kernel won't let it back out of - often a slow/hung disk or NFS mount. No
amount of Python-level poking will unstick it; that's an infrastructure
problem, and `/proc` is how you prove it.

## How this fits with the Python-level tools

The layers stack like this:

```
Sentry / OpenTelemetry     <- "which request, across which services"  (module 6)
py-spy / pystack / pdb     <- "which Python function / line"          (this module)
strace / lsof / /proc      <- "which syscall / fd / kernel state"     (this doc)
```

The winning move for a mysterious hang is to use them **together**: `py-spy`
shows Python is in `socket.recv`, `strace` confirms it's blocked in
`recvfrom` and never returns, and `lsof` names the dead upstream. Each tool
answers a question the layer above it can't.

## When to reach for OS-level tools

- A `py-spy`/`pystack` stack ends in a syscall (`read`, `recv`, `acquire`,
  `poll`) and you need to know **what it's really waiting on**.
- The process shows **0% CPU and won't budge** (likely blocked I/O - check
  `/proc/<pid>/status` for state `D`).
- You suspect an **fd/socket leak** (`lsof` count climbing).
- The problem might not be Python at all - a hung mount, a firewall dropping
  packets, a full disk. These tools see what Python can't.
