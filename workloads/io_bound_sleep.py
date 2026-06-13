"""An I/O-bound program: most "work" is waiting (time.sleep stands in for a
network call / DB query / disk read).

Used to demonstrate:

* why CPU profilers (cProfile, py-spy in CPU mode) show almost nothing
  interesting for I/O-bound code,
* how to use ``threading`` to run several "requests" concurrently,
* how stack-dump tools (faulthandler, py-spy dump) show many threads parked
  in ``time.sleep`` / ``Condition.wait``.

Run it directly:

    python workloads/io_bound_sleep.py
    python workloads/io_bound_sleep.py --workers 8 --requests 20
"""

from __future__ import annotations

import argparse
import threading
import time


def handle_request(request_id: int, latency: float) -> str:
    """Simulate a network/database call that takes ``latency`` seconds."""
    time.sleep(latency)
    return f"request {request_id} done after {latency:.2f}s"


def worker(worker_id: int, requests: list[int], latency: float, results: list[str]) -> None:
    for request_id in requests:
        result = handle_request(request_id, latency)
        results.append(f"[worker {worker_id}] {result}")


def run(num_workers: int = 4, num_requests: int = 16, latency: float = 0.25) -> list[str]:
    """Fan ``num_requests`` requests out across ``num_workers`` threads."""
    results: list[str] = []
    # Round-robin assign request ids to workers.
    buckets: list[list[int]] = [[] for _ in range(num_workers)]
    for request_id in range(num_requests):
        buckets[request_id % num_workers].append(request_id)

    threads = [
        threading.Thread(
            target=worker, args=(i, buckets[i], latency, results), name=f"io-worker-{i}"
        )
        for i in range(num_workers)
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--requests", type=int, default=16)
    parser.add_argument("--latency", type=float, default=0.25,
                         help="Simulated per-request latency in seconds.")
    args = parser.parse_args()

    start = time.perf_counter()
    results = run(args.workers, args.requests, args.latency)
    elapsed = time.perf_counter() - start

    for line in results:
        print(line)
    print(f"\nTotal wall time: {elapsed:.2f}s for {args.requests} requests "
          f"across {args.workers} workers")
