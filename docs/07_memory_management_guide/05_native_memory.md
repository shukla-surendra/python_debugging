<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 5 — Native Memory

Chapter 4 ended on a warning: `tracemalloc` says "nothing is leaking" while RSS
climbs to the moon and the pod gets `OOMKilled`. This chapter explains that
gap. The memory that dominates real ML, data, and image-processing workloads
mostly lives **outside** CPython's allocator entirely — in buffers allocated by
C/C++/CUDA libraries through `malloc`, `mmap`, or their own private allocators.

This is the single biggest blind spot for Python engineers. Master it and you
can debug the OOMs that "impossible" — the ones where every Python tool reports
a tiny heap.

> Prerequisites: Chapter 2 (heap vs. mmap, why `munmap` returns memory but the
> heap doesn't), Chapter 4 (pymalloc handles small Python objects; ≥512 B and
> big buffers bypass it to `malloc`/`mmap`).

## 5.1 The two heaps: Python's vs. the process's

There is not "a heap" in a Python process — there are **layers**, and profilers
see different ones:

```
   +-----------------------------------------------------------------+
   |  PYTHON OBJECTS (PyObject graph)          <- tracemalloc SEES    |
   |  ints, str, list, dict, your instances      this layer only      |
   +-----------------------------------------------------------------+
   |  pymalloc arenas (small objects <=512B)   <- tracemalloc SEES    |
   +-----------------------------------------------------------------+
   |  NATIVE ALLOCATIONS via malloc / mmap     <- tracemalloc is BLIND|
   |  NumPy ndarray buffers, PyTorch tensors,     memray / OS tools    |
   |  OpenCV Mats, Pillow images, Arrow buffers,  SEE this             |
   |  pandas block values, model weights,                              |
   |  CUDA host-pinned buffers, thread stacks                          |
   +-----------------------------------------------------------------+
   |  glibc malloc arenas  /  jemalloc  /  tcmalloc                    |
   +-----------------------------------------------------------------+
   |  Linux virtual memory: [heap] (brk) + anonymous mmaps  (Ch 1-2)  |
   +-----------------------------------------------------------------+
                          |
                          v
                    RSS  <- the OS counts ALL of the above
```

**The crux:** `sys.getsizeof(arr)` on a NumPy array returns ~112 bytes — the
size of the *Python wrapper object*. The actual 800 MB data buffer is a native
`malloc`/`mmap` allocation the wrapper merely points at. RSS counts the 800 MB;
`getsizeof` and `tracemalloc` (mostly) don't.

## 5.2 Why Python profilers can't see native memory

- **`tracemalloc`** hooks CPython's allocator (`PyMem_*`). Libraries that call
  the system `malloc`/`mmap` **directly** (which is nearly all C-extension data
  buffers) never touch that hook, so `tracemalloc` doesn't record them. It's a
  *Python-allocation* profiler, not a *process-memory* profiler.
- **`sys.getsizeof`** reports an object's own struct size, not the external
  buffers it references. For NumPy/Torch/pandas it is almost meaningless.
- **`gc.get_objects()` / objgraph / Pympler** walk the *Python object graph* —
  they can tell you a giant array's wrapper is retained, but not the byte size
  of its native buffer accurately, and they can't see buffers with no live
  Python wrapper at all.

**What CAN see native memory:** the OS (`RSS` via `/proc`, `pmap`, `smem` —
Chapter 3), **`memray`** (intercepts `malloc`/`free` at the C level — the right
tool here, Chapter 12), library-specific tools (`torch.cuda.memory_summary()`),
and allocator introspection (`malloc_stats()`, jemalloc stats).

> **Interview-grade summary:** *tracemalloc measures allocations made through
> Python's allocator; native library buffers go through the system allocator and
> are invisible to it. Use RSS + memray to see the whole process.*

## 5.3 NumPy

- **What it is / where the memory lives.** A NumPy `ndarray` is a thin Python
  wrapper around a **single contiguous native buffer** (`malloc` for small,
  `mmap` for large). `arr.nbytes` = the real data size; the buffer is **unboxed
  and contiguous** — a `float64` element is 8 raw bytes, not a 28-byte
  `PyObject`.
