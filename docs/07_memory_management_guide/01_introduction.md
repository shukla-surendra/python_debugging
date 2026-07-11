<!-- Part of the Memory Management Guide. Index: ./README.md -->

# Chapter 1 — Introduction — What Memory Actually Is

Before you can debug memory, you need a physical and mental model of what
memory *is*. Most memory bugs come from a wrong mental model: engineers think
`del x` frees RAM, that RSS is "how much my program uses," or that a container
"has" 2 GB. All three are subtly wrong, and this chapter plants the seeds for
why.

## 1.1 What is memory?

**What it is.** Memory is a large array of numbered boxes, each holding one
**byte** (8 bits). Each box has an **address** — an integer name — starting at
0 and counting up. That's it. RAM is not "smart"; it is a giant addressable
array that the CPU reads from and writes to billions of times per second.

```
Physical RAM as a numbered array of bytes:

 address:   0        1        2        3        4        5     ...
          +--------+--------+--------+--------+--------+--------+
 value:   |  0x48  |  0x65  |  0x6C  |  0x6C  |  0x6F  |  0x00  | ...
          +--------+--------+--------+--------+--------+--------+
              'H'      'e'      'l'      'l'      'o'     NUL
```

**Why it exists.** The CPU can only compute on data that is *close* to it. It
cannot do arithmetic on data sitting on a disk. RAM is the "working desk" of
the computer: fast, volatile (wiped on power loss), and directly addressable
by the CPU. Disk is the "filing cabinet": slower, persistent, not directly
addressable.

**The memory hierarchy** (why RAM even matters) — each level is ~10–100× faster
and ~10× smaller/more expensive than the one below it:

```
        FASTER, SMALLER, MORE EXPENSIVE
   ^   +-------------------------------+   ~1 ns,   ~KB
   |   |  CPU registers                |
   |   +-------------------------------+   ~1-4 ns, ~KB-MB
   |   |  L1 / L2 / L3 CPU cache       |
   |   +-------------------------------+   ~100 ns,  GBs   <-- "memory" = this
   |   |  Main memory (RAM / DRAM)     |                       (what this book
   |   +-------------------------------+   ~100 us,  TBs        is about)
   |   |  SSD / NVMe                   |
   |   +-------------------------------+   ~10 ms,   TBs
   v   |  Spinning disk (HDD)          |
       +-------------------------------+
        SLOWER, LARGER, CHEAPER
```

**Common misconception.** "Memory" and "storage" are used interchangeably in
everyday speech ("my phone has 128 GB of memory"). In systems engineering they
are strictly different: **memory = RAM = volatile working set**; **storage =
disk = persistent files**. This book is about RAM, though we'll see that the
kernel blurs the line with the *page cache* (Chapter 3) and swap (Chapter 6).

## 1.2 RAM vs. Physical Memory

These are effectively synonyms in this book. **Physical memory** is the actual
DRAM chips installed on the machine — a fixed, finite resource. If a node has
`64 GiB` of RAM, there are `64 * 1024^3` physical byte-boxes, period. When we
say "the machine is out of memory," we mean these physical boxes are all
spoken for.

> **Units matter and cause real incidents.** `GB` (gigabyte) = 10^9 bytes.
> `GiB` (gibibyte) = 2^30 = 1,073,741,824 bytes. Kubernetes uses the binary
> units: `Gi`, `Mi`, `Ki`. A limit of `1000M` is **not** `1Gi` — it's about
> 4.6% smaller. Mixing them is a classic cause of "why did it OOM at 954 MB
> when I set the limit to 1 GB?"

## 1.3 The problem physical memory alone can't solve

Imagine you write a program and it uses raw physical addresses directly. Three
disasters immediately follow:

1. **No isolation.** Program A writes to address `4096`. Program B also uses
   address `4096`. They corrupt each other. One buggy program crashes the
   whole machine.
2. **No relocation.** A program compiled to live at address `0x400000` can only
   run if that exact region is free. You couldn't run two copies.
3. **No overcommit.** The sum of all programs' needs can't exceed installed
   RAM, ever — even if most of that memory is never actually touched.

The fix, used by every modern OS, is **virtual memory**.

## 1.4 Virtual Memory — the central idea

**What it is.** Every process gets its own private, enormous, imaginary array
of addresses called its **virtual address space**. On 64-bit Linux this space
is 128 TiB per process (`0x0` up to `0x00007FFF_FFFFFFFF` for user space). The
process *believes* it owns a huge contiguous block of memory starting at low
addresses.

**Why it exists.** It solves all three disasters at once:

