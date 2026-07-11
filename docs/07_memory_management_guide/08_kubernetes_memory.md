<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 8 — Kubernetes Memory

Kubernetes memory is **cgroups with YAML** (Chapter 7) plus a scheduler and an
eviction manager on top. Every OOMKill, every mysterious pod restart, every
"why did my healthy pod get evicted?" traces back to three numbers —
**requests**, **limits**, and the node's **available memory** — and how the
kubelet turns them into cgroup settings and `oom_score_adj` values.

This chapter makes those mechanics precise. It pairs with the repo's hands-on
[`../05_production_playbook/04_kubernetes_debugging.md`](../05_production_playbook/04_kubernetes_debugging.md),
which we extend into a full workflow in Chapter 13.

> Prerequisites: Ch 3 (working set, the metric k8s uses), Ch 6 (OOM killer,
> `oom_score_adj`), Ch 7 (cgroups v2, `memory.max`, what counts as container
> memory). Ch 9 covers shared memory volumes in depth.

## 8.1 The mental model: pod → container → cgroup

```
   NODE (a Linux machine with, say, 32 GiB RAM)
   +-----------------------------------------------------------------+
   |  kubelet + container runtime (containerd/CRI-O)                  |
   |                                                                 |
   |  POD A                          POD B                           |
   |  +---------------------------+  +---------------------------+   |
   |  | container: app            |  | container: worker         |   |
   |  |   requests.memory: 256Mi  |  |   requests.memory: 1Gi    |   |
   |  |   limits.memory:   512Mi  |  |   limits.memory:   1Gi    |   |
   |  |   -> cgroup memory.max =  |  |   -> cgroup memory.max =  |   |
   |  |      512Mi                |  |      1Gi                  |   |
   |  +---------------------------+  +---------------------------+   |
   |         each container == one cgroup (Ch 7)                     |
   +-----------------------------------------------------------------+
```

- A **pod** is a group of containers sharing network + (optionally) IPC/volumes.
- Each **container** gets its **own cgroup**; its `limits.memory` becomes that
  cgroup's `memory.max`.
- The **pod** also has a parent cgroup summing its containers.
- The **node** has finite RAM; the scheduler packs pods using **requests**, and
  the kubelet protects the node using **eviction thresholds**.

## 8.2 Requests vs. limits — the two numbers that control everything

**They do completely different jobs. Conflating them is the #1 k8s memory
mistake.**

| | **`requests.memory`** | **`limits.memory`** |
|---|---|---|
| Purpose | **Scheduling** + eviction ranking | **Hard cap** (cgroup `memory.max`) |
| Enforced by | scheduler (bin-packing) | kernel cgroup (OOM kill) |
| Exceeding it | allowed (burst) if node has room | **OOMKilled**, exit 137 |
| Guarantees | node *reserves* this much for you | you can *never* exceed this |
| Node accounting | sum(requests) ≤ allocatable | not summed for scheduling |

```yaml
resources:
  requests:
    memory: "256Mi"   # scheduler finds a node with >=256Mi free (reserved for you)
  limits:
    memory: "512Mi"   # cgroup memory.max = 512Mi; exceed -> OOMKilled (137)
```

- **Request** = "reserve this for me; use it for scheduling." The scheduler
  ensures `sum(requests)` of all pods ≤ node **allocatable** memory. You are
  *guaranteed* your request; you may **burst above it** up to your limit if the
  node has spare RAM.
- **Limit** = "the kernel will kill me if I exceed this." It's `memory.max`.
- **Memory has no throttling.** Unlike CPU (which is compressible — you just get
  throttled), **memory is incompressible**: you can't be "slowed down" on RAM, so
  exceeding the limit means **death by OOM**, not degradation.
- **`limits` with no `requests`:** k8s sets `requests = limits`. **`requests`
  with no `limits`:** no `memory.max` cap → your container can use all node RAM
  and cause node pressure/eviction of *others*.

## 8.3 QoS classes — how k8s ranks who dies first