- **Why it's efficient.** A Python list of 1M floats ≈ 8 MB pointers + ~28 MB of
  float objects ≈ **36 MB**; a NumPy `float64` array of 1M ≈ **8 MB**. ~4–5×
  smaller, and cache-friendly. This is *the* reason to vectorize.
- **When it grows / hidden copies.** The classic OOM: operations that silently
  **copy** the whole buffer. `arr.astype(np.float32)`, `arr.T.copy()`,
  `np.concatenate`, fancy indexing (`arr[mask]`), and most arithmetic
  (`a + b` makes a new array) each allocate a fresh buffer. A "20 GB" pipeline is
  often 4 GB of data × 5 simultaneous copies.
- **Views vs. copies (memorize this).** Slicing (`arr[10:20]`, `arr[:, 0]`)
  returns a **view** — no new buffer, shares memory. Fancy/boolean indexing and
  reshape-that-can't-be-a-view return **copies**. `arr.base is not None` ⇒ it's a
  view. Use `np.shares_memory(a, b)` to check.
- **Returns to OS?** Large arrays are `mmap`-backed, so freeing the last
  reference `munmap`s and **RSS drops** — unlike a million small Python objects
  (Chapter 4.9). This is a pleasant surprise: big NumPy frees *do* come back.
- **How to inspect.** `arr.nbytes`, `arr.base`, `np.shares_memory`,
  `arr.flags['OWNDATA']`.
- **Production issue.** `df.values`, `np.array(list_of_lists)`, and dtype
  upcasts (int8→int64 is 8×) blow up quietly. Watch **RSS**, not `getsizeof`.

```python
import numpy as np
a = np.ones(10_000_000, dtype=np.float64)   # 80 MB native buffer
print(a.nbytes)                              # 80000000
b = a[::2]                                    # VIEW: 0 new bytes
print(b.base is a)                            # True
c = a.astype(np.float32)                      # COPY: +40 MB
d = a[a > 0]                                  # COPY (boolean index): +80 MB
```

## 5.4 pandas

- **Where the memory lives.** A DataFrame stores columns in **blocks** —
  internally NumPy arrays grouped by dtype (the BlockManager). So pandas memory
  is NumPy memory plus overhead. `object` dtype columns (strings!) store an array
  of **pointers to Python `str` objects** — back to the fat-object problem.
- **The `object`-dtype trap.** A column of 10M short strings as `object` dtype
  can cost **10–20×** the same data as PyArrow-backed strings
  (`dtype="string[pyarrow]"`) or `category`. This is the #1 pandas memory sink.
- **Hidden copies.** Most operations return a new DataFrame; chained transforms
  hold several copies at once. `df.copy()`, `pd.concat`, `merge`, `.apply`,
  `groupby` materializations. `inplace=True` rarely saves memory (often still
  copies internally) — a common myth.
- **When it grows.** `read_csv` of a 2 GB file can peak at 5–10 GB (parsing
  buffers + type inference + the frame). Use `chunksize=`, `dtype=`,
  `usecols=`, and `engine="pyarrow"`.
- **Returns to OS?** The underlying NumPy/Arrow buffers `munmap` on free (good),
  but `object` columns leave millions of small Python strings → pymalloc
  retention (Chapter 4.9). Mixed outcome.
- **How to inspect.** `df.memory_usage(deep=True)` — **`deep=True` is essential**
  to count the actual string payloads, not just the pointer array;
  `df.info(memory_usage="deep")`.

```python
df.memory_usage(deep=True).sum()        # real bytes incl. python str payloads
df["col"] = df["col"].astype("category")  # or "string[pyarrow]" -> big savings
```

## 5.5 Pillow (PIL)

- **Where the memory lives.** A decoded image is a native raw pixel buffer:
  `width × height × channels × bytes_per_channel`. A 6000×4000 RGB image =
  6000·4000·3 = **72 MB** decoded, regardless of the 3 MB JPEG on disk.
