<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 16 — Linux Commands Cheat Sheet

A terminal-ready reference for every Linux memory command in this book. Each
entry: **what it's for**, the **commands you'll actually type**, and **what to
look at**. Chapter 12 explains *when* to reach for each; this is the *how*.

> Legend: `$PID` = target process id. Many commands need `sudo` for other users'
> processes or kernel data. Inside containers, per-process/`/proc` views work but
> `free`/`/proc/meminfo` show the **host** — read `/sys/fs/cgroup/memory.*`
> instead (Ch 7.6, and Ch 18 for the k8s cheat sheet).

## 16.1 The 30-second triage sequence

```bash
free -h -w                              # node RAM: watch 'available', not 'free'
ps -o pid,rss,vsz,%mem,cmd --sort=-rss | head   # top memory processes (RSS, KB)
top -o %MEM                             # live, sort by memory (press M)
vmstat 1 5                              # swap in/out (si/so) => pressure?
grep -E '^(Rss|Pss|Anonymous|Swap):' /proc/$PID/smaps_rollup   # honest per-proc
```

## 16.2 top — live process view

```bash
top                    # M = sort by mem, then look at RES; P = sort by CPU
top -o %MEM            # start sorted by memory
top -H -p $PID         # per-THREAD view of one process
top -b -n1 | head -20  # batch mode (scriptable snapshot)
```
- **Look at:** `RES` (=RSS, real memory — but over-counts shared, Ch 3.3), `%MEM`,
  `SHR` (shared). Ignore `VIRT` for sizing. `Mem`/`Swap` summary lines up top.

## 16.3 htop — friendlier TUI

```bash
htop                   # F6 sort (RES/MEM/M_SHARE); F2 setup to add MEM columns
htop -p $PID           # follow one process; F5 = tree view
```
- **Look at:** color bar (green=used, yellow=cache/buffers, blue=cache). Add a
  **PSS** column via Setup on kernels that expose it (truer than RES).

## 16.4 ps — scriptable snapshots

```bash
ps -o pid,rss,vsz,%mem,comm --sort=-rss | head    # top RSS (KB)
ps -o rss= -p $PID                                 # just RSS for scripts
ps -eo pid,rss,comm | awk '{s+=$2} END{print s/1024" MB total RSS"}'
ps -o pid,nlwp,rss -p $PID                         # nlwp = thread count
```
- **Look at:** `RSS`/`VSZ` (KB). `rss=` (empty header) is ideal for scripting.

## 16.5 free — system memory & the `available` truth

```bash
free -h -w             # human, split buffers/cache
free -m -s 2           # MB, refresh every 2s
```
- **Look at:** **`available`** (can be allocated without swapping — the real
  headroom, Ch 3.12), `buff/cache` (reclaimable), `shared` (tmpfs/`/dev/shm`),
  swap `used`. **Low `free` is normal.** Container caveat: shows host (Ch 7.7).

## 16.6 vmstat — pressure & paging over time

```bash
vmstat 1               # 1s samples (first row = since boot; ignore it)
vmstat -s              # one-shot memory stats table
vmstat -w 1 10         # wide, 10 samples
```
- **Look at:** `si`/`so` (swap **in/out** — nonzero & sustained = thrashing,
  Ch 6.6), `free`, `buff`, `cache`, `b` (procs blocked on I/O). This is the
  swap-thrash detector.

## 16.7 iostat — is memory pressure causing disk I/O?

```bash
iostat -xz 1           # extended per-device; needs sysstat
```
- **Look at:** high `%util`/`await` alongside swap activity ⇒ paging is hitting
  disk (major faults, Ch 6.4). Correlate with `vmstat` si/so.

## 16.8 pidstat — per-process rates over time

```bash
pidstat -r 1                   # ALL procs: minflt/s, majflt/s, VSZ, RSS, %MEM
pidstat -r 1 -p $PID           # one process
pidstat -r 1 | sort -k5 -n     # sort by majflt/s (major faults = latency, Ch 6.4)
```
- **Look at:** **`majflt/s`** (major faults/sec — the p99 killer), `minflt/s`
  (normal, ignore), `RSS` trend.

