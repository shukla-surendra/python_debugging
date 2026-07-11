<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 2 — Linux Process Memory

In Chapter 1 we said "everything is an `mmap`." Now we name every region of a
running process, learn to read it out of `/proc`, and watch a real Python
interpreter build its address space from scratch. By the end you'll be able to
point at any line of `/proc/<pid>/maps` and say what it is and whether it costs
you RAM.

> **This repo is your lab.** Everything below can be run against the "victim"
> programs in [`../../workloads/`](../../workloads/) and the runnable demos in
> [`../03_memory_profiling/`](../03_memory_profiling/). See
> [§2.9 Aligning with this repo](#29-aligning-with-this-repo-docs--make-commands)
> for the exact `make` and `python` commands. Render this whole handbook to a
> browsable site with `make docs` (serves at http://localhost:8000).

## 2.1 The big picture: a process's address space, top to bottom

When the kernel `exec()`s a program, it lays out the new process's *user-space*
virtual address space into well-defined **segments**. Here is the canonical
layout on 64-bit Linux (high addresses on top):

```
  HIGH ADDRESSES (0x00007FFF_FFFFFFFF, top of user space)
  +-------------------------------------------------------+
  |  [stack]                                              |  <- grows DOWNWARD
  |  local variables, call frames, return addresses       |     as calls nest
  |     |                                                 |
  |     v      (guard gap)                                |
  |                                                       |
  |                    ... unused address space ...       |
  |                                                       |
  |     ^      (mmap region grows down toward heap)       |
  |     |                                                 |
  |  [mmap area]                                          |  <- shared libs,
  |  libc.so, libssl.so, python .so C-extensions,         |     mmap'd files,
  |  big malloc/NumPy anonymous mmaps, thread stacks      |     large allocs
  |                                                       |
  |     ^                                                 |
  |     |      (heap grows UPWARD via brk/sbrk)           |
  |  [heap]                                               |  <- small malloc,
  |  small allocations, pymalloc arenas (Ch 4)            |     pymalloc arenas
  +-------------------------------------------------------+
  |  .bss    - zero-initialized globals (no disk cost)    |
  +-------------------------------------------------------+
  |  .data   - initialized globals (from the binary)      |
  +-------------------------------------------------------+
  |  .rodata - read-only constants, string literals       |
  +-------------------------------------------------------+
  |  .text   - machine code (read-only, executable)       |  <- the program
  +-------------------------------------------------------+
  LOW ADDRESSES (starts above 0x0; 0x0 is left unmapped so
  that dereferencing NULL segfaults instead of corrupting data)
```

Two things to internalize immediately:

1. **The heap grows up; the stack grows down.** They grow toward each other
   through a vast empty middle. On 64-bit machines they will essentially never
   collide (the gap is terabytes), but the *directions* explain a lot of
   behavior (e.g. why deep recursion overflows the stack, Chapter 4).
2. **The bottom segments come straight from the executable file** (text, rodata,
   data); the middle/top are created and grown at runtime (bss, heap, mmap,
   stack).

## 2.2 The `.text` segment (code)

- **What it is.** The compiled machine code of the program. For a Python app,
  this is the code of the `python3` interpreter binary and every C-extension
  `.so`, **not** your `.py` files (those become Python objects on the heap —
  see §2.10).
- **Why it exists.** The CPU executes instructions; they have to live in
  addressable memory.
- **Where it lives.** Mapped **file-backed, read-only, executable** (`r-xp`)
  directly from the binary on disk.
- **When it grows / shrinks.** It doesn't. It's a fixed-size, read-only mapping
  for the life of the process.
- **Returns to OS?** Under memory pressure the kernel can **drop** these clean
  pages for free (they're safe on disk) and re-fault them later — so text
  effectively "costs nothing" when idle and reloads on demand.
- **How to inspect.** In `/proc/<pid>/maps`, look for `r-xp` lines with the
  binary/`.so` path.
- **Misconception.** "My 2000-line Python program has a big code segment." No —
  your Python source is data on the heap; `.text` is the *interpreter's* C code
  and is **shared** across every Python process on the node.

## 2.3 `.rodata` and `.data` (initialized data)

- **`.rodata`** — read-only data: string literals, `const` tables, jump tables.
  Mapped `r--p`, file-backed, shareable.
- **`.data`** — global/static variables that have a non-zero initial value
  (e.g. `int counter = 42;` in C). Mapped `rw-p`, **copy-on-write** from the
  file: shared until first written, then a private copy is made (Chapter 6).
- **Grows/shrinks?** Fixed size — the set of globals is known at compile time.
- **Production relevance.** Usually small for the interpreter; irrelevant to
  your app's memory growth. Don't spend time here when hunting a leak.

## 2.4 `.bss` (zero-initialized data)

- **What it is.** Global/static variables that start at **zero** (e.g.
  `static char buffer[1<<20];` or `int flags;`).
- **Why it exists / clever trick.** Storing a million zero bytes in the
  executable file would be wasteful. Instead the binary just records "reserve
  N bytes, all zero." At load time the kernel maps an **anonymous zero-filled**
  region — **no disk space, no file read**.
- **Where it lives.** Anonymous, zero-filled, demand-paged. A page of `.bss`
  costs zero physical RAM until you actually touch it (demand paging, Ch 6).
- **Misconception.** "BSS bloats my binary." The opposite — BSS is the trick
  that keeps binaries small. `size ./python3` shows text/data/bss sizes.

```bash
$ size $(readlink -f $(command -v python3))
   text    data     bss     dec     hex filename
2451930   52104   30112 2534146  26aec2 .../python3.14
```

## 2.5 The heap (`brk`/`sbrk`)

- **What it is.** A contiguous region for dynamic allocation that grows/shrinks
  by moving a single pointer called the **program break**. `malloc()` for
  *small* objects carves memory out of here.
- **Why it exists.** Programs need to allocate memory whose size isn't known at
  compile time.
- **Where it lives.** Anonymous, private (`rw-p`, shown as `[heap]` in maps).
- **When it grows.** When the allocator needs more small-object space it calls
  `brk()`/`sbrk()` to push the break up.
- **When it shrinks / returns to OS.** *Rarely.* The break only moves back down
  if the **top** of the heap is free. If you free an object in the middle, the
  hole stays mapped. **This is a primary reason RSS stays high after you free
  Python objects** (Chapters 4 & 11).
- **How to inspect.** The `[heap]` line in `/proc/<pid>/maps`; `pmap -x <pid>`.
- **Python note.** CPython's small-object allocator (`pymalloc`, Chapter 4) and
  glibc's `malloc` (Chapter 5) both build on the heap and on anonymous `mmap`.
  Large allocations (≥128 KiB by default in glibc) skip the heap and use a
  fresh anonymous `mmap` instead — which *can* be returned to the OS on free.

## 2.6 The stack

- **What it is.** Per-thread scratch space holding **call frames**: local
  variables, function arguments, return addresses, saved registers.
- **Why it exists.** Function calls nest; each needs private storage that is
  automatically reclaimed on return. A stack (LIFO) is the perfect structure.
- **Where it lives.** Anonymous, private (`[stack]` for the main thread; thread
  stacks are separate anonymous `mmap`s in the mmap area).
- **When it grows / shrinks.** Grows **downward** automatically as calls nest;
  shrinks as they return. Bounded by `ulimit -s` (default **8 MiB** on Linux).
- **Returns to OS?** The mapping stays reserved; touched pages may be reclaimed,
  but you don't manage this.
- **Common production issue.** **Deep/unbounded recursion** overflows the stack.
  In Python you usually hit `RecursionError` first (the interpreter's
  `sys.setrecursionlimit` guard, default ~1000). But raise that limit and you
  can crash the interpreter with a real **segfault** by exhausting the C stack —
  see [`../../workloads/recursion_blowup.py`](../../workloads/recursion_blowup.py).
- **Threads matter for memory.** Each thread gets its **own** stack (default
  8 MiB of *virtual* reservation). 500 threads ≈ 4 GiB of VSZ (virtual!), but
  only touched pages become RSS. This inflates **VSZ** dramatically while RSS
  stays modest — a classic "why is VSZ 20 GB?!" confusion resolved in Chapter 3.

```bash
$ ulimit -s          # default thread stack size in KiB
8192
$ python3 -c "import threading; print(threading.stack_size())"  # 0 = OS default
0
```

## 2.7 Shared libraries

- **What it is.** Reusable code (`libc.so`, `libssl.so`, `libcrypto.so`, plus
  every compiled Python C-extension like `numpy`'s `_multiarray_umath.so`) that
  many processes share.
- **Why it exists.** Loading one physical copy of libc and mapping it into every
  process saves enormous RAM and disk, and lets you patch a library once.
- **Where it lives.** In the mmap area. Each `.so` produces **multiple**
  mappings: `r--p` (headers/rodata), `r-xp` (code), `rw-p` (its writable
  globals, copy-on-write).
- **The shared part is the point.** The `r-xp`/`r--p` pages are **shared**
  physical frames across all processes using that library. This is exactly why
  **RSS over-counts** (it charges each process the *full* size of shared libs)
  and why **PSS** exists (it divides shared pages by the number of sharers) —
  Chapter 3.
- **Production issue.** A container image with dozens of heavy libs
  (OpenCV, CUDA, MKL) can map **hundreds of MB** of `.so` files. Across 30 pods
  on a node, PSS ≪ sum(RSS). Capacity-plan with PSS, not RSS.

## 2.8 Memory-mapped files

- **What it is.** A file whose bytes are mapped directly into the address space
  with `mmap()`, so reading the memory reads the file (paged in on demand) and
  writing the memory (if `MAP_SHARED`) writes the file.
- **Why it exists.** Zero-copy access to large files; let the kernel page in
  only the parts you touch; share a file between processes.
- **Where it lives.** File-backed mappings in the mmap area. In Python:
  `mmap.mmap(...)`, `numpy.load(..., mmap_mode="r")`, Arrow/Parquet memory
  maps, and databases (SQLite, RocksDB) all do this.
- **When it grows.** As you touch more of the file, more pages fault in (as
  **page cache**, Chapter 3) and appear in RSS.
- **Returns to OS?** **Clean** mapped file pages are reclaimed for free under
  pressure; **dirty** ones (you wrote to a `MAP_SHARED` mapping) are written
  back first.
- **Production issue.** `mmap`ing a 10 GB model file makes RSS *look* huge as
  you scan it, but it's reclaimable page cache — **yet in a cgroup it still
  counts toward the memory limit and can get you OOM-killed** (Chapters 7–8).
  This surprises a *lot* of ML engineers.

## 2.9 Aligning with this repo: docs & `make` commands

This handbook is part of the **Python Debugging Dojo**. The commands below are
the real ones in this repository — run them as you read.

```bash
# --- Build & read the docs (this whole guide included) ---
make docs      # render every .md (incl. this guide) to docs_html/ and
               # serve at http://localhost:8000
make check     # validate all relative markdown links, then build (CI-friendly,
               # no serve). Run this after editing any doc.

# --- The "victim" programs used throughout Chapters 2, 4, 11, 14 ---
python workloads/memory_leak.py        # unbounded cache + ref cycle + closure
python workloads/recursion_blowup.py   # exhausts the stack (see §2.6)
python workloads/cpu_bound.py          # tight loops (CPU, not memory)

# --- Runnable memory-profiling demos (Chapter 12 covers each in depth) ---
python docs/03_memory_profiling/01_sys_getsizeof.py         # per-object sizes
python docs/03_memory_profiling/02_tracemalloc_basics.py    # tracemalloc intro
python docs/03_memory_profiling/03_tracemalloc_snapshot_diff.py  # find growth
python docs/03_memory_profiling/04_memory_profiler_demo.py  # line-by-line RSS
python docs/03_memory_profiling/05_objgraph_demo.py         # reference graphs
python docs/03_memory_profiling/06_pympler_demo.py          # heap summaries
python docs/03_memory_profiling/07_gc_module_demo.py        # gc introspection
# 08_memray_demo.md — a walkthrough doc (memray records native + Python allocs)
```

Read the section overviews any time:
[`../03_memory_profiling/README.md`](../03_memory_profiling/README.md)
(memory) and, for production/Kubernetes,
[`../05_production_playbook/04_kubernetes_debugging.md`](../05_production_playbook/04_kubernetes_debugging.md)
— we build directly on the latter in Chapters 8, 13, and 18.

> **Where does *this* guide live in the docs?** `scripts/build_docs.py` renders
> every `.md` in the repo, so each chapter of this guide (under
> `docs/07_memory_management_guide/`) is automatically included in `make docs`
> output and linked from `docs_html/index.html`. Keep relative links valid so
> `make check` stays green.

## 2.10 What actually happens when a Python process starts

Let's trace it, because it demystifies half the lines in `/proc/<pid>/maps`.

```
  $ python3 my_app.py
        |
        | 1. Shell fork()s, then execve("/usr/bin/python3", ...)
        v
  +-----------------------------------------------------------+
  | Kernel builds a fresh address space for the interpreter:  |
  |   - maps python3 binary:  .text (r-xp), .rodata (r--p),   |
  |     .data (rw-p COW), reserves .bss (anon zero)           |
  |   - maps the dynamic loader ld-linux-x86-64.so            |
  +-----------------------------------------------------------+
        |
        | 2. ld.so runs: resolves & mmaps shared libraries
        v
  +-----------------------------------------------------------+
  |   libc.so, libpthread, libssl, libz, ... each mapped      |
  |   (r--p / r-xp shared, rw-p COW). This is why an idle     |
  |   interpreter already has ~50-200 mappings.               |
  +-----------------------------------------------------------+
        |
        | 3. CPython runtime initializes
        v
  +-----------------------------------------------------------+
  |   - creates the heap; pymalloc requests its first arenas  |
  |     (256 KiB anonymous mmaps, Chapter 4)                  |
  |   - builds built-in types, interned strings, sys.modules  |
  |   - imports site.py, encodings, etc. -> heap objects      |
  +-----------------------------------------------------------+
        |
        | 4. Your code runs
        v
  +-----------------------------------------------------------+
  |   - `import numpy` mmaps numpy's C-extension .so files    |
  |     AND allocates native buffers (Chapter 5)              |
  |   - your .py source is compiled to bytecode -> code       |
  |     objects, function objects, dicts: all HEAP objects    |
  |   - every list/dict/str you build: heap (pymalloc/malloc) |
  +-----------------------------------------------------------+
```

**Baseline cost.** A bare `python3 -c "input()"` typically shows ~10–15 MiB
RSS on a modern Linux — almost all of it interpreter code + libraries + the
initial import machinery, much of it **shared** (so PSS is lower). `import
numpy; import pandas` can push baseline to 80–150 MiB before you've done any
real work. Know your baseline before blaming your code.

**See it live:**

```bash
# Terminal 1: start an idle interpreter and keep it alive
python3 -c "input()"      # blocks; leave it running

# Terminal 2: inspect it
PID=$(pgrep -f 'input()')
grep -E 'VmRSS|VmSize|VmData|VmStk|VmExe|VmLib' /proc/$PID/status
#   VmSize = VSZ (total virtual), VmRSS = resident, VmExe = text,
#   VmLib  = shared libs,        VmStk = stack,    VmData = heap+data

pmap -x $PID | tail -1     # total RSS/dirty summary
wc -l < /proc/$PID/maps    # how many mappings a "small" process really has
```

Then, in Terminal 1, press Enter to let it exit.

## 2.11 Reading `/proc/<pid>/maps` like a pro

Every line is one mapping. Anatomy:

```
7f3c2a028000-7f3c2a1b0000 r-xp 00028000 08:01 2201  /usr/lib/libc.so.6
|__________ _____________| |__| |______| |___| |__|  |________________|
   address range           perms offset  dev   inode  pathname
                           r-xp                        (blank = anonymous)
```

- **perms**: `r`ead `w`rite e`x`ecute, and `p`rivate (COW) vs `s`hared.
- Quick classification:
  - `r-xp` + path → **code** (text of binary or `.so`), shared, reclaimable.
  - `r--p` + path → **rodata / file-backed read-only**, shared, reclaimable.
  - `rw-p` + path → library/globals **data** (COW) or a writable file mapping.
  - `rw-p` + **no path** (`00:00 0`) → **anonymous** = your data / heap / stack.
  - Named `[heap]`, `[stack]`, `[vdso]`, `[vvar]` → special kernel regions.

For per-mapping RSS/PSS/dirty accounting, read
`/proc/<pid>/smaps` (or the aggregated `/proc/<pid>/smaps_rollup`) — this is the
ground truth behind `smem` and Chapter 3's metrics:

```bash
grep -E '^(Rss|Pss|Shared|Private|Anonymous|Swap):' /proc/$PID/smaps_rollup
```

## 2.12 Segment → property cheat table

| Segment | Backing | Shared? | Grows | Shrinks / returns to OS | Your app's data? |
|---|---|---|---|---|---|
| `.text` | file (binary/.so) | Yes (r-x) | No | Dropped for free | No (interpreter) |
| `.rodata` | file | Yes (r--) | No | Dropped for free | No |
| `.data` | file (COW) | Until written | No | No | No |
| `.bss` | anon zero | No | No | No | Rarely |
| heap `[heap]` | anon | No | Up via `brk` | Rarely (only from top) | **Yes** |
| large mmap | anon | No | Per alloc | **Yes**, freed on `munmap` | **Yes** |
| stack `[stack]` | anon | No | Down on calls | Auto | Locals only |
| shared libs | file (.so) | **Yes** | No | Dropped for free | No |
| mmap'd file | file | Optional | As touched | Clean dropped free | Depends |

Keep this table in your head: **the only rows that explain a growing,
non-returning process are the heap and (native) anonymous mmaps** — everything
else is either fixed or reclaimable. That narrows every investigation.

---

## Key takeaways

- A process's user address space is a stack of well-defined segments: `.text`,
  `.rodata`, `.data`, `.bss` (from the file), then heap (grows up), mmap area,
  and stack (grows down).
- **Your Python source and objects are heap data**, not `.text`. `.text` is the
  interpreter's C code, shared across all Python processes.
- The **heap rarely returns memory to the OS** (only from its top); **large
  anonymous mmaps do** (freed on `munmap`). This dichotomy explains most "RSS
  won't drop" mysteries.
- Shared libraries are **shared, read-only, reclaimable** — they inflate RSS
  but barely cost per-process (PSS, Chapter 3).
- `/proc/<pid>/maps` + `smaps_rollup` let you classify every byte; `pmap`,
  `size`, and `/proc/<pid>/status` are your first-look tools.
- Align your practice with the repo: `make docs`, `make check`, the
  `workloads/` victims, and `docs/03_memory_profiling/` demos.

## Practice exercises

1. Start `python3 -c "input()"`, find its PID, and run
   `grep -E 'VmRSS|VmSize|VmExe|VmLib|VmStk|VmData' /proc/$PID/status`. Record
   each value and label which segment it corresponds to.
2. In `/proc/$PID/maps`, find and classify: one `r-xp` code mapping, one `rw-p`
   anonymous mapping, the `[heap]`, and the `[stack]`.
3. Run `size $(readlink -f $(command -v python3))` and explain why `bss` costs
   no disk space.
4. Run `make check` after adding a link somewhere in a doc; confirm it validates
   relative links.

## Quiz questions

1. Which direction does the heap grow? The stack? Why does it matter for
   recursion?
2. Why does `.bss` not increase the size of the executable file on disk?
3. You `free()` an object in the middle of the heap. Does RSS drop? Why or why
   not?
4. Why is a 200 MB shared-library footprint *not* 200 MB of cost per process on
   a 30-pod node?
5. You `mmap` a 10 GB file read-only and scan it. Is that memory reclaimable?
   Does it still risk an OOM kill inside a cgroup? (Foreshadow Ch 7–8.)
6. Where does your `my_app.py` **source code** live once the process is
   running — `.text` or the heap?

## Suggested experiments

- Run [`../../workloads/memory_leak.py`](../../workloads/memory_leak.py) under
  `/usr/bin/time -v python workloads/memory_leak.py` and note "Maximum resident
  set size". Then run `docs/03_memory_profiling/03_tracemalloc_snapshot_diff.py`
  to see *which lines* grow — connect the RSS number to the source lines.
- Start an interpreter, snapshot `wc -l /proc/$PID/maps`, then `import numpy`
  in it (use `python3 -c "import numpy; input()"`) and snapshot again. How many
  new mappings did numpy's `.so` files and buffers add?
- Raise the recursion limit and run
  [`../../workloads/recursion_blowup.py`](../../workloads/recursion_blowup.py) to
  feel the difference between Python's `RecursionError` guard and a real C-stack
  segfault (§2.6). Do this in a throwaway shell.

---

*Next up: **[Chapter 3 — Memory Metrics](03_memory_metrics.md)**, where we
finally pin down RSS, PSS, USS, VSZ, working set, page cache, and exactly which
numbers Kubernetes uses to decide whether to kill your pod.*

[← Chapter 1](01_introduction.md) · [Back to index](README.md) · [Chapter 3 →](03_memory_metrics.md)
