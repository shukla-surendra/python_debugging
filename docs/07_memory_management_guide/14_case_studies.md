<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 14 — Case Studies from Production

Theory becomes intuition when you see it fail in the wild. Each case study below
is a composite of real incidents, told in the same shape: **the setup**, **the
symptom**, **where the memory actually went**, **how the Chapter 13 workflow
found it**, and **the fix**. Read them as pattern-matching training — after a
dozen, you'll recognize most production memory failures on sight.

Every case cites the mechanism chapter so you can go deeper. The recurring
lesson: **memory goes where the data is largest and lives longest**, and the
tool that finds it depends on whether that data is Python objects, native
buffers, or shared memory.

> Prerequisites: Ch 5 (native), Ch 9 (shm), Ch 11 (patterns), Ch 13 (workflow).

## 14.1 Large-scale OCR pipeline — the un-closed image

- **Setup.** A Celery worker OCRs uploaded documents: for each page, open image →
  `convert("RGB")` → resize → Tesseract. Throughput ~5 docs/s, pods limited to
  2 GiB.
- **Symptom.** Workers OOMKilled every ~30 min; sawtooth that never returns to
  baseline (Ch 11.2 climb).
- **Where the memory went.** `memory.stat` `anon` dominated; `tracemalloc` nearly
  flat → **native** (Ch 13 S5a). memray pointed at **Pillow decode buffers**
  (Ch 5.5): the code kept every page's original `Image` in a per-doc list
  "for debugging," and each 6000×4000 RGB page is **72 MiB decoded**. 10 pages ×
  72 MiB = 720 MiB retained per in-flight doc; several concurrent docs → OOM.
- **How found.** Ch 13: S3 `anon` large → S5a `gc_objects` flat while RSS climbs
  → **native** → memray tree showed `PIL.Image` buffers under a retained list.
- **Fix.** Process pages in a generator, `im.close()` each page, never accumulate
  originals; set `Image.MAX_IMAGE_PIXELS` guard; `--max-tasks-per-child` on Celery
  as a safety net. RSS dropped to a flat ~500 MiB sawtooth.
- **Lesson.** Decoded image size has nothing to do with file size; retaining
  native buffers in an innocent list is the classic OCR/image leak.

## 14.2 PDF processing — decompression bombs & font caches

- **Setup.** A service rasterizes PDFs to images (pdf2image/PyMuPDF) for preview
  generation.
- **Symptom.** Occasional sudden OOM on *specific* files, not a steady climb.
- **Where the memory went.** Two sources: (1) a **decompression bomb** — a small
  PDF page declaring huge dimensions rasterized to a multi-GiB bitmap (native, Ch
  5.5); (2) PyMuPDF/font glyph caches growing with document variety
  (retention, Ch 11).
- **How found.** Not a climb → **spike** shape (Ch 11.2). Correlating OOM
  timestamps with request logs identified the offending files; memray on those
  files showed the giant rasterization buffer.
- **Fix.** Cap render DPI and output dimensions; validate declared page size
  before rasterizing; render in a **subprocess with its own memory limit** so one
  bad file can't take the worker down (subprocess exit guarantees RSS release, Ch
  4.9); bound the font cache.
- **Lesson.** "Spike, not climb" ⇒ a *specific input*, not a leak. Isolate risky
  work in a subprocess with a hard limit.

## 14.3 Image-processing batch job — the hidden NumPy copies

- **Setup.** A nightly batch resizes/augments millions of images with
  OpenCV+NumPy.
- **Symptom.** Peak RSS ~5× the expected working set; intermittent OOM on large
  images.
- **Where the memory went.** **Hidden copies** (Ch 5.3/5.6): `img.astype`,
  `cvtColor`, boolean masks, and `np.concatenate` each allocated a fresh full
  buffer; at peak, 5 copies of a large frame were live simultaneously. Also
  OpenCV's native thread pool (Ch 5.6) multiplied scratch buffers on a 64-core
  node.
- **How found.** scalene (Ch 12.3) showed high **native** memory and copy volume
  on specific lines; `memory_profiler` line view pinpointed the `astype`.
- **Fix.** Operate in-place where possible (`cv2.resize(..., dst=...)`), reuse
  buffers, keep dtype small (uint8 not float64 until needed), `cv2.setNumThreads`
  to the CPU limit; process in chunks. Peak RSS fell ~4×.
- **Lesson.** Vectorized code is memory-cheap only if you avoid copies; each
  transform is a new buffer unless it's a view.

## 14.4 ML inference service — the PyTorch caching allocator "leak"

- **Setup.** FastAPI + PyTorch model served on GPU; batch inference.
- **Symptom.** `nvidia-smi` shows GPU memory climbing and "never freed"; team
  suspected a leak. Host RSS was fine.
