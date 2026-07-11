<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 21 — Best Practices

The operational wisdom that keeps memory incidents from happening — distilled
from every mechanism and case study in this book. This chapter is deliberately
prescriptive: do's, don'ts, anti-patterns, and the monitoring/capacity/tuning
practices that separate a service that quietly runs for months from one that
pages you at 3 a.m.

> Prerequisites: the whole book. This is the "what to actually do" synthesis of
> Ch 8 (limits/QoS), Ch 11 (patterns), Ch 13 (workflow), Ch 15 (optimization).

## 21.1 Development do's and don'ts

**Do:**
- **Stream, don't materialize** — generators/chunks over giant lists (Ch 15.1).
  The cheapest memory is memory you never allocate.
- **Bound every cache and queue** — size + TTL; an unbounded buffer is a leak
  (Ch 15.5, 14.7, 14.10).
- **Measure the right thing** — working set for k8s, PSS for fleets, USS for
  leaks, `nbytes`/`deep=True` for native (Ch 3, 5).
- **Use `weakref`** for back-references, observer registries, and object-keyed
  caches (Ch 15.4).
- **Close native resources** — images, files, cursors, `VideoCapture` — via
  context managers (Ch 14.1, 11.6).
- **Prefer native/columnar for bulk data** — NumPy/Arrow over lists of objects;
  `__slots__`/dataclass-slots for millions of instances (Ch 5, 15.3).
- **Run inference under `torch.no_grad()`**; detach tensors before caching
  (Ch 14.4).

**Don't:**
- **Don't call `gc.collect()` in hot loops** "to be safe" — it's CPU cost with no
  memory benefit for non-cyclic garbage (Ch 4.8).
- **Don't assume `del` frees RAM** — it frees to the allocator, not the OS
  (Ch 4.9).
- **Don't size caches/threads from `free`/`os.cpu_count()`** in a container —
  they report the host (Ch 7.7).
- **Don't store exceptions** (they pin frames via `__traceback__`) or accumulate
  request state in module-level structures (Ch 11.4).
- **Don't trust `tracemalloc` for native memory** — it's blind to it (Ch 5.2).

## 21.2 Container & Kubernetes sizing

**The sizing formula:**

```
   request.memory  ≈  steady-state working-set p50–p90   (honest -> good scheduling)
   limit.memory    ≈  peak working set × 1.2 – 1.5        (headroom for spikes)
   /dev/shm + app working set  MUST fit under limit.memory (Ch 9.8)
```

**Do:**
- **Set both requests and limits** for anything important; make critical/stateful
  pods **Guaranteed** (requests == limits) so node pressure kills others first
  (Ch 8.3).
- **Keep requests honest** — the scheduler and eviction ranking depend on them;
  lying causes overpacking and eviction storms (Ch 8.10).
- **Cap native thread pools** to the CPU limit:
  `OMP/OPENBLAS/MKL/NUMEXPR_NUM_THREADS`, `cv2.setNumThreads`,
  `torch.set_num_threads` (Ch 5.6, 7.5).
- **Cap glibc arenas** (`MALLOC_ARENA_MAX=2`) and consider **jemalloc** for
  long-running data/ML services (Ch 5.9–5.10).
- **Bound `/dev/shm`** via a memory `emptyDir` with `sizeLimit`, sized inside the
  limit (Ch 8.8, 9.8).
- **Inject the limit** via the downward API so the app self-tunes caches/workers
  (Ch 8.6, 7.7).

**Don't:**
- **Don't set `limit ≫ request`** across many pods (overpacking → eviction).
- **Don't set the limit == observed peak** (no headroom → OOM on the next spike).
- **Don't omit limits** on untrusted/bursty workloads (noisy-neighbor node
  pressure).
- **Don't forget `/dev/shm` counts against the limit** (Ch 9).

## 21.3 Anti-patterns (and the fix)

| Anti-pattern | Why it hurts | Fix |
|---|---|---|
| Unbounded in-process cache | slow leak → OOM (Ch 14.10) | `lru_cache(maxsize)`/`TTLCache`/Redis |
| `readlines()` / `list(gen)` on big data | peak = whole dataset | stream/chunk (Ch 15.1–2) |
| pandas `object` string columns | 10–20× memory (Ch 5.4) | `string[pyarrow]`/`category` |
| Sizing from `free`/`cpu_count` in a container | OOM at real limit (Ch 7.7) | read cgroup / downward API |
| Native lib threads uncapped | RSS blowup on many-core (Ch 5.6) | `*_NUM_THREADS` |
| Accumulating frames/tensors/images in a list | native retention (Ch 14.1) | stream + `close()`/detach |
| `limit ≫ request` everywhere | node overpack → evictions (Ch 8.10) | sane ratio, honest requests |
| Unbounded queue (fast prod/slow cons) | OOM under load (Ch 14.7) | bounded queue (backpressure) |
| Fork + big Python dict shared | COW erosion → N× (Ch 14.9) | NumPy/Arrow/shared memory |
| `gc.collect()` in a request path | latency spikes, no benefit | remove it (Ch 4.8) |
| Raising the limit to "fix" a leak | masks it → OOM at new ceiling | find the reference (Ch 13.8) |
| Ignoring `oom_kill`/eviction distinction | wrong fix | classify first (Ch 8.5, 13) |