- **Isolation:** Process A's virtual address `0x1000` and Process B's virtual
  address `0x1000` map to *different* physical boxes (or to none at all). They
  cannot see each other. This is enforced by hardware.
- **Relocation:** Every program can be compiled to "start at the same place"
  because those are virtual addresses; the OS maps them wherever physical RAM
  is free.
- **Overcommit:** A virtual address only consumes physical RAM once you
  actually *write* to it. You can reserve 100 GB of virtual space on a 4 GB
  machine as long as you only touch a little of it (more in Chapters 3 & 6).

**Where it lives.** The mapping from virtual → physical is stored in **page
tables**, maintained by the kernel and consulted by a piece of CPU hardware
called the **MMU (Memory Management Unit)** on every single memory access.

```
  Process A's view                Physical RAM              Process B's view
  (virtual)                       (real chips)              (virtual)

  0x0000 ---------\                                    /-------- 0x0000
  0x1000 -----\    \        +-------------------+     /    /---- 0x1000
  0x2000 --\   \    \-----> | frame 17 (A.1000) | <--/    /
            \   \           +-------------------+        /
             \   \--------> | frame 4  (A.2000) |       /
              \             +-------------------+      /
               \            | frame 88 (B.1000) | <---/
                \---------> | frame 23 (A.0000) |
                            +-------------------+
                            | ... free frames   |
                            +-------------------+

  Same virtual address in A and B -> different physical frames.
  The MMU + page tables perform this translation on every access.
```

**Key takeaway:** *Virtual addresses are what your program uses. Physical
frames are what actually cost you money. The whole art of memory debugging is
figuring out how many virtual addresses have been "backed" by real physical
frames — and why they aren't being un-backed.*

## 1.5 Address space

**What it is.** The set of all valid virtual addresses a process can use. On
64-bit Linux it is split:

```
  0xFFFFFFFFFFFFFFFF  +--------------------------+
                      |     KERNEL SPACE         |  (shared, protected;
                      |  (page tables, kernel    |   user code cannot
                      |   code, driver buffers)  |   read/write this)
  0xFFFF800000000000  +--------------------------+
                      |                          |
                      |   "non-canonical" gap    |  (huge unused hole)
                      |                          |
  0x00007FFFFFFFFFFF  +--------------------------+
                      |     USER SPACE           |  (your program:
                      |  (code, heap, stack,     |   heap, stack, libs,
                      |   libraries, mmaps)      |   mmap'd files)
  0x0000000000000000  +--------------------------+
```

Only a tiny fraction of this 128 TiB is ever mapped to anything. We dissect the
user-space layout in detail in **Chapter 2**.

**Common misconception.** "A 64-bit process can use 16 exabytes of RAM." No —
the *address space* is huge, but the amount actually **backed by physical
frames** is limited by your RAM + swap. Address space is free; physical frames
are not.

## 1.6 Why operating systems use virtual memory (recap of the payoff)

| Feature | Without virtual memory | With virtual memory |
|---|---|---|
| Process isolation | None — one bug crashes all | Hardware-enforced |
| Running multiple programs | Fragile, manual address juggling | Trivial |
| Using more than physical RAM | Impossible | Possible via swap + overcommit |
| Sharing code (libc) between processes | Hard | One physical copy, mapped into many |
| Memory-mapping a file | Awkward | `mmap()` — file *is* address space |
| Copy-on-write `fork()` | Impossible | Cheap (Chapter 6) |

Virtual memory is arguably the single most important abstraction in operating
systems. Nearly every topic in this book — RSS vs. PSS, shared libraries, the
OOM killer, `fork()` in Gunicorn, page cache — is a direct consequence of it.

## 1.7 Memory pages — the unit of everything

**What it is.** The kernel does **not** manage memory one byte at a time (that
would need a mapping entry per byte — absurd). Instead it manages memory in
fixed-size chunks called **pages**. Both virtual and physical memory are
divided into pages of the same size.

- A **page** = a chunk of *virtual* address space.
- A **page frame** (or just "frame") = a chunk of *physical* RAM the same size.
- The page table maps pages → frames.

```
  Virtual pages (of one process)      Physical page frames (whole machine)
  +------+------+------+------+        +------+------+------+------+------+
  | VP0  | VP1  | VP2  | VP3  |        | PF0  | PF1  | PF2  | PF3  | PF4  |
  +--+---+--+---+--+---+--+---+        +---+--+------+--+---+---+--+------+
     |      |      |      |                |             |       |
     |      |      +------|----------------+             |       |
     |      +-------------|------------------------------+       |
     +--------------------+--------------------------------------+
  (VP3 is unmapped -> touching it causes a page fault, Chapter 6)
```