- **Where the memory went.** **Not a leak** — the PyTorch **caching allocator**
  (Ch 5.7) holds freed GPU blocks; `memory_reserved()` grew while
  `memory_allocated()` was stable. Separately, a real bug: keeping `loss`/output
  tensors with autograd graph attached retained activations.
- **How found.** `torch.cuda.memory_summary()` showed reserved ≫ allocated
  (caching, benign); the retained-graph bug showed as `memory_allocated()`
  growing across requests.
- **Fix.** For the benign part: nothing (or `empty_cache()` between very
  different batch sizes). For the real bug: `with torch.no_grad():` for inference,
  `.detach()`/`.cpu()` before storing outputs, don't keep tensors in a cache with
  their graph.
- **Lesson.** GPU memory is a separate pool (not RSS/cgroup); reserved-vs-allocated
  distinguishes allocator caching from a real tensor leak. Inference must run
  under `no_grad`.

## 14.5 ML training DataLoader — `/dev/shm` `Bus error`

- **Setup.** Training job, `DataLoader(num_workers=8, pin_memory=True)`, default
  container `/dev/shm` (64 MiB).
- **Symptom.** `RuntimeError: DataLoader worker (pid X) is killed by signal: Bus
  error`, crashing minutes in.
- **Where the memory went.** Workers pass collated batches to the main process
  via **POSIX shared memory in `/dev/shm`** (Ch 9.6); 8 workers × prefetch × big
  batches exceeded 64 MiB.
- **How found.** Symptom string is diagnostic (Ch 9.6 cheat-sheet); `df -h
  /dev/shm` full; `memory.stat` `shmem` maxed.
- **Fix.** Mount a bounded memory `emptyDir` at `/dev/shm` (Ch 8.8), e.g. 2 GiB
  *inside* an 8 GiB limit; or reduce `num_workers`/`batch_size`; or
  `set_sharing_strategy('file_system')`. Also watch pinned host memory (Ch 5.7).
- **Lesson.** `Bus error` in a DataLoader ≈ `/dev/shm` too small. Size shm inside
  the memory limit (Ch 9.8 golden rule).

## 14.6 Batch ETL with pandas — the object-dtype explosion

- **Setup.** A daily job reads a 3 GiB CSV of mostly string columns into pandas,
  joins, and writes Parquet.
- **Symptom.** `read_csv` peaks at ~18 GiB; OOM on the join.
- **Where the memory went.** **`object`-dtype string columns** (Ch 5.4): 60M
  short strings stored as pointers to individual Python `str` objects — ~10–20×
  the raw bytes. Plus `read_csv` parse buffers and a full copy during `merge`.
- **How found.** `df.info(memory_usage="deep")` (Ch 5.4) showed object columns
  dominating; the merge doubled it.
- **Fix.** `dtype="string[pyarrow]"`/`category` for string columns (Ch 5.4/5.8);
  `read_csv(chunksize=...)` and process in chunks; `usecols`; `engine="pyarrow"`;
  drop intermediates. Peak fell from 18 GiB to ~4 GiB.
- **Lesson.** In pandas, `object` string columns are the #1 memory sink; Arrow
  strings + chunking are the fix. Always use `deep=True` to measure.

## 14.7 Streaming pipeline — unbounded in-flight buffering

- **Setup.** An async service consumes a fast source and writes to a slow sink,
  buffering messages in an `asyncio.Queue`.
- **Symptom.** Memory grows without bound under load spikes; OOM during traffic
  peaks.
- **Where the memory went.** **Backpressure absent** — the unbounded queue
  accumulated messages faster than the slow sink drained them (retention, Ch 11).
  All Python objects (`anon`, tracemalloc-visible).
- **How found.** Ch 13 S4 climb tracked producer rate; tracemalloc pointed at the
  queue's internal deque.
- **Fix.** **Bound the queue** (`asyncio.Queue(maxsize=N)`) so producers await
  when full (natural backpressure); add flow control; scale the sink. Memory
  became bounded by `maxsize`.
- **Lesson.** Every buffer between a fast producer and slow consumer must be
  bounded or it *is* a leak under load. Backpressure is a memory feature.

## 14.8 Async workers — blocking the loop while holding references

- **Setup.** FastAPI async endpoints; one handler does heavy CPU work inline.
- **Symptom.** Under load, memory climbs and latency explodes; requests pile up.
- **Where the memory went.** A blocked event loop (Ch: concurrency) meant
  **in-flight requests accumulated** — each holding its parsed body, response
  buffers, and DB rows in memory — because nothing completed. Not a leak per se;
  **concurrency-induced retention**.
- **How found.** `py-spy dump` (Ch 12.3) showed all workers stuck in the CPU
  function; request count (and thus retained per-request memory) climbing.
- **Fix.** Move CPU work off the loop (`run_in_executor`/process pool); bound
  concurrency (semaphore, worker count); set request timeouts. Memory and latency
  normalized.