From the request/limit combination, k8s assigns each pod a **Quality of Service
class**, which controls **eviction order** and **`oom_score_adj`** (Ch 6.11).

```
   +-------------+---------------------------------+---------------------------+
   | QoS class   | Condition                       | Under node pressure       |
   +-------------+---------------------------------+---------------------------+
   | Guaranteed  | requests == limits for EVERY     | Last to be evicted;       |
   |             | container (cpu & memory set)    | most protective oom_score |
   +-------------+---------------------------------+---------------------------+
   | Burstable   | at least one request set, but   | Evicted after BestEffort; |
   |             | not Guaranteed                  | oom_score by usage/request|
   +-------------+---------------------------------+---------------------------+
   | BestEffort  | NO requests or limits at all    | FIRST to be evicted;      |
   |             |                                 | highest (worst) oom_score |
   +-------------+---------------------------------+---------------------------+
```

- **Guaranteed** (requests == limits): the safest. Its processes get a
  protective `oom_score_adj` so, under **node** pressure, the kernel prefers to
  kill others first. Use for latency-critical/stateful services.
- **Burstable** (the common case): can burst above request; `oom_score_adj` is
  computed from `1000 − (1000 × request / limit)`-ish, so pods using *far more
  than their request* score worse (die sooner). **Set requests realistically.**
- **BestEffort** (no requests/limits): scheduled anywhere, killed first, no
  guarantees. Fine for throwaway jobs; dangerous for anything important.

> **Two different kills — don't confuse them.** Exceeding your **own limit** →
> **cgroup OOMKill** (your container, regardless of QoS). **Node** running out of
> memory → **eviction** and **node-level OOM**, where **QoS decides the victim
> ordering.** Chapter 13 shows how to tell which happened.

## 8.4 OOMKilled — the anatomy of exit 137

```
   Container's charged memory (anon + shmem + kernel + non-reclaimable cache)
   climbs toward its cgroup memory.max...
        |
        v
   charge exceeds memory.max, kernel can't reclaim enough
        |
        v
   cgroup OOM killer SIGKILLs the top process in THAT container's cgroup
        |
        v
   kubelet sees exit code 137 (128 + SIGKILL 9)  ->  reason: OOMKilled
        |
        v
   restartPolicy kicks in -> CrashLoopBackOff if it keeps happening
```

**Diagnose it:**

```bash
kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[0].lastState.terminated}'
#   reason: OOMKilled, exitCode: 137, ...
kubectl describe pod <pod> | grep -A3 -i 'last state\|reason\|restart'
kubectl get events --field-selector reason=OOMKilling
# On the node: dmesg -T | grep -i oom   (Ch 6.11)
```

- **The signature of a leak vs. a spike.** OOMKilled every ~40 min with a
  sawtooth ramp = a **leak/retention** (Ch 11). OOMKilled during a specific
  request (big upload, batch) = a **transient peak** exceeding the limit → raise
  the limit or bound the operation.
- **Key subtlety:** it is **working set** (non-reclaimable ≈ anon + active), not
  RSS or VSZ, that's compared to the limit (Ch 3.14). Page cache from your file
  I/O counts in `memory.current` but the reclaimable part won't OOM you.

## 8.5 Node memory pressure & eviction — the *other* way pods die

Even if **no** pod exceeds its own limit, the **node** can run low on memory
(overcommitted requests, system daemons, page cache pressure). Then the
**kubelet's eviction manager** steps in — *before* the kernel OOM killer, if it
can — and evicts pods to reclaim memory.

```
   Node allocatable RAM shrinking...
        |
        | kubelet watches memory.available against evictionHard
        | (default: memory.available < 100Mi)
        v
   MemoryPressure condition on the node = True
        |
        v
   kubelet EVICTS pods to reclaim, in this order:
     1. BestEffort pods
     2. Burstable pods using MORE than their requests (most over first)
     3. Guaranteed / Burstable-within-request  (last resort)
        |
        v
   Evicted pod: status "Evicted", reason "The node was low on resource: memory"
        |
   If memory falls too fast for the kubelet, the KERNEL OOM killer fires first
   (node-level), using oom_score_adj set from QoS.
```

