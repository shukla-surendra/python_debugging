<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 13 — Kubernetes Memory Debugging Workflow

This is the chapter you'll actually open at 3 a.m. Everything so far was
foundation; here we run a **single, repeatable workflow** on a real incident:

> **Symptom:** the `inference` pod's memory keeps climbing and it gets
> `OOMKilled` roughly every 40 minutes, entering `CrashLoopBackOff`.

We go step by step — each step has the **command**, **realistic output**, and
**what it tells you / where it points** — until we reach root cause and a
verified fix. The workflow is a decision tree, not a script: each step routes you
to the next based on what you see.

> Prerequisites: Ch 3 (working set), Ch 7–9 (cgroups, `/dev/shm`), Ch 10 (master
> table), Ch 11 (patterns), Ch 12 (tools). This extends the repo's
> [`../05_production_playbook/04_kubernetes_debugging.md`](../05_production_playbook/04_kubernetes_debugging.md).

## 13.0 The workflow at a glance

```
   Pod memory rising / OOMKilled
        |
   S1  Confirm it IS memory (not liveness/CPU/disk)      -> kubectl describe/events
   S2  Quantify: limit vs usage, is it working set?      -> kubectl top, memory.max/current
   S3  Classify the KIND of memory (the fork in the road) -> memory.stat: anon/shmem/file/slab
   S4  Leak vs retention vs spike (the SHAPE)             -> history / Grafana / repeated top
   S5  Localize:
         anon+Python  -> tracemalloc/objgraph
         anon+native  -> memray
         shmem        -> /dev/shm, ipcs
         slab/kernel  -> lsof, fd/socket count
   S6  Rule out NODE pressure (is it even you?)           -> describe node, Evicted events
   S7  Fix + verify the graph shape changed               -> Ch 11.9 / Ch 15
```

## 13.1 Step 1 — Confirm it's actually a memory OOM

Don't assume. A `CrashLoopBackOff` can be a failing liveness probe, a CPU-starved
startup, or disk pressure. Confirm the cause is memory and exit 137.

```bash
kubectl get pod inference-7d9f -o wide
# NAME              READY   STATUS             RESTARTS   AGE
# inference-7d9f    0/1     CrashLoopBackOff   14         9h

kubectl describe pod inference-7d9f | grep -A6 'Last State'
#   Last State:     Terminated
#     Reason:       OOMKilled          <-- memory, confirmed
#     Exit Code:    137                <-- 128 + SIGKILL(9)  (Ch 3.14, 6.11, 8.4)
#     Started:      ...  Finished: ... (~40 min apart)

kubectl get events --field-selector reason=OOMKilling --sort-by=.lastTimestamp | tail
# ... Killing container inference (memory limit) ...
```

**Reads:** `Reason: OOMKilled` + `Exit Code: 137` ⇒ it's a **cgroup OOM kill**
(the container exceeded **its own** `memory.max`), not a node eviction (that would
say `Evicted`, Ch 8.5 — we still confirm in S6). Proceed.

> If instead you saw `Reason: Error` + a liveness-probe event, or `Evicted`, this
> is a different problem — stop and branch (liveness tuning; or S6 node pressure).

## 13.2 Step 2 — Quantify: limit vs. usage, and which metric

```bash
# The limit (from the spec) and live working set (metrics-server):
kubectl get pod inference-7d9f -o jsonpath='{.spec.containers[0].resources.limits.memory}'; echo
# 2Gi

kubectl top pod inference-7d9f --containers
# POD             NAME        CPU   MEMORY
# inference-7d9f   inference   1850m  1987Mi     <-- working set right at the 2Gi limit
```

Then the **cgroup ground truth** inside the pod (Ch 7.6/8.6):

```bash
kubectl exec inference-7d9f -- sh -c '
  echo max=$(cat /sys/fs/cgroup/memory.max)
  echo current=$(cat /sys/fs/cgroup/memory.current)
  cat /sys/fs/cgroup/memory.events'
# max=2147483648
# current=2103808000            (~1.96Gi, riding the limit)
# low 0
# high 0
# max 3184                       <-- hit the limit 3184 times
# oom 12
# oom_kill 12                    <-- 12 cgroup OOM kills (matches ~restarts)
```

**Reads:** working set (not RSS/VSZ — Ch 3.14) is pinned at the 2Gi limit;
`memory.events oom_kill=12` confirms repeated cgroup kills. Now the key question:
**what kind of memory is it?**

## 13.3 Step 3 — Classify the kind of memory (the fork in the road)

This single command decides your entire investigation path (Ch 10.5).