## 21.4 Monitoring & alerting

**Alert on (signal → threshold idea):**
- **Working-set / limit ratio** > 0.85 sustained → approaching OOM (Ch 3.14).
- **`container_memory_oom_kill`/`oom_events` rate** > 0 → already OOMing (Ch 8.4).
- **Pod restarts with reason OOMKilled** → CrashLoop risk.
- **Major-fault rate** (`majflt/s`) rising → memory pressure/thrashing (Ch 6.4).
- **Node `MemoryPressure` / eviction events** → capacity problem (Ch 8.5).
- **`shmem` growth** in `memory.stat` → `/dev/shm` creep (Ch 9.7).
- **Swap in/out** (`si`/`so`) sustained on nodes that have swap (Ch 6.6).

**Don't alert on:**
- **VSZ** (a promise, not a cost — Ch 3.2).
- **`free` being low** (page cache is healthy — alert on `available`, Ch 3.12).
- **Minor faults** (normal and constant, Ch 6.4).
- **RSS in absolute terms** without comparing to the limit / baseline.

**Track (dashboards, not alerts):**
- Working set + limit line per container; **PSS** per fleet for capacity; RSS
  trend shape (climb/plateau/sawtooth — Ch 11.2); `memory.stat` breakdown
  (anon/shmem/file/slab); GC stats for latency-sensitive services.

**Continuous profiling:** run always-on low-overhead sampling (pyroscope +
memray/eBPF) so you can inspect allocations *at the OOM moment* (Ch 12.3) — the
single highest-leverage observability investment for memory.

## 21.5 Capacity planning

- **Budget with PSS, not summed RSS** — shared libraries are counted once; summing
  RSS overestimates and wastes nodes (Ch 3.4).
- **Leave headroom** for page cache, kernel/slab, and spikes — don't pack nodes to
  100% of requests.
- **Account for peak, not average** — a service that averages 800 MiB but peaks at
  1.6 GiB needs a ~2 GiB limit.
- **Size `/dev/shm` and pinned memory explicitly** for ML/DataLoader workloads
  (Ch 9.8).
- **Model the fleet:** `nodes ≈ ceil(Σ PSS(pods) + headroom) / node_allocatable`;
  validate with load tests, not spreadsheets alone.
- **Plan for restarts:** worker recycling means brief RSS resets — ensure enough
  replicas that a recycling wave doesn't drop capacity (Ch 15.11).

## 21.6 Memory budgeting for a service

Write down a memory budget per container, e.g.:

```
   limit.memory: 2Gi  breaks down as:
     baseline (interpreter + libs, PSS)  ~150 MiB
     model / warm data (native)          ~600 MiB
     per-request working set × concurrency ~800 MiB (peak)
     /dev/shm (bounded emptyDir)          256 MiB
     headroom (spikes, fragmentation)     ~200 MiB
     ------------------------------------------------
     total                                ~2 GiB  <= limit  ✓
```

If the pieces don't fit under the limit, the design is wrong *before* you deploy
— shrink the model, bound concurrency, or raise the limit deliberately. This
one-page budget prevents most "why did it OOM?" surprises.

## 21.7 GC tuning (only when measured)

- **Default is fine for most services.** Tune only if GC pauses show up in latency
  profiles or you have a huge long-lived heap (Ch 4.6).
- **Raise thresholds** (`gc.set_threshold(50_000, 500, 500)`) to collect less
  often (less CPU, slightly more RAM) for allocation-heavy workloads.
- **`gc.freeze()` after warm-up / before fork** — moves warm objects out of GC
  scanning, improving COW sharing in pre-fork servers (Ch 6.8).
- **`gc.disable()` only in tightly-controlled batch jobs** where you know there
  are no unbounded cycles — measure the risk (Ch 11.5).
- **Always A/B measure** wall-time and peak RSS before/after; blind GC tuning
  usually makes things worse.

## 21.8 Allocator & runtime tuning (code-free)

The reliable, no-code-change wins (Ch 5.9–5.10, 15.13):