- **Eviction ≠ OOMKill.** Eviction is a **graceful** kubelet action (pod gets
  `Evicted` status, may reschedule elsewhere). OOMKill is the **kernel** SIGKILL
  (exit 137). You'll see different reasons; treat them differently.
- **`kubectl describe node`** shows `Conditions: MemoryPressure` and eviction
  thresholds. `kubectl get events` shows `Evicted` events.
- **Protect critical pods:** make them **Guaranteed** (requests == limits) and
  set **PriorityClass**; keep node **requests** honest so the scheduler doesn't
  overpack.

## 8.6 Reading a pod's *real* memory

Three levels, from cluster view down to cgroup truth (extends Ch 7.6):

```bash
# 1) Cluster metrics (metrics-server) -> WORKING SET, not RSS (Ch 3.14)
kubectl top pod <pod> --containers

# 2) Inside the container -> the cgroup ground truth
kubectl exec -it <pod> -- sh -c '
  cat /sys/fs/cgroup/memory.max        # your limit
  cat /sys/fs/cgroup/memory.current    # current usage
  grep -E "^(anon|file|shmem|slab|kernel_stack|inactive_file)" /sys/fs/cgroup/memory.stat
  cat /sys/fs/cgroup/memory.events     # oom_kill count etc.
'

# 3) Per-process breakdown inside the pod (Ch 3)
kubectl exec -it <pod> -- sh -c 'cat /proc/1/smaps_rollup | grep -E "Rss|Pss|Anonymous|Swap"'
```

- **`kubectl top` vs `top` inside the pod will differ** — `kubectl top` is
  working set; `top` shows RSS. Both are "right," measuring different things
  (Ch 3.14).
- **Compute working set yourself:** `memory.current − inactive_file` — this is
  what the eviction/OOM logic effectively uses.
- **The downward API** can inject your limit into the app so it self-tunes
  caches/workers to the *limit* (fixing the Ch 7.7 "host RAM" trap):

```yaml
env:
  - name: MEM_LIMIT_BYTES
    valueFrom:
      resourceFieldRef: { resource: limits.memory }
```

## 8.7 Volumes and where each kind of memory/storage lives

This is the section that stops "why is my `emptyDir` OOMKilling me?" incidents.
**Where you mount matters as much as what you write.**

| Volume type | Backed by | Counts as POD MEMORY? | Counts as disk/ephemeral? | Lifetime |
|---|---|---|---|---|
| **`emptyDir` (default)** | node disk | No (except page cache) | ✅ ephemeral storage | pod lifetime |
| **`emptyDir` `medium: Memory`** | **tmpfs (RAM)** | ✅ **YES — charged to the pod** | No | pod lifetime |
| **`/dev/shm`** (default 64Mi) | tmpfs (RAM) | ✅ **YES** | No | container/pod |
| **`hostPath`** | node's real path | No (except page cache) | node disk | node |
| **PersistentVolume (PVC)** | network/block storage (CSI) | No (except page cache) | external | survives pod |
| **ConfigMap / Secret** | tmpfs (RAM), small | ✅ tiny amount | No | pod |
| **projected / downwardAPI** | tmpfs (RAM), tiny | ✅ tiny | No | pod |

- **`emptyDir` (default, disk)** — scratch space on the node's disk; survives
  container restarts within the pod, dies with the pod. Counts as **ephemeral
  storage** (can trigger disk-pressure eviction), **not** memory.
- **`emptyDir` with `medium: Memory`** — a **tmpfs = RAM**. Everything written
  here is **charged to the pod's memory cgroup** and can **OOMKill** you.
  Excellent for fast scratch, dangerous if unbounded. **Set `sizeLimit`.**

