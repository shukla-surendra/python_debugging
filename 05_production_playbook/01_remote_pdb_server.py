"""A remote `pdb` console for a running process - no extra dependencies.

`pdb.set_trace()` / `breakpoint()` (module 1, file 05) need a TTY attached to
the process's stdin/stdout. A production service usually has neither - its
stdin/stdout are redirected to log files or `/dev/null`. The fix: give `pdb`
a SOCKET instead of a terminal.

The recipe:

1. A background thread listens on a TCP socket.
2. On each connection, it creates `pdb.Pdb(stdin=conn_file, stdout=conn_file)`
   and calls `debugger.set_trace()` **with no arguments** - this breaks
   *inside the server thread itself*, at the `set_trace()` line.
3. From that pdb prompt you have full access to any Python expression in
   scope - including a `namespace` dict/object the rest of the app shares
   with this thread, e.g. `globals()` of your main module, a registry of
   live connections, queue depths, feature-flag state, etc.
4. `c` (continue) closes that connection and the thread goes back to
   `accept()`, ready for the next session.

This is the same idea as Werkzeug's debug console, Django's `manhole`, or
`aiomonitor` - a live REPL into the process - built from two stdlib modules.

**Security note**: this opens an UNAUTHENTICATED socket that gives arbitrary
code execution in your process. Bind to `127.0.0.1` (never `0.0.0.0`), and
only enable it behind an SSH tunnel / in environments where "anyone who can
reach this port can run any code as this process" is acceptable (e.g.
internal-only debug ports, dev/staging - or production with firewall rules
restricting the port to a bastion host).

Run:
    python 01_remote_pdb_server.py
"""

from __future__ import annotations

import pdb
import socket
import threading
import time


def serve_remote_pdb(
    namespace: dict,
    host: str = "127.0.0.1",
    port: int = 4444,
    stop_event: threading.Event | None = None,
) -> None:
    """Serve one pdb session per TCP connection, with `namespace` in scope.

    Intended to be run in its own daemon thread:
        threading.Thread(target=serve_remote_pdb, args=(globals(),), daemon=True).start()
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(1)
    server.settimeout(1.0)  # so stop_event is checked periodically

    print(f"[remote-pdb] listening on {host}:{port} - connect with: nc {host} {port}")

    while not (stop_event and stop_event.is_set()):
        try:
            conn, addr = server.accept()
        except socket.timeout:
            continue

        print(f"[remote-pdb] connection from {addr}")
        rfile = conn.makefile("r")
        wfile = conn.makefile("w")
        debugger = pdb.Pdb(stdin=rfile, stdout=wfile)
        debugger.message(
            "Remote pdb console. `namespace` is the app's shared state.\n"
            "Try: p namespace\n"
            "     p namespace['counter']\n"
            "     namespace['counter'] = 0   # mutate live state\n"
            "     c                          # disconnect, app keeps running"
        )
        debugger.set_trace()  # <-- breaks HERE, in this function's frame
        try:
            conn.close()
        except OSError:
            pass

    server.close()
    print("[remote-pdb] stopped")


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_remote_pdb_round_trip() -> None:
    """Start the server, connect a client, and drive a real pdb session."""
    section("Remote pdb: inspecting and mutating a 'running service's' state")

    # `namespace` stands in for "things the app wants debuggable" - in a real
    # app this is often just `globals()`, or a dict of key subsystems
    # (caches, connection pools, feature flags, queue objects, ...).
    namespace = {"counter": 0, "feature_flag_enabled": False}
    stop = threading.Event()

    def app_loop() -> None:
        while not stop.is_set():
            namespace["counter"] += 1
            time.sleep(0.05)

    port = 4444
    server_thread = threading.Thread(
        target=serve_remote_pdb, args=(namespace,), kwargs={"port": port, "stop_event": stop},
        daemon=True, name="remote-pdb-server",
    )
    app_thread = threading.Thread(target=app_loop, daemon=True, name="app-loop")
    server_thread.start()
    app_thread.start()
    time.sleep(0.3)  # let both threads get going

    print(f"\nIn a real session you'd now run: nc 127.0.0.1 {port}")
    print("This demo instead connects a client socket and sends pdb commands")
    print("programmatically, to show the full round trip:\n")

    client = socket.create_connection(("127.0.0.1", port), timeout=5)
    client.settimeout(2)

    def send(cmd: str) -> None:
        print(f"(Pdb) {cmd}")
        client.sendall((cmd + "\n").encode())
        time.sleep(0.1)

    def recv() -> str:
        try:
            return client.recv(8192).decode()
        except socket.timeout:
            return "<no more output - connection closed>"

    print(recv())  # banner + first prompt

    send("p namespace['counter']")
    print(recv())

    send("p namespace['feature_flag_enabled']")
    print(recv())

    send("namespace['feature_flag_enabled'] = True")
    print(recv())

    send("c")
    print(recv())

    client.close()
    time.sleep(0.1)

    print(f"\nAfter disconnecting, app_loop is still running (counter is now")
    print(f"{namespace['counter']}), and feature_flag_enabled is now")
    print(f"{namespace['feature_flag_enabled']} - changed LIVE via the remote")
    print("pdb session, with zero downtime and zero extra dependencies.")

    stop.set()
    app_thread.join()
    server_thread.join(timeout=2)


if __name__ == "__main__":
    demo_remote_pdb_round_trip()