```dockerfile
ENV MALLOC_ARENA_MAX=2
ENV LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so.2   # measure on a canary
ENV MALLOC_CONF=background_thread:true,dirty_decay_ms:1000
ENV OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 NUMEXPR_NUM_THREADS=2
```
- **Recycle workers** for retention/fragmentation: `gunicorn --max-requests`,
  Celery `worker_max_tasks/memory_per_child`, uWSGI `max-requests`/`reload-on-rss`
  (Ch 15.11).
- **Isolate risky/heavy work in subprocesses** for guaranteed RSS release and
  blast-radius containment (Ch 15.12).

## 21.9 Incident response checklist

When a memory alert fires, follow Chapter 13 — condensed:

```
   [ ] Is it memory? (OOMKilled / 137, not liveness/CPU/disk)     Ch 13.1
   [ ] Working set vs limit? memory.events oom_kill count?        Ch 13.2
   [ ] memory.stat kind: anon / shmem / file / slab?              Ch 13.3
   [ ] Shape: leak (climb) / retention (plateau) / spike?         Ch 13.4
   [ ] Localize: Python (tracemalloc/objgraph) or native (memray)?
       shmem (/dev/shm) or fd/socket (lsof)?                      Ch 13.5
   [ ] Node pressure vs your limit? (MemoryPressure/Evicted)      Ch 13.6
   [ ] Fix + VERIFY shape changed + oom_kill stops                Ch 13.7
   [ ] Stopgap (raise limit / recycle) logged as follow-up        Ch 13.8
```

Keep this taped to the wall (or in the runbook). It turns panic into procedure.

## 21.10 The ten commandments (the whole book in ten lines)

1. **Measure working set, not RSS/VSZ** — it's what OOM-kills you (Ch 3.14).
2. **`del` frees to the allocator, not the OS** — RSS won't drop (Ch 4.9).
3. **Most ML/data memory is native** — `tracemalloc` is blind; use memray/RSS
   (Ch 5).
4. **Containers report the host** — read cgroup files, cap threads to the limit
   (Ch 7.7).
5. **`/dev/shm`/tmpfs is RAM and counts against the limit** — bound it (Ch 9).
6. **Bound every cache, queue, and batch** — unbounded = leak (Ch 11, 15).
7. **Does it plateau?** — the one test that separates leak from retention
   (Ch 11.3).
8. **Requests = scheduling, Limits = OOM cap** — set both, honestly (Ch 8.2).
9. **Verify fixes by the graph shape over a long run**, not a smoke test
   (Ch 13.7).
10. **When you can't fix it, recycle the worker or isolate in a subprocess**
    (Ch 15.11–12).

---

## Key takeaways

- **Prevention beats debugging:** stream, bound, cap threads, size honestly, and
  budget memory *before* deploying — most incidents are designed-in.
- **Set both requests and limits; make critical pods Guaranteed; keep requests
  honest** — QoS and scheduling depend on it (Ch 8).
- **Alert on working-set/limit ratio, oom_kill rate, and major faults — never on
  VSZ, `free`, or minor faults.** Run continuous profiling so you have data at the
  OOM moment.
- **Capacity-plan with PSS + headroom for peak**, and write a one-page per-service
  memory budget.
- **Tune GC/allocators only when measured**; recycle workers and isolate heavy
  work as reliable, low-risk safety nets.

## Practice exercises

1. Write a one-page memory budget (§21.6) for a service you operate; check whether
   the pieces fit under the current limit.
2. Audit a deployment against §21.3 anti-patterns; list every one it commits and
   the fix.
3. Define the alert rules from §21.4 (working-set ratio, oom_kill, major faults)
   in your monitoring system; remove any VSZ/`free`/minor-fault alerts.
4. Turn §21.9 into a runbook entry and dry-run it against a past incident.

## Quiz questions

1. Give the memory sizing formula for requests vs. limits and justify each.
2. Name three things you should alert on and three you should never alert on.
3. Why capacity-plan with PSS instead of summed RSS?
4. When is raising the limit the right fix, and when is it a band-aid?
5. Which two "safety nets" reliably handle memory growth you can't immediately
   fix, and why?
6. Recite as many of the ten commandments as you can; for each, name its chapter.

## Suggested experiments

- Take a real service, produce its §21.6 budget from measured working set + PSS,
  and compare to its configured limit — adjust if they disagree.
- Implement §21.4 alerting on a test cluster, trigger an OOM, and confirm the
  right alert (not VSZ/`free`) fires.
- Run the §21.9 checklist against Lab 16 (Ch 20) end-to-end until it's reflexive.

---

*Next up: the **Appendix** — glossary (Linux/Python/Kubernetes/Docker terms),
quick-reference tables, decision trees, troubleshooting flowcharts, and further
reading (books, kernel docs, CPython source, Kubernetes docs, PEPs).*

[← Chapter 20](20_practical_labs.md) · [Back to index](README.md) · [Appendix →](22_appendix.md)
