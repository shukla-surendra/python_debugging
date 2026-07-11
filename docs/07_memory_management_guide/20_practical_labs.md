<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 20 — Practical Labs

Reading builds models; *doing* builds intuition. These labs turn every major
concept in the book into a hands-on exercise you run yourself, each with a
**goal**, **steps**, **expected output** (approximate — numbers vary by machine),
and **what it proves**. They use only this repo's `workloads/` +
`docs/03_memory_profiling/` demos and standard tools.

> Setup: `python3 -m venv .venv && source .venv/bin/activate && pip install -r
> requirements.txt` (Ch: README). Tested on Python 3.14 / Linux x86_64. Numbers
> are illustrative; the *shapes and directions* are the point. Build the docs any
> time with `make docs`.

---

## Lab 1 — See virtual vs. resident (demand paging)

**Goal:** prove RSS grows on *touch*, not on allocation (Ch 6.1).

```bash
python3 - <<'PY'
import os, resource, time
def rss(): return int(next(l.split()[1] for l in open('/proc/self/status') if l.startswith('VmRSS')))//1024
print("baseline RSS", rss(), "MB")
buf = bytearray(500*1024*1024)      # allocate 500MB (mostly reserved)
print("after alloc  ", rss(), "MB")
for i in range(0, len(buf), 4096):  # touch every page
    buf[i] = 1
print("after touch  ", rss(), "MB")
PY
```
**Expected:**
```
baseline RSS 12 MB
after alloc  ~14–500 MB     (bytearray zero-fills, so may fault immediately)
after touch  ~512 MB
```
**Proves:** RSS tracks touched pages. (Try `mmap` with `MAP_NORESERVE` for a
clearer "alloc cheap, touch expensive" split.)

## Lab 2 — Measure RSS, PSS, USS on one process

**Goal:** see `RSS ≥ PSS ≥ USS` and shared-library over-counting (Ch 3).

```bash
python3 -c "import time; time.sleep(300)" &   # PID=$!
PID=$!
grep -E '^(Rss|Pss|Private_Clean|Private_Dirty|Shared_Clean):' /proc/$PID/smaps_rollup
smem -k -c "pid rss pss uss command" -P "sleep 300" 2>/dev/null || echo "install smem for PSS/USS"
kill $PID
```
**Expected:**
```
Rss:   11000 kB
Pss:    6500 kB     <-- lower: shared libc/python pages apportioned
Shared_Clean: 7000 kB
Private_Dirty: 2500 kB   (~USS)
```
**Proves:** RSS counts shared pages fully; PSS apportions; USS is private-only.
Start 4 copies and compare summed RSS vs summed PSS (double-counting, Ch 3.4).

## Lab 3 — Build a memory leak, then recognize its shape

**Goal:** produce the unbounded-climb shape and confirm it's retention (Ch 11.2).

```bash
python3 - <<'PY'
import time
def rss(): return int(next(l.split()[1] for l in open('/proc/self/status') if l.startswith('VmRSS')))//1024
CACHE = {}
for r in range(1, 9):
    for i in range(r*100000, r*100000+100000):
        CACHE[f"key-{i}"] = b"x"*200          # unbounded cache (Ch 11.4 #1)
    print(f"round {r}: RSS {rss()} MB, keys {len(CACHE):,}")
PY
```
**Expected:**
```
round 1: RSS 40 MB,  keys 100,000
round 2: RSS 65 MB,  keys 200,000
...
round 8: RSS 210 MB, keys 800,000     <-- monotonic, never plateaus
```
**Proves:** unbounded growth = leak/retention. This mirrors
`leak_via_global_cache` in [`../../workloads/memory_leak.py`](../../workloads/memory_leak.py).

## Lab 4 — Find the leaking line with tracemalloc

**Goal:** attribute Lab 3's growth to a source line (Ch 12.3, 17.3).