## 16.9 smem — PSS / USS (the honest tool)

```bash
smem -k -c "pid user command rss pss uss" --sort=pss    # apportioned view
smem -r -k -c "pid pss uss command" | head              # worst PSS first
smem -tk -P python                                       # totals for python procs
smem -u -k                                               # per-user totals
smem -m -k -P python                                     # per-MAPPING breakdown
```
- **Look at:** **`PSS`** (fair share incl. shared — sums correctly across procs,
  Ch 3.4), **`USS`** (private, dies-with-process — best leak signal, Ch 3.5).
  Install: `apt/dnf install smem`.

## 16.10 pmap — one process's mappings

```bash
pmap -x $PID | sort -k3 -n | tail       # biggest RSS mappings
pmap -x $PID | tail -1                   # total line (RSS/dirty)
pmap -X $PID                             # extended (PSS, referenced, etc.)
```
- **Look at:** big **anonymous** blocks (native buffers/arenas, Ch 5), mmap'd
  files, `[heap]`, `[stack]`. Many `rw-p` anon chunks = glibc arenas (Ch 5.9).

## 16.11 /proc — ground truth, no install

```bash
grep -E 'VmRSS|VmSize|VmData|VmStk|VmSwap|VmPTE|Threads' /proc/$PID/status
grep -E '^(Rss|Pss|Private_Clean|Private_Dirty|Shared_Clean|Anonymous|Swap):' \
     /proc/$PID/smaps_rollup                      # aggregated PSS/USS/anon
cat /proc/$PID/maps                               # every mapping (classify, Ch 2.11)
grep -E '^(MemTotal|MemFree|MemAvailable|Buffers|Cached|AnonPages|Slab|SwapFree):' \
     /proc/meminfo                                # system-wide (Ch 3.11)
ps -o min_flt,maj_flt -p $PID                     # cumulative faults
ls /proc/$PID/fd | wc -l                          # open fd count (fd leak? Ch 3.13)
```
- **Look at:** `VmRSS`/`VmSwap` (status), `Pss`+`Private_*` (smaps_rollup ≈ USS),
  `MemAvailable`/`AnonPages`/`Slab` (meminfo).

## 16.12 lsof — open files & sockets (fd/kernel memory)

```bash
lsof -p $PID | wc -l                    # how many fds this process holds
lsof -p $PID | awk '{print $5}' | sort | uniq -c | sort -rn   # by fd type
lsof -nP -iTCP -sTCP:ESTABLISHED | wc -l                       # open sockets
```
- **Look at:** growing fd counts ⇒ fd/socket leak ⇒ kernel/slab memory growth &
  possible OOM with small user RSS (Ch 3.13, 13 S5e).

## 16.13 strace — watch allocation syscalls

```bash
strace -f -e trace=memory -p $PID           # live mmap/munmap/brk/mprotect
strace -f -e trace=memory -c -p $PID         # summary counts (Ctrl-C to print)
strace -f -e trace=mmap,munmap python app.py 2>&1 | grep -c mmap
```
- **Look at:** frequent `mmap`/`munmap` (allocator churn), rising `brk` (heap
  growth). Heavy overhead — short windows only.

## 16.14 perf — fault events & allocation stacks (advanced)

```bash
perf stat -e page-faults,minor-faults,major-faults -p $PID sleep 10
perf record -e page-faults -p $PID -g -- sleep 10 && perf report   # fault stacks
perf top -e page-faults                                            # live fault hot spots
```
- **Look at:** major-fault counts/stacks (where faults originate). Needs
  `perf_event_paranoid` relaxed / privileges.

## 16.15 sar — historical memory (what happened at 3 a.m.)