```yaml
volumes:
  - name: scratch
    emptyDir:
      medium: Memory        # RAM-backed! counts toward pod memory
      sizeLimit: 512Mi      # ALWAYS set this or it can eat all pod memory
```

- **ConfigMaps & Secrets** are mounted as small **tmpfs** files (RAM), so they
  cost a little pod memory; Secrets stay in RAM deliberately (never written to
  disk). Usually negligible, but thousands of large ConfigMaps add up.
- **PersistentVolumes (via CSI drivers)** live on external storage (EBS, PD,
  Ceph, NFS). Not pod memory; but files you read/write populate **page cache**
  (reclaimable, counts in `memory.current`).
- **`hostPath`** mounts a node directory — not memory, but a security/portability
  smell; avoid except for node agents.

## 8.8 Fixing `/dev/shm` in Kubernetes

Unlike Docker's `--shm-size`, k8s has **no `shm-size` field**. The idiom is to
mount a memory `emptyDir` at `/dev/shm` (needed by PyTorch DataLoaders, OpenCV,
Chromium/Selenium — Ch 9):

```yaml
spec:
  containers:
    - name: app
      volumeMounts:
        - { name: dshm, mountPath: /dev/shm }
      resources:
        limits:
          memory: 2Gi       # remember: dshm usage counts INSIDE this limit!
  volumes:
    - name: dshm
      emptyDir:
        medium: Memory
        sizeLimit: 1Gi      # bound it so it can't consume the whole 2Gi limit
```

- **Critical accounting note:** the `/dev/shm` tmpfs counts **against your
  `limits.memory`**. If you give `/dev/shm` 1Gi inside a 2Gi limit, your app has
  only ~1Gi left. Size both together.

## 8.9 A production-grade memory spec

```yaml
apiVersion: apps/v1
kind: Deployment
metadata: { name: inference }
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: inference
          image: myrepo/inference:1.4
          resources:
            requests: { cpu: "2", memory: "2Gi" }   # honest steady-state
            limits:   { cpu: "2", memory: "3Gi" }   # headroom for peaks
          env:
            - { name: OMP_NUM_THREADS, value: "2" }      # cap native threads (Ch 5/7)
            - { name: OPENBLAS_NUM_THREADS, value: "2" }
            - { name: MALLOC_ARENA_MAX, value: "2" }     # glibc arenas (Ch 5.9)
            - name: MEM_LIMIT_BYTES                       # self-tune to the limit
              valueFrom: { resourceFieldRef: { resource: limits.memory } }
          volumeMounts:
            - { name: dshm, mountPath: /dev/shm }
      volumes:
        - name: dshm
          emptyDir: { medium: Memory, sizeLimit: 512Mi }
```

Design choices, justified: **requests < limits** (Burstable with headroom, but
requests honest so scheduling/eviction ranking is fair); **capped native
threads** (Ch 5/7); **`MALLOC_ARENA_MAX`** to curb glibc arena RSS; **downward
API** so the app sizes caches to the real limit; **bounded `/dev/shm`** that
lives *inside* the memory limit.

## 8.10 Common Kubernetes memory anti-patterns

- **No limits at all** → pods burst freely, cause **node pressure**, and get
  everyone (including themselves) evicted; noisy-neighbor incidents.
- **`limits ≫ requests`** on many pods → scheduler overpacks the node (packs by
  low requests), then real usage causes eviction storms. Keep the ratio sane.
- **Setting a limit equal to observed *peak*** → no headroom; a slightly bigger
  request OOMKills. Add ~20–50% over your working-set peak.
- **Ignoring `/dev/shm` accounting** → OOMKilled with a tiny app heap (Ch 9).
- **Sizing caches/threads from `free`/`cpu_count`** → the Ch 7.7 host-RAM trap.
- **Treating eviction and OOMKill as the same** → wrong fix; one is node
  pressure (raise requests / add nodes), the other is your own limit (raise
  limit / fix leak).

---

## Key takeaways

