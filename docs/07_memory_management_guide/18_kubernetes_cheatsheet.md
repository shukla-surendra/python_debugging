<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 18 — Kubernetes Cheat Sheet

The `kubectl`-and-cgroup companion to Chapters 8, 13, and 16. Everything you type
to inspect a running pod's memory — from the cluster view down to the cgroup
files inside the container. Chapter 13 is the *workflow*; this is the *command
reference*.

> `$POD` = pod name, `$NS` = namespace (`-n $NS` if not default), `$C` =
> container name (for multi-container pods use `-c $C`). This extends the repo's
> [`../05_production_playbook/04_kubernetes_debugging.md`](../05_production_playbook/04_kubernetes_debugging.md).

## 18.1 The pod-memory triage sequence

```bash
kubectl top pod $POD --containers                         # working set (Ch 3.14), NOT RSS
kubectl describe pod $POD | grep -A6 'Last State'         # OOMKilled? exit 137?
kubectl get pod $POD -o jsonpath='{.status.qosClass}'; echo    # QoS (Ch 8.3)
kubectl exec $POD -- sh -c 'cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.max'
kubectl exec $POD -- grep -E '^(anon|file|shmem|slab) ' /sys/fs/cgroup/memory.stat  # the fork (Ch 13 S3)
```

## 18.2 `kubectl top` — live usage (working set, not RSS)

```bash
kubectl top pod                          # all pods in namespace
kubectl top pod $POD --containers        # per-container breakdown
kubectl top pod -A --sort-by=memory      # cluster-wide, biggest first
kubectl top node                         # node CPU/MEM utilization & headroom
kubectl top pod -l app=inference         # by label selector
```
- **Shows `container_memory_working_set_bytes`** = `memory.current − inactive_file`
  (Ch 3.14) — **not** RSS, **not** VSZ. Will differ from `top` inside the pod;
  both are correct, measuring different things. Needs `metrics-server`.

## 18.3 `kubectl describe` — limits, QoS, OOM reason, events

```bash
kubectl describe pod $POD
# Look for:
#   Containers: ... Limits/Requests: memory      -> your caps (Ch 8.2)
#   Last State: Terminated  Reason: OOMKilled  Exit Code: 137   (Ch 8.4)
#   QoS Class: Guaranteed | Burstable | BestEffort              (Ch 8.3)
#   Events: ... OOMKilling / FailedScheduling / Evicted
kubectl describe pod $POD | grep -A6 'Last State'          # just the crash info
kubectl describe node $(kubectl get pod $POD -o jsonpath='{.spec.nodeName}') \
  | grep -A5 Conditions                                    # MemoryPressure? (Ch 8.5)
```

## 18.4 Pod status via jsonpath (scriptable)

```bash
# The limit and the crash details, no grep:
kubectl get pod $POD -o jsonpath='{.spec.containers[0].resources.limits.memory}'; echo
kubectl get pod $POD -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}'; echo    # OOMKilled
kubectl get pod $POD -o jsonpath='{.status.containerStatuses[0].lastState.terminated.exitCode}'; echo  # 137
kubectl get pod $POD -o jsonpath='{.status.containerStatuses[0].restartCount}'; echo
kubectl get pod $POD -o jsonpath='{.status.qosClass}'; echo
```

## 18.5 `kubectl get events` — OOM & eviction history

```bash
kubectl get events --field-selector reason=OOMKilling --sort-by=.lastTimestamp
kubectl get events --field-selector reason=Evicted --sort-by=.lastTimestamp   # node pressure (Ch 8.5)
kubectl get events --field-selector involvedObject.name=$POD --sort-by=.lastTimestamp
kubectl get events -A --field-selector reason=Evicted | tail        # cluster-wide evictions
```
- **OOMKilling** = your container hit its own limit (cgroup). **Evicted** = node
  pressure, kubelet reclaimed you (Ch 8.5). *Different problems, different fixes.*

## 18.6 `kubectl exec` — cgroup ground truth inside the pod

```bash
# One-shot memory snapshot inside the container (Ch 7.6/16.17):
kubectl exec $POD -- sh -c '
  echo "limit : $(cat /sys/fs/cgroup/memory.max)"
  echo "usage : $(cat /sys/fs/cgroup/memory.current)"
  echo "--- memory.stat ---"
  grep -E "^(anon|file|shmem|slab|kernel_stack|sock|inactive_file|active_file) " /sys/fs/cgroup/memory.stat
  echo "--- memory.events ---"; cat /sys/fs/cgroup/memory.events'
# oom_kill count and whether you keep hitting the ceiling ("max" counter)

# Interactive shell:
kubectl exec -it $POD -- sh          # or bash; then run Ch 16 tools if present

# Per-process breakdown of PID 1 (the app) (Ch 3.16):
kubectl exec $POD -- grep -E 'VmRSS|VmSwap|Threads' /proc/1/status
kubectl exec $POD -- grep -E '^(Rss|Pss|Anonymous|Swap):' /proc/1/smaps_rollup
kubectl exec $POD -- sh -c 'ls /proc/1/fd | wc -l'      # fd count (Ch 13 S5e)
kubectl exec $POD -- sh -c 'du -sh /dev/shm; ls -la /dev/shm'   # shm (Ch 9)
```