- **When it grows (the OCR/thumbnail killer).** `.convert("RGB")`, `.resize()`,
  `.rotate()`, `.copy()` each allocate a fresh full buffer; a pipeline holding
  original + converted + resized has 3 live buffers. Batch a folder of large
  images and you OOM instantly.
- **Returns to OS?** These big buffers are malloc/mmap; freeing the `Image`
  object frees them. But you must **actually drop references** and often call
  `img.close()`; keeping originals in a list is a classic retention leak.
- **Production issue.** The **decompression bomb**: a tiny highly-compressed file
  that decodes to gigabytes (Pillow has `MAX_IMAGE_PIXELS` guard). And EXIF
  auto-rotate doubling buffers. See the OCR case study in Chapter 14.

## 5.6 OpenCV (cv2)

- **Where the memory lives.** A `cv2` image is a NumPy array backed by OpenCV's
  native `cv::Mat` buffer — heavy, contiguous, native. Same view/copy semantics
  as NumPy.
- **Native thread pools.** OpenCV (and NumPy/MKL/OpenBLAS) spin up internal
  thread pools; each thread reserves stack + scratch buffers. On a 64-core node
  this multiplies memory per process. Cap with `cv2.setNumThreads(n)`,
  `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS` — critical in
  containers where the library sees the *host's* core count, not your cgroup CPU
  limit (Chapter 7).
- **Production issue.** Video processing accumulates frames; `VideoCapture`
  buffers; and forgetting that each `cv2.resize`/`cvtColor` is a new buffer.

## 5.7 PyTorch / TensorFlow (and CUDA)

This is where native memory gets genuinely subtle because of the **GPU** and
**caching allocators**.

- **CPU tensors** are native buffers (like NumPy) — count toward RSS.
- **GPU tensors** live in **device (VRAM) memory**, which is **not** in your
  process RSS and **not** in the cgroup memory limit — it's governed by the GPU
  and `nvidia-smi`. A common confusion: "RSS is fine but I get CUDA OOM." Two
  entirely different pools.
- **The caching allocator (the big gotcha).** PyTorch does **not** return freed
  GPU memory to the driver — it keeps a private cache to avoid slow
  `cudaMalloc`/`cudaFree`. So after `del tensor`, `nvidia-smi` still shows the
  memory as used by your process. `torch.cuda.empty_cache()` returns *cached*
  (unused) blocks to the driver; it does **not** free live tensors. The same
  pattern (allocator caching, not leaking) that Chapter 4 described for CPython,
  now on the GPU.
- **Pinned (page-locked) host memory.** `pin_memory=True` DataLoaders and CUDA
  staging buffers allocate **non-swappable** host RAM that counts fully toward
  RSS/cgroup and can't be reclaimed under pressure.
- **DataLoader workers.** `num_workers=N` forks N processes; each may copy
  dataset structures (Chapter 6 copy-on-write) and needs `/dev/shm` for tensor
  passing — a top cause of `Bus error`/`/dev/shm` exhaustion (Chapter 9).