- **Lesson.** Memory growth is sometimes a *concurrency* symptom: stalled work ⇒
  more simultaneously-live requests ⇒ more memory. Fix the stall.

## 14.9 Multiprocessing — fork copy-on-write erosion & duplicated data

- **Setup.** A pre-fork pool (`multiprocessing`/Gunicorn) loads a 1.5 GiB
  reference dataset once, then forks 16 workers expecting to *share* it.
- **Symptom.** Node memory ≈ 16 × 1.5 GiB instead of ~1.5 GiB shared; OOM /
  scheduling failures.
- **Where the memory went.** **COW erosion** (Ch 6.8): CPython refcount writes on
  every access to the shared Python objects triggered copy-on-write, so each
  worker drifted toward a private copy. **PSS ≪ sum(RSS)** early, then PSS climbed
  toward RSS (Ch 3).
- **How found.** `smem` PSS vs. summed RSS (Ch 12.2) showed sharing eroding over
  time.
- **Fix.** Store the dataset as a **NumPy/Arrow buffer** (no per-object refcounts
  → stays shared, Ch 6.8), or in real **shared memory** (Ch 9), or
  `gc.freeze()`/`gc.disable()` in workers after load. Sharing held; footprint
  dropped to ~1.5 GiB + small per-worker overhead.
- **Lesson.** "Fork shares memory" is only true until CPython writes refcounts.
  Share large read-only data as native buffers, not Python object graphs.

## 14.10 FastAPI service — the unbounded response cache

- **Setup.** FastAPI app with a hand-rolled `dict` cache keyed by request params
  "to speed things up."
- **Symptom.** Slow steady climb over days to OOM; the textbook Ch 13 case.
- **Where the memory went.** **Unbounded cache** (Ch 11.4 #1): unique keys never
  evicted; Python objects, tracemalloc-visible.
- **How found.** Exactly the Ch 13 S5b path: tracemalloc snapshot-diff →
  `app/cache.py` line; objgraph backrefs → the module-level dict.
- **Fix.** `functools.lru_cache(maxsize=...)` or `cachetools.TTLCache`; or Redis
  as an out-of-process cache with its own eviction. Climb became a plateau.
- **Lesson.** Every in-process cache needs a **bound and an eviction policy**. An
  unbounded cache is a leak with good intentions.

## 14.11 Celery workers — task-scoped retention & big results

- **Setup.** Celery workers process jobs; results (large) returned via the result
  backend; long-lived worker processes.
- **Symptom.** Worker RSS ratchets up job over job, never fully returning (Ch
  11.2 fragmentation/retention).
- **Where the memory went.** Three contributors: (1) per-task large allocations
  fragmenting the heap (Ch 4.10/5.9) so RSS plateaus high; (2) module-level state
  accumulating across tasks; (3) big task results held until serialized.
- **How found.** RSS plateaued-high but didn't track a single line (tracemalloc
  modest) → **retention/fragmentation**, not a pure leak (Ch 11.7).
- **Fix.** **`worker_max_tasks_per_child`** (recycle workers — the standard Celery
  fix, Ch 15) to reset RSS; move big work to subprocesses; `MALLOC_ARENA_MAX`/
  jemalloc; avoid module-level accumulation; stream large results to storage
  instead of returning them.
- **Lesson.** Long-lived workers accumulate fragmentation even without a bug;
  **recycling** is the pragmatic, correct answer.

## 14.12 Kafka consumers — fetch buffers, batch size & lag

- **Setup.** A Kafka consumer processes messages; `max.poll.records` /
  `fetch.max.bytes` tuned for throughput; consumer lag under load.
- **Symptom.** Memory spikes proportional to lag; OOM when the consumer falls
  behind.
- **Where the memory went.** Large **fetch buffers** hold many messages in flight
  (native + Python), and when the consumer lags, it fetches big batches it then
  holds while processing. Deserializing all records up front materialized huge
  Python object lists (retention, Ch 11).
- **How found.** OOM correlated with **consumer lag** metrics; memory scaled with
  `max.poll.records` × message size.