## 18.7 The cgroup v2 files you'll read (from inside)

| File | Meaning | Chapter |
|---|---|---|
| `memory.max` | hard limit (= `limits.memory`); `max` = unlimited | 7.4, 8.2 |
| `memory.current` | current charged usage (anon + cache + kernel) | 7.6 |
| `memory.stat` | **breakdown**: `anon`, `file`, `shmem`, `slab`, `sock`, `inactive_file` | 10.5, 13.3 |
| `memory.events` | counters: `oom`, `oom_kill`, `high`, `max` | 8.4 |
| `memory.high` | soft throttle limit (reclaim pressure, no kill) | 7.3 |
| `memory.swap.max` | swap limit (usually 0 in k8s) | 3.7, 8 |
| `memory.min`/`memory.low` | reclaim protection | 7.3 |

```bash
# Working set (what k8s compares to the limit) computed by hand:
kubectl exec $POD -- sh -c 'echo $(( $(cat /sys/fs/cgroup/memory.current) - $(awk "/inactive_file/{print \$2}" /sys/fs/cgroup/memory.stat) ))'
# v1 fallback paths:
#   /sys/fs/cgroup/memory/memory.limit_in_bytes , memory.usage_in_bytes , memory.stat
```

## 18.8 `kubectl logs` — correlate memory with app behavior

```bash
kubectl logs $POD --previous              # logs from the CRASHED (OOMKilled) container
kubectl logs $POD -c $C --since=1h        # a specific container, recent window
kubectl logs $POD -f --tail=100           # follow live while watching memory climb
kubectl logs $POD --previous | tail -50   # what was it doing right before the OOM?
```
- **`--previous` is the key flag** for OOM debugging: it shows the *dead*
  container's logs (the one that got 137'd), not the fresh restart.

## 18.9 `kubectl debug` — tools without rebuilding the image

When the app image is `distroless`/`slim` and lacks profilers (Ch 12), attach an
**ephemeral debug container** that shares the target's process namespace:

```bash
# Share the target container's PID namespace so you can see/profile PID 1:
kubectl debug -it $POD --image=python:3.14-slim --target=$C -- bash
#   inside: pip install memray py-spy ; py-spy dump --pid 1 ; read /proc/1/... 

# A throwaway node-level debugger (host view):
kubectl debug node/$(kubectl get pod $POD -o jsonpath='{.spec.nodeName}') -it --image=busybox
# Copy a running pod with an added debug container (non-disruptive):
kubectl debug $POD -it --copy-to=$POD-dbg --image=python:3.14-slim --share-processes -- bash
```
- **`--target`/`--share-processes`** is what lets `py-spy`/`memray` and
  `/proc/1/*` reach the real app process (Ch 13 S5a).

## 18.10 `kubectl edit` / `patch` / `set` — adjust limits (stopgap & fix)

```bash
# Bump the memory limit (stopgap headroom while you find root cause, Ch 13.8):
kubectl set resources deployment/inference --limits=memory=3Gi --requests=memory=2Gi
kubectl patch deployment inference --type=json -p \
  '[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"3Gi"}]'
kubectl rollout status deployment/inference        # watch the new pods come up
kubectl rollout restart deployment/inference       # force fresh pods (clear leaked state)
```
- Editing resources triggers a rollout (new pods). Use as a **logged stopgap**;
  pair with the real fix (Ch 13.7, 15).

## 18.11 Node & scheduling view

```bash
kubectl top node                                          # node headroom
kubectl describe node $NODE | grep -A8 'Allocated resources'   # requests vs allocatable
kubectl get pods -A -o wide --field-selector spec.nodeName=$NODE   # who's on the node
kubectl describe node $NODE | grep -A5 Conditions         # MemoryPressure/DiskPressure
kubectl get pods -A --field-selector status.phase=Failed  # evicted/failed pods
```

## 18.12 Full copy-paste OOM triage block