**Why it exists.** Pages are a compromise: small enough to not waste much RAM
per allocation, large enough that the page table stays a manageable size and
the CPU's translation cache (the **TLB**, Chapter 6) is effective.

## 1.8 Page size

**What it is.** The default page size on x86-64 and ARM64 Linux is **4 KiB
(4096 bytes)**. This is the granularity of almost everything:

- Physical RAM is handed out in 4 KiB frames.
- `mmap()` allocations are rounded up to a multiple of 4 KiB.
- A single-byte write into a fresh region faults in a whole 4 KiB frame.
- RSS (Chapter 3) is always a multiple of 4 KiB.

Check it yourself:

```bash
$ getconf PAGE_SIZE
4096
$ python3 -c "import resource; print(resource.getpagesize())"
4096
```

**Huge pages.** Linux also supports **2 MiB** and **1 GiB** pages ("huge
pages"), used to reduce TLB pressure for big workloads (databases, ML). We
cover these and **Transparent Huge Pages (THP)** in Chapter 6 — THP in
particular is a frequent, surprising cause of RSS bloat in containers.

**Production consequence.** Because 4 KiB is the minimum, allocating one
million tiny 16-byte Python objects does **not** cost 16 MB of fresh frames in
a simple way — CPython packs them into pages via `pymalloc` (Chapter 4). And
freeing one object rarely frees a whole page, which is why RSS doesn't drop
(Chapter 4.9).

## 1.9 Memory mapping (`mmap`)

**What it is.** `mmap()` is the fundamental syscall that connects a region of a
process's virtual address space to *something*. That "something" is either:

- **a file** ("file-backed" mapping), or
- **nothing / zero-fill** ("anonymous" mapping).

Every meaningful chunk of a process's memory is ultimately an `mmap`. Even the
heap and the loading of shared libraries are built on it.

```
  Virtual address space                Backing store
  +---------------------+
  | mmap of libc.so.6   | -----------> /usr/lib/libc.so.6   (file-backed,
  +---------------------+                                     read-only, shared)
  | mmap of model.bin   | -----------> /data/model.bin       (file-backed)
  +---------------------+
  | anonymous mmap      | -----------> (zero-filled RAM,      (anonymous,
  | (big malloc/NumPy)  |               nothing on disk)       private)
  +---------------------+
```

You can literally see these mappings for any process — this is one of the most
important debugging skills in the book:

```bash
$ cat /proc/self/maps | head
555a1c000000-555a1c021000 r--p 00000000 08:01 1311 /usr/bin/python3.14
555a1c021000-555a1c2b0000 r-xp 00021000 08:01 1311 /usr/bin/python3.14
...
7f3c2a000000-7f3c2a028000 r--p 00000000 08:01 2201 /usr/lib/libc.so.6
7f3c2a028000-7f3c2a1b0000 r-xp 00028000 08:01 2201 /usr/lib/libc.so.6
...
7f3c2c000000-7f3c2c400000 rw-p 00000000 00:00 0     [anonymous]
7ffd1e3a0000-7ffd1e3c1000 rw-p 00000000 00:00 0     [stack]
```

We read this file line-by-line in Chapter 2. For now, notice: files have a
path; anonymous regions show `00:00 0` and no path.

## 1.10 Anonymous memory

**What it is.** Memory that is **not backed by any file** — just zero-filled
RAM that belongs to the process. This is where your program's *actual data*
lives: every Python object, every NumPy array, every string, the heap, the
stack.

- **Why it exists.** Programs need scratch space to compute with that has no
  meaning on disk.
- **Where it lives.** Anonymous pages live in RAM; under memory pressure they
  can be pushed to **swap** (Chapter 6), which is the *only* backing store they
  have.
- **When it grows.** Every allocation your program actually writes to.
- **When it shrinks.** When freed *and* the allocator returns pages to the OS
  (often it doesn't — Chapters 4 & 5).
- **Returns to OS?** Sometimes. This is the crux of "why doesn't my RSS go
  down."
- **Counts toward pod memory?** **Yes, heavily** — anonymous memory is the
  main thing that gets you `OOMKilled` (Chapter 8).

**This is the memory you care about most.** When a pod is killed for using too
much memory, it is almost always anonymous memory that grew and didn't come
back.

## 1.11 File-backed memory

**What it is.** Memory whose contents mirror a file on disk. Two big
categories:

1. **Executable/library code** — when you run `python3`, the interpreter binary
   and every `.so` it loads are `mmap`ed file-backed and **read-only**. Because
   they're read-only and identical, the kernel keeps **one physical copy** and
   maps it into every Python process on the node (this is why 50 Python pods
   don't each pay full price for libc — see PSS in Chapter 3).
2. **Data files you `mmap`** — e.g. a memory-mapped model file, a `mmap`ed
   Parquet dataset, or a database's data file.

- **Returns to OS?** Clean (unmodified) file-backed pages are cheap to reclaim:
  the kernel can just drop them (the data is safe on disk) and re-read later.
  This is why file-backed memory is "nicer" than anonymous memory under
  pressure.
- **Counts toward pod memory?** The **page cache** portion is subtle and a
  frequent source of confusion — covered precisely in Chapters 3, 7, and 8.

```
   ANONYMOUS                          FILE-BACKED
   +-------------------------+        +-------------------------+
   | Python objects, NumPy   |        | python3 binary (r-x)    |
   | arrays, heap, stack     |        | libc.so, libssl.so      |
   |                         |        | mmap'd model / dataset  |
   +-----------+-------------+        +-----------+-------------+
               |                                  |
       backing store: SWAP                backing store: THE FILE
       (only if configured)               (always recoverable from disk)
               |                                  |
   Under pressure: must be         Under pressure: clean pages just
   written to swap or the           dropped for free; dirty pages
   process is OOM-killed.           written back first.
```

**Common misconception.** "All my memory is my program's data." No — a
meaningful fraction of a fresh Python process's mapped memory is shared,
read-only, file-backed library code that costs almost nothing per additional
process. Conflating this with your data leads to wildly overestimating "how
much my app uses" (the RSS vs. PSS trap, Chapter 3).

## 1.12 Putting it together: a one-paragraph mental model

Your process sees a private 128 TiB **virtual address space**. Almost none of
it is real. The parts that are "real" are **mappings** (`mmap`s) — either
**file-backed** (code, libraries, mmap'd data; often shared and read-only) or
**anonymous** (your heap, stack, objects, arrays; private, swap-backed). The
kernel hands out physical RAM one **4 KiB page frame** at a time, and only when
you actually *touch* a page (demand paging, Chapter 6). "How much memory does
my app use?" is really the question "how many physical frames are currently
backing this process's mappings, and how are they shared?" — which is exactly
what RSS, PSS, and USS measure in **Chapter 3**.

---

## Key takeaways

- Memory = RAM = a fast, volatile, byte-addressable array. Storage = disk =
  persistent files. Not the same thing.
- **Virtual memory** gives every process a private, huge address space; the
  kernel maps virtual **pages** to physical **frames** via **page tables** +
  the **MMU**.
- The unit of everything is the **4 KiB page**. RSS, `mmap`, page faults, and
  huge pages all revolve around it.
- Everything is an `mmap`: **anonymous** (your data, swap-backed, the thing
  that OOM-kills you) or **file-backed** (code/libraries/mmap'd files, often
  shared and free-ish under pressure).
- The core question of memory debugging: *how many physical frames back my
  mappings, and why don't they get released?*

## Practice exercises

1. Run `getconf PAGE_SIZE` and `cat /proc/self/maps` on your machine. Identify
   one file-backed read-only region (has a path, `r-xp`) and one anonymous
   region (`00:00 0`, no path).
2. Compute how many bytes are in `2Gi` vs `2GB`. By how many MB do they differ?
3. Start `python3 -c "input()"` in one terminal; in another run
   `cat /proc/$(pgrep -f 'input')/maps | wc -l`. How many mappings does a
   near-idle Python process have?

## Quiz questions

1. True/false: a 64-bit process can back all 128 TiB of its address space with
   RAM. Explain.
2. What is the difference between a *page* and a *page frame*?
3. Why can a read-only shared library be mapped into 100 processes without
   costing 100× the RAM?
4. Which kind of memory (anonymous or file-backed) is the primary cause of
   `OOMKilled`, and why?
5. Why does allocating a 100 GB region on a 4 GB machine sometimes *succeed*?

## Suggested experiments

- Write a Python script that does `x = bytearray(500 * 1024 * 1024)` (500 MB),
  then `input()`. Before and after allocation, look at
  `grep VmRSS /proc/<pid>/status`. Watch RSS jump by ~500 MB — this is
  anonymous memory being faulted in as you allocate.
- Now change it to only *allocate* but immediately `del x; import gc;
  gc.collect()` before `input()`. Does RSS return to baseline? Note your
  result — Chapter 4 explains why it often does *not*.

---

*Next up: **[Chapter 2 — Linux Process Memory](02_linux_process_memory.md)**,
where we dissect every segment (text, data, BSS, heap, stack, libraries, mmaps)
and trace exactly what happens when a Python process starts.*

[← Back to index](README.md) · [Chapter 2 →](02_linux_process_memory.md)