```bash
kubectl exec inference-7d9f -- sh -c 'grep -E "^(anon|file|shmem|slab|kernel_stack|sock|inactive_file|active_file) " /sys/fs/cgroup/memory.stat'
# anon 1904214016        <-- ~1.77Gi  DOMINATES  -> your data (Python or native)
# file 121634816         <-- ~116Mi   page cache (reclaimable, not the killer)
# shmem 8388608          <-- 8Mi      /dev/shm small -> NOT a shm problem
# slab 41943040          <-- 40Mi     kernel objects modest -> NOT fd/socket
# kernel_stack 3145728
# inactive_file 100663296
# active_file 20971520
```

**Reads:** `anon` dominates (~1.77 GiB). Per Ch 10.3 the OOM driver is
**anonymous memory** = Python objects **or** native buffers. `shmem` and `slab`
are small, so this is **not** `/dev/shm` (Ch 9) and **not** an fd/socket
explosion (Ch 3.13). Next: is `anon` a leak, and Python or native?

```
   memory.stat says:
     anon  large  ---------> go to S4 (shape) then S5-Python/native
     shmem large  ---------> jump to S5-shmem (/dev/shm, Ch 9)
     file  large  ---------> reclaimable cache; likely NOT your OOM cause
     slab  large  ---------> S5-kernel (lsof, fd/socket count)
```

## 13.4 Step 4 — Leak vs. retention vs. spike (the shape, Ch 11)

Look at memory **over time**, not a single reading. Use your dashboard
(Prometheus `container_memory_working_set_bytes`) or sample by hand.

```bash
# Poor man's history if you have no Grafana: sample working set every 30s
for i in $(seq 1 20); do
  printf '%s ' "$(date +%T)"
  kubectl exec inference-7d9f -- cat /sys/fs/cgroup/memory.current
  sleep 30
done
# 03:01:10 812339200
# 03:01:40 903872512
# 03:02:10 995420160    <-- steady linear climb, ~90MiB / 30s, tracks request rate
# ...      ...          <-- never plateaus -> LEAK or RETENTION (Ch 11.2/11.3)
```

**Reads:** monotonic linear climb that resets only on OOM restart ⇒ the
**unbounded leak/retention** shape (Ch 11.2), not allocator caching (which would
plateau) and not a transient spike. Now localize *which anon* — Python or native.

## 13.5 Step 5 — Localize the cause

### 5a. Is it Python objects or native buffers?

Get a shell in the running pod and check whether Python's own view of memory is
growing (Ch 5.2 / 12.3). If the image has the tools, use them; otherwise install
into the running container or use an ephemeral debug container.

```bash
# Attach a debug container that shares the target's process namespace (Ch 18):
kubectl debug -it inference-7d9f --image=python:3.14-slim --target=inference -- bash

# Inside: check Python-tracked object count vs. RSS over ~1 min
python3 - <<'PY'
import gc, os, time
def rss(): 
    return int(next(l.split()[1] for l in open(f"/proc/1/status") if l.startswith("VmRSS")))//1024
for _ in range(6):
    print("RSS_MB", rss(), "gc_objects", len(gc.get_objects()))
    time.sleep(10)
PY
# RSS_MB 1700 gc_objects 250114
# RSS_MB 1740 gc_objects 251003     <-- RSS climbs, Python object count ~flat-ish
# RSS_MB 1782 gc_objects 251540
```

- **If `gc_objects` grows with RSS** → **Python retention/leak** → 5b (tracemalloc
  + objgraph).
- **If RSS grows but `gc_objects` stays flat** → **native leak** (Ch 11.6) → 5c
  (memray). *This is the phantom-OOM branch.*