- **Fix.** Reduce `max.poll.records`/`fetch.max.bytes`; process and **release**
  messages incrementally (don't build a giant list); commit offsets promptly;
  bound in-flight work; scale partitions/consumers to cap per-consumer batch.
  Memory became proportional to batch, not lag.
- **Lesson.** Consumer memory ≈ in-flight batch size, and lag multiplies it.
  Bound the batch and process streaming, not bulk.

## 14.13 Cross-case pattern summary

| Case | Where memory went | Shape | Tool that found it | Root fix |
|---|---|---|---|---|
| OCR (14.1) | Pillow buffers retained in list | climb | memray | close/stream images |
| PDF (14.2) | decompression bomb / caches | spike | logs + memray | subprocess + DPI cap |
| Image batch (14.3) | NumPy hidden copies | high peak | scalene/mprof | in-place, small dtype |
| ML inference (14.4) | GPU caching + retained graph | GPU climb | cuda memory_summary | `no_grad`/detach |
| DataLoader (14.5) | `/dev/shm` | Bus error | df /dev/shm, shmem | bigger shm / fewer workers |
| pandas ETL (14.6) | object-dtype strings | huge peak | info(deep) | Arrow strings + chunking |
| Streaming (14.7) | unbounded queue | climb | tracemalloc | bound queue (backpressure) |
| Async (14.8) | stalled in-flight requests | climb | py-spy | offload CPU, bound concurrency |
| Multiprocessing (14.9) | COW erosion | PSS→RSS | smem PSS | share native buffers |
| FastAPI cache (14.10) | unbounded dict | slow climb | tracemalloc+objgraph | bounded cache |
| Celery (14.11) | fragmentation/retention | plateau-high | RSS vs live | recycle workers |
| Kafka (14.12) | fetch batch × lag | spike w/ lag | lag correlation | bound batch, stream |

**The meta-pattern:** find the **largest, longest-lived data**, identify whether
it's **Python / native / shared**, and check whether it's **bounded**. Almost
every fix is one of: *bound it, stream it, share it as a native buffer, isolate
it in a subprocess, or recycle the worker.*

---

## Key takeaways

- **Memory goes where data is largest and lives longest** — decoded images,
  NumPy copies, object-dtype strings, in-flight batches, unbounded caches/queues.
- **The tool follows the memory kind:** native buffers → **memray/scalene**;
  Python objects → **tracemalloc/objgraph**; `/dev/shm` → `df`/`shmem`; sharing
  → **smem PSS**; GPU → `torch.cuda.memory_summary`.
- **Shape tells the category:** climb = leak/retention; spike = bad input;
  plateau-high = fragmentation; Bus error = `/dev/shm`; PSS→RSS = COW erosion.
- **The five universal fixes:** *bound it* (caches/queues/batches), *stream it*
  (generators/chunks), *share it as a native buffer* (COW-safe), *isolate it in a
  subprocess* (guaranteed RSS release + blast radius), *recycle the worker*
  (fragmentation/retention).
- **Inference under `no_grad`; consumers/queues bounded; big read-only data as
  Arrow/NumPy** — three habits that prevent most of these cases.

## Practice exercises

1. For each case, cover the "fix" column and predict it from the "where/shape"
   columns. Check against §14.13.
2. Reproduce the FastAPI unbounded-cache case (14.10) locally and fix it with
   `TTLCache`; confirm the shape flips from climb to plateau (Ch 11.9).
3. Reproduce the pandas object-dtype case (14.6): load a string-heavy CSV as
   `object` vs `string[pyarrow]`; quantify the peak-memory difference.
4. Reproduce the multiprocessing COW case (14.9): fork workers sharing a big
   Python `dict` vs. a NumPy array; compare `smem` PSS over time.

## Quiz questions

1. A 3 MB JPEG OCR pipeline OOMs at 2 GiB. Where's the memory, and why is file
   size irrelevant?
2. GPU memory climbs and "never frees," host RSS fine. Leak or not? How do you
   tell, and what's the inference-specific fix?
3. A DataLoader dies with `Bus error`. One-line diagnosis and two fixes.
4. pandas `read_csv` of a 3 GiB string-heavy file peaks at 18 GiB. Why, and how
   do you cut it ~4×?
5. Node uses 16× the data size after forking 16 workers meant to share it. Name
   the mechanism and the fix.
6. A Kafka consumer OOMs only when it lags. Explain the relationship and the fix.
7. Which single fix (of the five universal ones) applies to Celery fragmentation,
   and why is it correct rather than a hack?

## Suggested experiments

- Pick three cases and reproduce them with the repo victim
  [`../../workloads/memory_leak.py`](../../workloads/memory_leak.py) as a starting
  point (extend it for images/pandas/queue), then run the Ch 13 workflow to
  "discover" the cause as if you didn't know it.
- Build a tiny "case classifier": given (memory kind, shape, symptom string),
  print the likely case and fix from §14.13.
- Take a service you operate and map its top memory consumer to the closest case
  here; decide which of the five universal fixes applies.

---

*Next up: **Chapter 15 — Optimization Techniques**, the fix toolbox referenced
throughout these cases: generators/streaming/chunking, `__slots__`, weakrefs,
object pooling, cache tuning, batch sizing, avoiding copies, NumPy/pandas/OpenCV
tricks, worker recycling, and thread-vs-process trade-offs.*

[← Chapter 13](13_kubernetes_debugging.md) · [Back to index](README.md) · [Chapter 15 →](15_optimization.md)