```bash
python3 docs/03_memory_profiling/03_tracemalloc_snapshot_diff.py
# or roll your own against workloads/memory_leak.py:
python3 - <<'PY'
import tracemalloc, sys; sys.path.insert(0, "workloads")
import memory_leak as m
tracemalloc.start()
s1 = tracemalloc.take_snapshot()
m.leak_via_global_cache(iterations=200000, start=0)
s2 = tracemalloc.take_snapshot()
for st in s2.compare_to(s1, "lineno")[:3]:
    print(st)
PY
```
**Expected:**
```
workloads/memory_leak.py:44: size=40.2 MiB (+40.2 MiB), count=200000 (+200000)
```
**Proves:** tracemalloc's snapshot-diff points straight at the allocating line.

## Lab 5 — Fix the leak, verify the shape changed

**Goal:** turn the climb into a plateau (Ch 11.9, 15.5).

```bash
python3 - <<'PY'
from cachetools import LRUCache      # pip install cachetools
def rss(): return int(next(l.split()[1] for l in open('/proc/self/status') if l.startswith('VmRSS')))//1024
CACHE = LRUCache(maxsize=100000)     # BOUNDED now
for r in range(1, 9):
    for i in range(r*100000, r*100000+100000):
        CACHE[f"key-{i}"] = b"x"*200
    print(f"round {r}: RSS {rss()} MB, keys {len(CACHE):,}")
PY
```
**Expected:**
```
round 1: RSS 40 MB, keys 100,000
round 4: RSS 55 MB, keys 100,000    <-- keys capped, RSS plateaus
round 8: RSS 58 MB, keys 100,000
```
**Proves:** bounding the cache flips the shape from climb to plateau — the fix is
validated by the graph, not a guess.

## Lab 6 — Why `del` + `gc.collect()` doesn't lower RSS

**Goal:** observe allocator retention (Ch 4.9).

```bash
python3 - <<'PY'
import gc
def rss(): return int(next(l.split()[1] for l in open('/proc/self/status') if l.startswith('VmRSS')))//1024
print("start   ", rss(), "MB")
big = [bytes(100) for _ in range(2_000_000)]   # many small objects
print("allocated", rss(), "MB")
del big; gc.collect()
print("after del", rss(), "MB")                 # often still high!
PY
```
**Expected:**
```
start    13 MB
allocated 300 MB
after del 120 MB     <-- NOT back to 13; arenas retained (Ch 4.9)
```
**Proves:** freeing returns memory to pymalloc, not the OS; fragmentation/retention,
not a leak. Repeat with one big `bytearray(200*1024*1024)` and see RSS *does* drop
(mmap-backed, Ch 5.3).

## Lab 7 — Profile NumPy: views, copies, and native invisibility

**Goal:** see native buffers, hidden copies, and tracemalloc's blindness (Ch 5.2–5.3).