- **How to inspect.** `torch.cuda.memory_allocated()` (live tensors),
  `torch.cuda.memory_reserved()` (allocator's total cache),
  `torch.cuda.memory_summary()`, `nvidia-smi`. For CPU side: RSS + memray.
- **TensorFlow** by default **grabs almost all GPU memory up front**; set
  `TF_FORCE_GPU_ALLOW_GROWTH=true` / `set_memory_growth` or it looks like a
  massive "leak" that's actually pre-reservation.

```python
import torch
torch.cuda.memory_allocated() / 1e9     # GB currently held by live tensors
torch.cuda.memory_reserved()  / 1e9     # GB the caching allocator holds total
torch.cuda.empty_cache()                # return UNUSED cached blocks to driver
```

## 5.8 Apache Arrow / Parquet

- **Where the memory lives.** Arrow uses **off-heap**, columnar, often
  memory-mapped buffers managed by its own allocator (jemalloc/system). Reading a
  Parquet file with `mmap` makes the data **file-backed page cache** (Chapter 3)
  — reclaimable, cheap, shareable, but still counts against the cgroup while
  resident.
- **Why it's great for memory.** Zero-copy sharing between processes/libraries,
  no per-value Python objects, `pyarrow`-backed pandas strings avoid the
  object-dtype trap (§5.4).
- **Returns to OS?** mmap-backed → reclaimable; Arrow's allocator can also
  release. Better behaved than pandas `object` columns.
- **Inspect.** `pa.total_allocated_bytes()`, `pool.bytes_allocated()`.

## 5.9 `malloc` and the glibc allocator (the default)

Now the layer under all of the above. When a C library calls `malloc(n)`:

- **Small/medium `n`** → served from the **heap** (`brk`) or a per-thread
  **arena**. Freed memory goes onto glibc's **free lists** and is **kept, not
  returned** — so process RSS stays high after frees (this, plus pymalloc,
  explains most "RSS won't drop"). glibc creates up to `8 × CPU cores` arenas by
  default, each up to 64 MB — on a big host this alone can reserve **gigabytes**
  of address space (and touched RSS) per process.
- **Large `n` (≥ `M_MMAP_THRESHOLD`, default 128 KiB)** → a dedicated anonymous
  **`mmap`**, which **is** `munmap`'d on free → RSS **does** drop. This is why
  big buffers return memory but many small ones don't.
- **Fragmentation.** Long-running native workloads fragment glibc arenas exactly
  like pymalloc arenas.
- **`malloc_trim(0)`** asks glibc to return free heap tops to the OS — sometimes
  visibly lowers RSS. Tunables: `MALLOC_ARENA_MAX` (cap arenas — a very common
  container fix), `MALLOC_TRIM_THRESHOLD_`, `M_MMAP_THRESHOLD`.

```bash
# Cap glibc arenas to reduce per-process memory in containers (huge for many-core hosts)
export MALLOC_ARENA_MAX=2
# From Python, force glibc to return free memory:
python3 -c "import ctypes; ctypes.CDLL('libc.so.6').malloc_trim(0)"
```

## 5.10 jemalloc and tcmalloc — drop-in allocator swaps

Because glibc `malloc` fragments and hoards for many real workloads, production
Python services (especially data/ML) frequently **replace** it — no code change,
just `LD_PRELOAD`.

| Allocator | Origin | Strengths | Typical use |
|---|---|---|---|
| **glibc malloc** (ptmalloc2) | default | ubiquitous, fine for most | the default |
| **jemalloc** | FreeBSD/Facebook | low fragmentation, returns memory to OS well, great stats/profiling | long-running services, pandas/Arrow, Redis-like |
| **tcmalloc** | Google | fast thread-caching, good for high-concurrency alloc churn | high-QPS servers, TensorFlow |

- **Why swap.** Many teams see **20–40% RSS reduction** and flatter memory just
  by preloading jemalloc — it returns freed pages to the OS more aggressively and
  fragments less. It also has excellent **heap profiling** built in.
- **How.**

```dockerfile
# Dockerfile: preload jemalloc for the whole process
RUN apt-get update && apt-get install -y libjemalloc2
ENV LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so.2
# Optional: aggressive page return + profiling
ENV MALLOC_CONF=background_thread:true,dirty_decay_ms:1000,prof:true
```

- **Caveat.** Not a silver bullet — measure your workload. Some allocators trade
  RAM for CPU; jemalloc's `dirty_decay_ms`/`muzzy_decay_ms` tune the RSS-vs-CPU
  balance. tcmalloc needs `TCMALLOC_RELEASE_RATE` tuning to actually return
  memory.

## 5.11 Putting it together: diagnosing a "phantom" OOM

The signature: **RSS high & climbing, `tracemalloc` shows a small flat Python
heap.** Decision path:

```
   RSS high, tracemalloc flat?
        |
        +-- Is it a GPU OOM (nvidia-smi), not host RSS?  --> PyTorch/TF caching
        |     allocator; check memory_reserved(); empty_cache(); reduce batch.
        |
        +-- Native library buffers (numpy/cv2/PIL/pandas)?
        |     --> profile with MEMRAY (sees malloc/mmap). Look for hidden copies,
        |         object-dtype columns, un-closed images, retained arrays.
        |
        +-- Allocator hoarding/fragmentation (RSS >> live data)?
        |     --> set MALLOC_ARENA_MAX=2, try LD_PRELOAD jemalloc, malloc_trim.
        |
        +-- /dev/shm / DataLoader workers / pinned memory?
              --> Chapter 9 (shared memory) + reduce num_workers / shm size.
```

We run this exact playbook on real incidents in Chapters 13–14.

---

## Key takeaways

- **Most memory in ML/data/image workloads is native** — `malloc`/`mmap`
  buffers behind NumPy/pandas/Pillow/OpenCV/PyTorch — and lives **outside**
  CPython's allocator.
- **`tracemalloc` and `sys.getsizeof` are blind to it.** Use **RSS** (the OS
  truth) and **memray** (intercepts `malloc`) to see the whole process.
- **Hidden copies** (dtype casts, boolean indexing, pandas transforms, image
  conversions) are the usual growth cause; NumPy **views** share memory, fancy
  indexing **copies**.
- **GPU memory is a separate pool** (not RSS, not cgroup); PyTorch's **caching
  allocator** holds freed GPU memory until `empty_cache()`; TF grabs all VRAM
  unless you enable growth.
- **The glibc allocator hoards and fragments**; big `mmap`-backed buffers return
  to the OS, small heap allocations don't. **Cap `MALLOC_ARENA_MAX`** and/or
  **`LD_PRELOAD` jemalloc/tcmalloc** — a frequent, code-free production win.

## Practice exercises

1. Create `np.ones(50_000_000)`; compare `sys.getsizeof(a)`, `a.nbytes`, and the
   process RSS delta. Explain why two of them disagree wildly.
2. Take a slice and a boolean-indexed selection of a large array; use
   `np.shares_memory` and `.base` to prove one is a view and one is a copy.
   Watch RSS confirm it.
3. Load a DataFrame with a string column as `object` vs. `string[pyarrow]`;
   compare `df.memory_usage(deep=True)`. Quantify the multiple.
4. Run any allocation-heavy script normally, then again with
   `LD_PRELOAD=.../libjemalloc.so.2` and `MALLOC_ARENA_MAX=2`. Compare peak RSS.

## Quiz questions

1. Why does `tracemalloc` report a flat heap while RSS grows for a NumPy-heavy
   job? Which tool would you use instead and why?
2. `sys.getsizeof(big_ndarray)` returns ~112. Where are the 800 MB?
3. Slicing vs. boolean indexing a NumPy array: which shares memory, which
   copies? How do you verify?
4. After `del gpu_tensor`, `nvidia-smi` still shows the memory used. Is it a
   leak? What actually returns it, and what does it *not* free?
5. Why can a 3 MB JPEG cause a 200 MB RSS spike?
6. Name two ways to reduce RSS of a long-running native workload **without
   changing application code**.
7. Why is capping `MALLOC_ARENA_MAX` especially important inside a container on
   a 64-core host?

## Suggested experiments

- Profile a NumPy/pandas script with **memray** (see
  [`../03_memory_profiling/08_memray_demo.md`](../03_memory_profiling/08_memray_demo.md))
  and confirm it attributes bytes to native `malloc` sites that `tracemalloc`
  (`../03_memory_profiling/02_tracemalloc_basics.py`) never showed.
- Set `MALLOC_ARENA_MAX=1` vs unset on a multi-threaded allocation loop and
  compare `VmRSS` and the number of `rw-p` anonymous mappings in
  `/proc/$PID/maps` (arenas!).
- In PyTorch, allocate and `del` several large tensors and watch
  `torch.cuda.memory_allocated()` vs `memory_reserved()` diverge; then call
  `empty_cache()` and watch `reserved` drop but `allocated` stay.

---

*Next up: **Chapter 6 — Linux Memory Internals**, where we go under the
allocators to the kernel: demand paging, page tables, minor vs. major page
faults, the TLB, huge pages/THP, NUMA, copy-on-write `fork()`, overcommit, and
exactly how the **OOM killer** decides which process dies.*

[← Chapter 4](04_python_memory.md) · [Back to index](README.md) · [Chapter 6 →](06_linux_memory_internals.md)