```bash
sar -r 1 5             # memory util samples (kbmemfree, kbmemused, %memused, cache)
sar -r -f /var/log/sysstat/sa$(date +%d)     # replay today's stored samples
sar -B 1 5             # paging: pgpgin/s, pgpgout/s, majflt/s, pgscan
sar -S 1 5             # swap utilization
sar -W 1 5             # swap in/out rates
```
- **Look at:** historical `%memused`, `majflt/s`, `pgscan` spikes at the incident
  time. Needs `sysstat` collecting (`/etc/cron.d/sysstat`).

## 16.16 slabtop — kernel object (slab) memory

```bash
sudo slabtop -o | head                  # top slab caches by size (one-shot)
sudo slabtop -s c                        # sort by cache size
grep -E '^(Slab|SReclaimable|SUnreclaim|KernelStack):' /proc/meminfo
awk '{print $1, $2*$4/1024/1024 " MB"}' /proc/slabinfo | sort -k2 -rn | head
```
- **Look at:** big `dentry`/`inode`/socket caches (fd/socket churn),
  `SUnreclaim` (pinned kernel memory). Relevant when RSS is small but OOM happens
  (Ch 3.13).

## 16.17 cgroup files (containers) — your real limits

```bash
cat /sys/fs/cgroup/memory.max           # hard limit (v2)  ("max" = unlimited)
cat /sys/fs/cgroup/memory.current       # current usage
grep -E '^(anon|file|shmem|slab|kernel_stack|sock|inactive_file)' \
     /sys/fs/cgroup/memory.stat         # THE classifier (Ch 10.5, 13 S3)
cat /sys/fs/cgroup/memory.events        # oom / oom_kill / high / max counts
# v1 fallback:
cat /sys/fs/cgroup/memory/memory.limit_in_bytes
cat /sys/fs/cgroup/memory/memory.usage_in_bytes
```
- **Look at:** `anon` vs `shmem` vs `file` vs `slab` (routes your diagnosis),
  `oom_kill` count. Working set ≈ `memory.current − inactive_file` (Ch 3.14).

## 16.18 OOM & dmesg — who died and why

```bash
dmesg -T | grep -iE 'killed process|out of memory|oom'      # kernel OOM lines
journalctl -k | grep -i oom                                  # same via journald
cat /proc/$PID/oom_score                                     # current OOM score
cat /proc/$PID/oom_score_adj                                 # bias (-1000..1000)
```
- **Look at:** the `Out of memory: Killed process <pid> (<name>) total-vm/anon-rss`
  line (Ch 6.11) — names the victim and its RSS at death.

## 16.19 Huge pages / THP (RSS-bloat suspect)

```bash
cat /sys/kernel/mm/transparent_hugepage/enabled     # [always] madvise never
grep -i huge /proc/meminfo                           # AnonHugePages, HugePages_*
grep AnonHugePages /proc/$PID/smaps_rollup           # THP used by this process
echo madvise | sudo tee /sys/kernel/mm/transparent_hugepage/enabled   # mitigate
```
- **Look at:** large `AnonHugePages` = THP inflating RSS (Ch 6.7).

## 16.20 One-liners you'll reuse

```bash
# Live RSS of a process, refreshed:
watch -n1 "grep VmRSS /proc/$PID/status"

# Total RSS of all python processes (approx, over-counts shared):
ps -eo rss,comm | awk '/python/{s+=$1} END{print s/1024" MB"}'

# Fair-share total for python (PSS, honest):
smem -tk -c pss -P python | tail -1

# Sample working set inside a container every 30s (Ch 13 S4):
while cat /sys/fs/cgroup/memory.current; do sleep 30; done

# Biggest anon mapping of a process (native buffer / arena):
pmap -x $PID | awk '$0!~/[a-z].so/ && $3+0>0' | sort -k3 -n | tail

# Watch swap pressure:
vmstat 1 | awk 'NR>2{print $7, $8}'   # si so
```

## 16.21 Command → job quick index