Here `gc_objects` is roughly flat while RSS climbs → **native buffers**. (If it
had grown, we'd take 5b.)

### 5b. Python objects — tracemalloc + objgraph (Ch 12.3)

If the app is instrumented (or you enable a debug flag), diff snapshots across a
work cycle:

```python
# Behind a runtime flag in the app (safe, short window):
import tracemalloc; tracemalloc.start(25)
snap1 = tracemalloc.take_snapshot()
# ... serve ~200 requests ...
snap2 = tracemalloc.take_snapshot()
for s in snap2.compare_to(snap1, 'lineno')[:5]:
    print(s)
# app/cache.py:44: size=612 MiB (+612 MiB), count=210344 (+210344)   <-- the leak
```

```python
import objgraph; objgraph.show_growth(limit=5)
# dict     +210344      <-- who is holding them?
objgraph.show_backrefs(objgraph.by_type('dict')[-1], max_depth=6, filename='/tmp/r.png')
# chain: module app.cache -> _RESPONSE_CACHE (dict) -> ...   <-- an UNBOUNDED CACHE
```

**Root cause (Python branch):** an unbounded module-level `_RESPONSE_CACHE`
(Ch 11.4 pattern #1). Fix: bound it (`lru_cache(maxsize=...)`/`TTLCache`).

### 5c. Native buffers — memray (Ch 12.3, the branch we're on)

Run the workload under memray (staging/canary or a short prod window):

```bash
memray run --native -o /tmp/out.bin -m myapp.serve &     # or wrap the entrypoint
# ...let it serve for a few minutes...
memray flamegraph /tmp/out.bin      # open the HTML: biggest allocation stacks
memray tree /tmp/out.bin | head -30
# 612.4 MiB  cv2.cvtColor                    <-- native OpenCV buffers accumulating
#   └─ 590.1 MiB  app/pipeline.py:88 preprocess()
#        └─ frames appended to self._debug_frames (list)   <-- RETAINED natively
```

**Root cause (native branch):** `preprocess()` appends every decoded frame's
`cv::Mat` to a long-lived `self._debug_frames` list — native buffers retained via
a reachable Python list (Ch 5.6, 11.6). `tracemalloc` missed it because the bytes
are native; `gc_objects` barely moved because it's *few* Python wrappers holding
*huge* buffers.

### 5d. Shared memory branch (if S3 showed large `shmem`)

```bash
kubectl exec inference-7d9f -- sh -c 'du -sh /dev/shm; ls -la /dev/shm; ipcs -m 2>/dev/null'
# 1.4G  /dev/shm
# -r-------- ... psm_torch_xxxx  (many stale DataLoader segments)   <- Ch 9 leak
```

Fix: mount a bounded memory `emptyDir` at `/dev/shm` (Ch 8.8), reduce
`num_workers`/`batch_size`, ensure `unlink()` on worker teardown (Ch 9.5/9.7).

### 5e. Kernel/slab branch (if S3 showed large `slab`)

```bash
kubectl exec inference-7d9f -- sh -c 'ls /proc/1/fd | wc -l; cat /sys/fs/cgroup/memory.stat | grep -E "slab|sock"'
# 48213                 <-- fd leak! (unclosed sockets/files) -> kernel memory (Ch 3.13)
```

Fix: close sockets/files/cursors (context managers), bound connection pools.

## 13.6 Step 6 — Rule out node pressure (is it even you?)

Even with a clean per-container diagnosis, confirm the node isn't the real story
(Ch 8.5) — especially if *multiple* pods misbehave.

```bash
kubectl describe node ip-10-0-3-11 | grep -A5 Conditions
#   MemoryPressure   False        <-- node is fine; this is OUR pod's own limit
kubectl get events --field-selector reason=Evicted --sort-by=.lastTimestamp | tail
#   (none)  -> no evictions; confirms cgroup OOM (S1), not node pressure
kubectl top nodes
# NAME            CPU   MEMORY   MEMORY%
# ip-10-0-3-11    62%   71%      ...       <-- headroom exists
```

**Reads:** `MemoryPressure=False`, no `Evicted` events, node has headroom ⇒ this
is **our container exceeding its own 2Gi limit**, exactly as S1 said. (If instead
`MemoryPressure=True` with `Evicted` events, the fix is node-level: raise
requests, add nodes, or right-size neighbors — Ch 8/21.)

## 13.7 Step 7 — Fix and verify the shape changed

The fix depends on the branch you landed on:

| Branch (from S5) | Root cause | Fix (Ch 15 has details) |
|---|---|---|
| 5b Python | unbounded cache/accumulator | bound cache (`lru_cache`/`TTLCache`), `weakref`, unregister callbacks |
| 5c Native | retained native buffers (frames/tensors/images) | drop the retaining ref; `close()`/`del`; don't accumulate `cv::Mat`/tensors |
| 5d shmem | `/dev/shm` too small / shm leak | bound memory `emptyDir`, fewer workers, `unlink()` |
| 5e kernel | fd/socket leak | close resources; pool limits |
| S6 node | node memory pressure | raise requests, add nodes, right-size neighbors |
| any (stopgap) | fragmentation/retention you can't fix now | **worker recycling** + raise limit for headroom |

For our native case, the fix is removing the `self._debug_frames` accumulation
(it was left-in debug code). Then **verify by shape** (Ch 11.9), not by a
5-minute smoke test:

```bash
# After deploy, watch working set across many request cycles:
for i in $(seq 1 30); do kubectl top pod inference-7d9f --no-headers; sleep 60; done
# ... MEMORY holds ~700-820Mi in a healthy sawtooth, never approaches 2Gi ...
kubectl exec inference-7d9f -- cat /sys/fs/cgroup/memory.events | grep oom_kill
# oom_kill 0     <-- no new kills. Fixed.
kubectl get pod inference-7d9f
# READY 1/1   STATUS Running   RESTARTS 0
```

**Reads:** the unbounded climb (S4) became a healthy sawtooth (Ch 11.2),
`oom_kill` stopped incrementing, restarts stopped. Root cause confirmed fixed —
not merely masked.

## 13.8 A note on stopgaps vs. root cause

While you hunt the root cause, it's legitimate to **stop the bleeding**: raise
the limit for headroom and/or enable **worker recycling**
(`--max-requests`, Ch 11.7/15) so the pod self-heals before OOM. But log a
follow-up — a raised limit hides a leak until it OOMs at the new ceiling. **A
stopgap buys time; the shape-verified fix (S7) ends the incident.**

## 13.9 The whole workflow as a copy-paste triage block

```bash
POD=inference-7d9f
# S1 confirm memory OOM
kubectl describe pod $POD | grep -A6 'Last State'
# S2 quantify
kubectl top pod $POD --containers
kubectl exec $POD -- sh -c 'echo max=$(cat /sys/fs/cgroup/memory.max) cur=$(cat /sys/fs/cgroup/memory.current); cat /sys/fs/cgroup/memory.events'
# S3 classify the kind of memory
kubectl exec $POD -- grep -E "^(anon|file|shmem|slab) " /sys/fs/cgroup/memory.stat
# S4 shape (sample over time)
for i in $(seq 1 20); do kubectl exec $POD -- cat /sys/fs/cgroup/memory.current; sleep 30; done
# S5 localize (pick by S3): tracemalloc/objgraph (python) | memray (native) | du /dev/shm+ipcs (shmem) | ls /proc/1/fd|wc -l (kernel)
# S6 rule out node pressure
kubectl describe node $(kubectl get pod $POD -o jsonpath='{.spec.nodeName}') | grep -A5 Conditions
kubectl get events --field-selector reason=Evicted | tail
# S7 fix (Ch 15) then verify shape + oom_kill stops incrementing
```

---

## Key takeaways

- **Follow the fixed 7-step workflow**, don't guess: confirm memory OOM →
  quantify vs. limit → **classify `memory.stat`** → **shape (leak/retention/
  spike)** → localize by branch → rule out node pressure → fix + **verify the
  shape changed**.
- **`memory.stat` is the fork in the road:** `anon` → Python/native; `shmem` →
  `/dev/shm` (Ch 9); `file` → reclaimable cache; `slab` → fd/socket leak.
- **`gc_objects`-vs-RSS splits Python from native**: both grow → Python
  (tracemalloc/objgraph); RSS grows but object count flat → **native** (memray,
  the phantom OOM).
- **Always rule out node pressure** (`MemoryPressure`, `Evicted`) — an OOMKill is
  *your* limit; an eviction is the *node's* problem, with different fixes.
- **Verify fixes by the graph shape and `oom_kill` count over a long run**, not a
  short smoke test; use worker recycling/limit bumps only as logged stopgaps.

## Practice exercises

1. Deploy a pod with `limits.memory: 512Mi` and an app with an unbounded cache;
   run the full 7-step workflow to root cause using only `kubectl` + cgroup
   files. Capture the output at each step.
2. Repeat with a **native** leak (accumulate NumPy arrays); show that S5a's
   `gc_objects`-vs-RSS split sends you to memray, not tracemalloc.
3. Reproduce a `/dev/shm` OOM (Ch 9) and show S3 routes you to the shmem branch,
   not the anon branch.
4. Cause a *node* MemoryPressure eviction and confirm S6 distinguishes it from a
   cgroup OOM.

## Quiz questions

1. A pod is `CrashLoopBackOff`. What two fields prove it's a memory OOM vs. a
   liveness failure?
2. Which single file/command tells you whether to hunt Python objects, native
   buffers, `/dev/shm`, or fds — and what value routes to each?
3. RSS climbs but `len(gc.get_objects())` is flat. Which branch, which tool, and
   why did tracemalloc miss it?
4. How do you distinguish a cgroup OOMKill from a node eviction, and why does the
   distinction change the fix?
5. Why must you verify a memory fix over a long run rather than a 5-minute test?
6. Your dashboard shows a plateau, not a climb, yet the pod OOMed once. Leak?
   What likely happened and what do you check?

## Suggested experiments

- Wire the §13.9 triage block into a script and run it against a deliberately
  leaky test deployment; practice reading each step's output.
- Instrument a service with a runtime `?debug=tracemalloc` flag that dumps the
  top-10 snapshot diff; confirm you can localize a Python leak in prod safely
  (Ch 12.5).
- Follow the repo playbook
  [`../05_production_playbook/04_kubernetes_debugging.md`](../05_production_playbook/04_kubernetes_debugging.md)
  alongside this workflow and note where they overlap and where this chapter goes
  deeper.

---

*Next up: **Chapter 14 — Case Studies from Production**: OCR/PDF/image pipelines,
ML inference, batch/streaming, async workers, multiprocessing, FastAPI, Celery,
and Kafka consumers — each showing exactly where the memory goes and how the Ch
13 workflow found it.*

[← Chapter 12](12_memory_profiling.md) · [Back to index](README.md) · [Chapter 14 →](14_case_studies.md)