```bash
POD=inference-7d9f; NS=default
kubectl -n $NS describe pod $POD | grep -A6 'Last State'                   # S1 confirm OOM/137
kubectl -n $NS top pod $POD --containers                                   # S2 working set
kubectl -n $NS get pod $POD -o jsonpath='{.spec.containers[0].resources.limits.memory}{"\n"}'
kubectl -n $NS exec $POD -- sh -c 'cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.max; cat /sys/fs/cgroup/memory.events'
kubectl -n $NS exec $POD -- grep -E '^(anon|file|shmem|slab) ' /sys/fs/cgroup/memory.stat   # S3 classify
kubectl -n $NS logs $POD --previous | tail -50                             # what it was doing
kubectl -n $NS get events --field-selector reason=Evicted | tail          # S6 node pressure?
kubectl -n $NS describe node $(kubectl -n $NS get pod $POD -o jsonpath='{.spec.nodeName}') | grep -A5 Conditions
# then localize (Ch 13 S5): kubectl debug ... --target -> py-spy/memray/tracemalloc
```

## 18.13 Command → question quick index

| Question | Command |
|---|---|
| How much memory now? | `kubectl top pod $POD --containers` (working set) |
| Was it OOMKilled? | `describe ... 'Last State'` → Reason/Exit 137 |
| What's my limit? | `get pod -o jsonpath=...limits.memory` or `exec cat memory.max` |
| Python/native/shm/kernel? | `exec grep '^(anon\|file\|shmem\|slab)' memory.stat` |
| How many OOM kills? | `exec cat memory.events` → `oom_kill` |
| My QoS class? | `get pod -o jsonpath='{.status.qosClass}'` |
| OOM vs eviction? | `get events` reason `OOMKilling` vs `Evicted` |
| Logs before the crash | `logs $POD --previous` |
| Profile a slim image | `kubectl debug --target=$C ... py-spy/memray` |
| Node out of memory? | `describe node ... Conditions` → MemoryPressure |
| Stopgap headroom | `kubectl set resources ... --limits=memory=...` |

---

## Key takeaways

- **`kubectl top` = working set, not RSS** (Ch 3.14) — expect it to differ from
  `top` inside the pod; both are right.
- **`describe` + jsonpath** give the limit, QoS, `OOMKilled`, and exit **137**;
  **`get events`** distinguishes **OOMKilling** (your limit) from **Evicted**
  (node pressure) — different fixes.
- **`kubectl exec` into the cgroup files is ground truth**: `memory.max`,
  `memory.current`, and especially **`memory.stat`** (`anon`/`shmem`/`file`/`slab`)
  — the fork that routes your whole diagnosis (Ch 13.3).
- **`kubectl logs --previous`** shows the dead container's logs; **`kubectl debug
  --target`** attaches profilers to slim images without a rebuild.
- **`kubectl set resources`/`rollout restart`** are legitimate *logged stopgaps*
  (headroom / clear leaked state) — pair with the shape-verified fix (Ch 13.7).

## Practice exercises

1. On a test pod, run the §18.1 triage sequence and the §18.12 block; capture and
   interpret each output.
2. Deliberately OOM a pod (`limits.memory: 256Mi` + growing allocation); use
   `describe`, `get events`, `logs --previous`, and `memory.events` to prove it
   was a cgroup OOM (137), not an eviction.
3. Attach `kubectl debug --target` to a slim image and run `py-spy dump --pid 1`
   plus read `/proc/1/smaps_rollup`.
4. Compute working set by hand from `memory.current − inactive_file` and compare
   to `kubectl top`.

## Quiz questions

1. `kubectl top` shows 1.6Gi, `top` inside shows 2.1Gi RES. Which is which and why
   differ?
2. Which single `exec`'d file+field tells you whether growth is Python/native,
   shared memory, cache, or kernel?
3. How do you get the logs of the container that just got OOMKilled, not the
   restart?
4. Your image has no profilers. How do you run `py-spy`/`memray` against PID 1?
5. `get events` shows `Evicted`, not `OOMKilling`. What happened and how does the
   fix differ?
6. Which files hold the limit, the current usage, the breakdown, and the OOM
   count?

## Suggested experiments

- Save the §18.12 block as `k8s-mem-triage.sh $POD` and run it against a leaky
  test deployment; practice reading each line.
- Compare `kubectl top pod` vs. `exec ... cat memory.current` vs. the hand-computed
  working set over a minute; reconcile the three.
- Use `kubectl debug --copy-to ... --share-processes` to profile a production-like
  pod non-disruptively, then follow Ch 13 S5 to localize a planted leak.

---

*Next up: **Chapter 19 — 100+ Interview Questions**, graded beginner →
intermediate → advanced → staff, each with a worked answer that ties back to the
mechanisms in this book.*

[← Chapter 17](17_python_cheatsheet.md) · [Back to index](README.md) · [Chapter 19 →](19_interview_questions.md)