| I want to… | Command |
|---|---|
| Node headroom | `free -h -w` → `available` |
| Top memory processes | `ps --sort=-rss` / `top -o %MEM` |
| Honest fleet total (no double count) | `smem -tk -c pss` |
| Find the leaking worker | `smem -r -c "pid uss"` (USS) |
| Big regions of one process | `pmap -x $PID` |
| Per-proc PSS/USS fast, no install | `/proc/$PID/smaps_rollup` |
| Swap thrashing | `vmstat 1` (si/so) |
| Major-fault storm | `pidstat -r 1` (majflt/s) |
| Kernel/slab OOM, small RSS | `slabtop`, `lsof \| wc -l` |
| Historical (3 a.m.) memory | `sar -r` / `sar -B` |
| Container real limit/usage | `/sys/fs/cgroup/memory.{max,current,stat}` |
| Who got OOM-killed | `dmesg -T \| grep -i oom` |
| THP RSS bloat | `grep AnonHugePages /proc/$PID/smaps_rollup` |
| Allocation syscalls live | `strace -f -e trace=memory -p $PID` |
| Fault stacks | `perf record -e page-faults -g` |

---

## Key takeaways

- **Triage order:** `free -h -w` (node headroom via `available`) → `ps
  --sort=-rss`/`top` (which process) → `smem`/`smaps_rollup` (honest PSS/USS) →
  `vmstat`/`pidstat` (pressure/faults) → cgroup files (container truth).
- **Use PSS/USS (`smem`, `smaps_rollup`), not `top`'s RES**, for real totals and
  leak-hunting; `VSZ` is noise.
- **`vmstat` si/so + `pidstat` majflt/s** are your pressure/latency detectors;
  **`slabtop` + `lsof`** catch kernel/fd OOMs with small user RSS.
- **In containers, `free`/`meminfo` lie — read `/sys/fs/cgroup/memory.*`**, and
  `memory.stat` (`anon`/`shmem`/`file`/`slab`) is the diagnostic fork (Ch 13).
- **`dmesg -T | grep -i oom`** names the OOM victim and its RSS at death.

## Practice exercises

1. Run the §16.1 triage sequence on your machine; write one sentence interpreting
   each output.
2. For one process, get its RSS three ways (`ps`, `top`, `smaps_rollup`) and its
   PSS/USS (`smem`); reconcile why RSS ≥ PSS ≥ USS.
3. Trigger light swap (allocate near RAM size) and watch `vmstat` si/so and
   `pidstat -r` majflt/s move.
4. Build a one-liner that prints the top-5 processes by **USS** using `smem`.

## Quiz questions

1. Which `free` column answers "am I about to run out of RAM," and why not
   `free`?
2. Which command gives a correct multi-process RAM total and why is summing
   `top`'s RES wrong?
3. You see OOM kills but every process's RSS is small. Which two commands do you
   run and what are you looking for?
4. What do `si`/`so` in `vmstat` mean, and what does sustained nonzero indicate?
5. Inside a container, why is `free` misleading and what do you read instead?
6. Which command + file tells you whether a container's growth is Python/native
   (`anon`), shared memory (`shmem`), or cache (`file`)?

## Suggested experiments

- Alias the §16.1 sequence into a `mem-triage` shell function and use it next time
  a process looks heavy.
- Compare `ps` summed RSS vs. `smem` summed PSS for all Python processes on a box
  running several workers; quantify the double-counting.
- Set up `sysstat` (`sar`) collection for a day, then replay `sar -r`/`sar -B`
  around a load spike to see historical memory/paging.

---

*Next up: **Chapter 17 — Python Memory Cheat Sheet**, the code-level companion to
this chapter: `gc`, `sys.getsizeof`, `tracemalloc`, `resource`, `psutil`,
`objgraph`, `memory_profiler` — snippets you can paste into any script or REPL.*

[← Chapter 15](15_optimization.md) · [Back to index](README.md) · [Chapter 17 →](17_python_cheatsheet.md)