- **Requests = scheduling + eviction ranking (guaranteed, burstable above);
  Limits = cgroup `memory.max` (exceed → OOMKilled 137).** They are not
  interchangeable. Memory is **incompressible** — no throttling, only death.
- **QoS (Guaranteed/Burstable/BestEffort)** is derived from requests/limits and
  sets **eviction order + `oom_score_adj`**. Make critical pods **Guaranteed**.
- **Two distinct kills:** exceeding *your* limit → **cgroup OOMKill**; **node**
  pressure → **kubelet eviction** (graceful, QoS-ordered) or node OOM. Diagnose
  which before you "fix" it.
- **`kubectl top` = working set**, not RSS; the cgroup files
  (`memory.max/current/stat/events`) are ground truth. Use the downward API to
  self-tune to the limit.
- **`emptyDir{medium: Memory}`, `/dev/shm`, ConfigMaps/Secrets are RAM and count
  against the pod's memory limit** — always `sizeLimit` them; PVs/`hostPath`/
  default `emptyDir` are disk (except page cache).

## Practice exercises

1. Write three pod specs that produce **Guaranteed**, **Burstable**, and
   **BestEffort** QoS. Verify with `kubectl get pod <p> -o jsonpath='{.status.qosClass}'`.
2. Deploy a pod with `limits.memory: 256Mi` and an app that allocates a growing
   list; capture the `OOMKilled`/137 in `kubectl describe` and the `oom_kill`
   count in `memory.events`.
3. Mount an `emptyDir{medium: Memory}` and write 300Mi into it in a pod limited
   to 400Mi; observe the pod OOMKill and explain why (shmem charged to cgroup).
4. Use the downward API to inject `limits.memory` as an env var and print it from
   the app; compare to what `free -h` reports inside the pod.

## Quiz questions

1. A pod has `requests.memory: 512Mi`, `limits.memory: 1Gi`. On a node with
   spare RAM it uses 800Mi — is it OK? What if the node is full?
2. What QoS class is a pod with requests set but limits unset, and how does that
   affect its fate under node pressure?
3. Distinguish an **Evicted** pod from an **OOMKilled** pod: what triggered each,
   who acted (kubelet vs. kernel), and what status/exit you'd see.
4. Does data written to an `emptyDir` count against `limits.memory`? Does it
   depend on anything?
5. Your pod is OOMKilled but `tracemalloc` shows a tiny Python heap and
   `/dev/shm` is full. What's happening and how do you fix it in a pod spec?
6. Why is memory OOMKilled but CPU merely throttled when you exceed limits?
7. `kubectl top pod` shows 1.6Gi; `top` inside shows 2.1Gi RES. Which does the
   OOM decision use, and why can they differ?

## Suggested experiments

- Reproduce the two kills separately: (a) one pod exceeding its **own** limit →
  OOMKilled 137; (b) overpack a node so `MemoryPressure=True` and a BestEffort
  pod gets **Evicted**. Compare `kubectl get events` and pod statuses.
- `kubectl exec` into a running pod and dump `memory.stat`; correlate `anon`,
  `file`, and `shmem` with what your app is doing (Ch 7.12 workflow).
- Add/remove the `MALLOC_ARENA_MAX` and thread-count env vars on a NumPy service
  and compare `kubectl top pod` steady-state working set.
- Follow the repo playbook
  [`../05_production_playbook/04_kubernetes_debugging.md`](../05_production_playbook/04_kubernetes_debugging.md)
  end-to-end against a test pod; Chapter 13 turns it into a full root-cause
  workflow.

---

*Next up: **Chapter 9 — Shared Memory**, the deep dive on `/dev/shm`, tmpfs,
POSIX/SysV IPC, `multiprocessing.shared_memory`, when shared memory grows and
shrinks, and why Chromium, Selenium, PyTorch, and OpenCV need it — plus how to
size it correctly in Docker and Kubernetes.*

[← Chapter 7](07_docker_memory.md) · [Back to index](README.md)