```bash
python3 - <<'PY'
import numpy as np, sys, tracemalloc
def rss(): return int(next(l.split()[1] for l in open('/proc/self/status') if l.startswith('VmRSS')))//1024
tracemalloc.start()
a = np.ones(20_000_000, dtype=np.float64)    # 160 MB native
print("getsizeof(a):", sys.getsizeof(a), "  a.nbytes:", a.nbytes, "  RSS:", rss())
v = a[::2]; print("view shares mem:", np.shares_memory(a, v))
c = a.astype(np.float32); print("after copy RSS:", rss())      # +80MB
cur, _ = tracemalloc.get_traced_memory()
print("tracemalloc sees:", cur//1024//1024, "MB (should be tiny!)")
PY
```
**Expected:**
```
getsizeof(a): 112   a.nbytes: 160000000   RSS: 190
view shares mem: True
after copy RSS: 270
tracemalloc sees: 0 MB (should be tiny!)
```
**Proves:** the data is native (`nbytes`, RSS see it; `getsizeof`/`tracemalloc`
don't); slicing is a view, `astype` copies.

## Lab 8 — Profile native memory with memray

**Goal:** attribute native allocations to stacks (Ch 12.3).

```bash
pip install memray
memray run -o /tmp/lab8.bin docs/03_memory_profiling/01_sys_getsizeof.py
memray tree /tmp/lab8.bin | head -20
memray flamegraph /tmp/lab8.bin && echo "open memray-flamegraph-lab8.html"
```
**Expected:** a tree/flamegraph attributing bytes to allocation call stacks
(including native frames with `--native`).
**Proves:** memray sees what tracemalloc can't — the phantom-OOM tool (Ch 5.11).
Try it against a NumPy script and find the `astype` copy from Lab 7.

## Lab 9 — Reproduce fragmentation and fix with jemalloc

**Goal:** see rising-floor RSS and a code-free fix (Ch 5.9, 11.7, 15.13).

```bash
cat > /tmp/frag.py <<'PY'
def rss(): return int(next(l.split()[1] for l in open('/proc/self/status') if l.startswith('VmRSS')))//1024
keep=[]
for r in range(6):
    junk=[bytearray(500) for _ in range(500000)]   # varied churn
    keep.append(junk[0])                             # one survivor per round pins arenas
    del junk
    print("round", r, "RSS", rss(), "MB")
PY
echo "=== glibc default ==="; python3 /tmp/frag.py
echo "=== MALLOC_ARENA_MAX=1 ==="; MALLOC_ARENA_MAX=1 python3 /tmp/frag.py
# If jemalloc installed:
echo "=== jemalloc ==="; LD_PRELOAD=$(find / -name 'libjemalloc.so.2' 2>/dev/null|head -1) python3 /tmp/frag.py
```
**Expected:** default shows a creeping floor; `MALLOC_ARENA_MAX=1` and jemalloc
show lower/flatter RSS.
**Proves:** fragmentation is allocator behavior; capping arenas / swapping
allocator reduces it without code changes.

## Lab 10 — Debug a Docker container OOM (exit 137)

**Goal:** hit a cgroup limit and read the evidence (Ch 7, 8.4).

```bash
docker run --rm -m 256m --memory-swap 256m python:3.14-slim python3 - <<'PY'
def rss(): return int(next(l.split()[1] for l in open('/proc/self/status') if l.startswith('VmRSS')))//1024
buf=[]
try:
    while True:
        buf.append(bytearray(10*1024*1024))   # +10MB until killed
        print("RSS", rss(), "MB", flush=True)
except MemoryError:
    print("MemoryError")
PY
echo "container exit code: $?"     # 137 if OOMKilled
```
**Expected:**
```
RSS 40 MB ... RSS 250 MB
container exit code: 137
```
**Proves:** exceeding the cgroup limit → kernel OOM kill → 137. Inspect inside a
longer-lived container: `cat /sys/fs/cgroup/memory.max` (256Mi) and
`memory.events` (`oom_kill` count).

## Lab 11 — Classify memory kind via `memory.stat`

**Goal:** watch different `memory.stat` counters light up (Ch 10.5, 13.3).

```bash
docker run --rm -m 512m python:3.14-slim sh -c '
read_stat(){ grep -E "^(anon|file|shmem) " /sys/fs/cgroup/memory.stat; }
echo "--- baseline ---"; read_stat
python3 -c "x=bytearray(200*1024*1024); import time; open(\"/tmp/stat_after_anon\",\"w\")" 2>/dev/null
python3 - <<PY
import time
x = bytearray(200*1024*1024)          # anon
open("/dev/shm/blob","wb").write(b"y"*(150*1024*1024))  # shmem
open("/tmp/file","wb").write(b"z"*(150*1024*1024))       # file cache
import subprocess; subprocess.run(["grep","-E","^(anon|file|shmem) ","/sys/fs/cgroup/memory.stat"])
PY'
```
**Expected:** `anon` up ~200M, `shmem` up ~150M, `file` up ~150M.
**Proves:** each activity moves a *different* counter — the fork that routes Ch 13
diagnosis. `anon`=data, `shmem`=/dev/shm, `file`=page cache.

## Lab 12 — Exhaust `/dev/shm` (the DataLoader Bus error)

**Goal:** reproduce shm exhaustion and fix it (Ch 9.6).

```bash
# Default 64MB /dev/shm -> writing 100MB fails:
docker run --rm python:3.14-slim sh -c 'df -h /dev/shm; dd if=/dev/zero of=/dev/shm/big bs=1M count=100'
# Fix: enlarge /dev/shm
docker run --rm --shm-size=256m python:3.14-slim sh -c 'df -h /dev/shm; dd if=/dev/zero of=/dev/shm/big bs=1M count=100 && echo OK'
```
**Expected:**
```
(default) /dev/shm 64M ... dd: error writing '/dev/shm/big': No space left on device
(--shm-size=256m) /dev/shm 256M ... OK
```
**Proves:** `/dev/shm` is a size-capped tmpfs; the 64 MB default is what kills
PyTorch DataLoaders (`Bus error`). Fix = enlarge it (Ch 8.8 for k8s).

## Lab 13 — Shared memory lifecycle & leak

**Goal:** see `close()` vs `unlink()` and a leak (Ch 9.5, 9.7).

```bash
python3 - <<'PY'
from multiprocessing import shared_memory
import subprocess
shm = shared_memory.SharedMemory(create=True, size=100*1024*1024)   # 100MB
print("created:", shm.name)
subprocess.run(["sh","-c","ls -la /dev/shm | grep "+shm.name+" ; du -sh /dev/shm"])
shm.close()                      # detach only
subprocess.run(["sh","-c","ls /dev/shm | grep "+shm.name+" && echo 'STILL THERE after close()'"])
shm.unlink()                     # now freed
subprocess.run(["sh","-c","ls /dev/shm | grep "+shm.name+" || echo 'gone after unlink()'"])
PY
```
**Expected:**
```
created: psm_xxxx
... /dev/shm  100M
STILL THERE after close()
gone after unlink()
```
**Proves:** `close()` doesn't free RAM; only `unlink()` does. Skip `unlink()` and
you get a `resource_tracker` leak warning + a stale `/dev/shm` file.

## Lab 14 — Profile multiprocessing COW sharing

**Goal:** see fork sharing and CPython COW erosion (Ch 6.8, 14.9).

```bash
python3 - <<'PY'
import os, multiprocessing as mp
BIG = {i: str(i) for i in range(2_000_000)}     # ~150MB python dict
def rss(pid='self'): return int(next(l.split()[1] for l in open(f'/proc/{pid}/status') if l.startswith('VmRSS')))//1024
def child():
    s=0
    for k in BIG: s+=len(BIG[k])                # READING bumps refcounts -> COW
    print("child RSS", rss(), "MB (grew via COW on read)")
print("parent RSS", rss(), "MB")
p=mp.Process(target=child); p.start(); p.join()
PY
```
**Expected:**
```
parent RSS 165 MB
child RSS ~120 MB (grew via COW on read)     <-- pages privatized by refcount writes
```
**Proves:** "fork shares memory" erodes because CPython writes refcounts on read.
Fix: store `BIG` as a NumPy array (no per-object refcounts) and the child stays
near-zero private (Ch 14.9).

## Lab 15 — Analyze `/proc` for a real process

**Goal:** classify every mapping and read the metrics (Ch 2.11, 16.11).

```bash
python3 -c "import numpy as np; a=np.ones(50_000_000); input()" &   # holds 400MB
PID=$!
grep -E 'VmRSS|VmSize|VmData|Threads' /proc/$PID/status
echo "--- biggest mappings ---"; pmap -x $PID | sort -k3 -n | tail -5
echo "--- rollup ---"; grep -E '^(Rss|Pss|Anonymous):' /proc/$PID/smaps_rollup
kill $PID
```
**Expected:** a large `rw-p` anonymous mapping (~400MB, the NumPy buffer),
`VmRSS` ~450MB, `Anonymous` dominating the rollup.
**Proves:** you can locate the native buffer as an anonymous region and read
RSS/PSS/anon straight from `/proc`.

## Lab 16 — Full k8s OOM workflow (if you have a cluster/kind)

**Goal:** run the Ch 13 workflow end to end.

```bash
kubectl create deployment leaky --image=python:3.14-slim -- \
  python3 -c "import time;b=[];[ (b.append(bytearray(10*1024*1024)), time.sleep(2)) for _ in range(1000)]"
kubectl set resources deployment/leaky --limits=memory=128Mi
# Then follow Ch 13:
kubectl describe pod -l app=leaky | grep -A6 'Last State'      # OOMKilled / 137
kubectl exec deploy/leaky -- grep -E '^(anon|shmem|file) ' /sys/fs/cgroup/memory.stat
kubectl get events --field-selector reason=OOMKilling | tail
kubectl delete deployment leaky
```
**Expected:** `Reason: OOMKilled`, `Exit Code: 137`, `anon` dominating,
OOMKilling events.
**Proves:** the whole workflow (Ch 13/18) on a real (or `kind`) cluster.

---

## Lab index

| Lab | Concept | Chapter |
|---|---|---|
| 1 | demand paging (touch vs alloc) | 6.1 |
| 2 | RSS/PSS/USS | 3 |
| 3 | leak shape | 11.2 |
| 4 | tracemalloc line | 12.3 |
| 5 | fix + verify shape | 11.9, 15.5 |
| 6 | del/gc don't lower RSS | 4.9 |
| 7 | NumPy views/copies/native | 5.2–5.3 |
| 8 | memray native profiling | 12.3 |
| 9 | fragmentation + jemalloc | 5.9, 15.13 |
| 10 | Docker OOM 137 | 7, 8.4 |
| 11 | memory.stat classify | 10.5, 13.3 |
| 12 | /dev/shm exhaustion | 9.6 |
| 13 | shm close vs unlink | 9.5 |
| 14 | multiprocessing COW | 6.8, 14.9 |
| 15 | /proc analysis | 2.11 |
| 16 | k8s OOM workflow | 13, 18 |

---

## Key takeaways

- **Every concept in this book is reproducible in ~20 lines** — run the labs and
  the abstractions become muscle memory.
- **The highest-value labs to internalize:** RSS-doesn't-drop (6), NumPy native
  invisibility (7), leak shape → fix → verify (3→4→5), and `memory.stat`
  classification (11) — they underpin real incident debugging.
- **Always validate a fix by the shape**, not a single reading (Lab 5) — the
  discipline that separates "fixed" from "masked."
- **The `/proc` and `memory.stat` labs (11, 15)** give you the container-truth
  skills that `kubectl top` alone can't.

## Practice exercises

1. Run all 16 labs; for each, write one sentence on whether the output matched the
   prediction and why any differed.
2. Modify Lab 3/5 to sweep cache `maxsize` and plot RSS plateau height vs. size.
3. Combine Labs 7 + 8: profile the NumPy `astype` copy with memray and find the
   exact allocation stack.
4. Extend Lab 14 to store `BIG` as a NumPy array and show the child's private RSS
   stays near zero.

## Quiz questions

1. In Lab 1, why might `bytearray` show RSS jump at allocation while a raw `mmap`
   wouldn't?
2. In Lab 6, why does a single big `bytearray` free return RSS but two million
   small objects don't?
3. In Lab 7, which two measurements see the NumPy data and which two don't?
4. In Lab 11, what does each of `anon`/`shmem`/`file` growing tell your Ch 13
   diagnosis?
5. In Lab 13, what exactly does `unlink()` do that `close()` doesn't?
6. In Lab 14, why does merely *reading* a forked dict grow the child's RSS?

## Suggested experiments

- Build a single script that runs Labs 1–7 and prints a pass/fail vs. expected
  directions — your personal memory-behavior test suite.
- Wire Lab 16 into `kind` (kubernetes-in-docker) and practice the Ch 13 workflow
  until it's reflexive.
- Turn Lab 9 into a benchmark comparing glibc / `ARENA_MAX` / jemalloc / tcmalloc
  steady-state RSS on your workload.

---

*Next up: **Chapter 21 — Best Practices**: production do's and don'ts,
anti-patterns, monitoring/alerting, capacity planning, container sizing, memory
budgeting, and GC tuning — the operational wisdom that keeps memory incidents
from happening.*

[← Chapter 19](19_interview_questions.md) · [Back to index](README.md) · [Chapter 21 →](21_best_practices.md)
