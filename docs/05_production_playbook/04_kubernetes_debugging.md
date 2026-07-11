# Debugging a Python app running in Kubernetes

Everything in modules 1-6 still applies inside Kubernetes - `py-spy`,
`pystack`, `pdb`, `debugpy`, `strace`, `memray`, core dumps. What changes is
the part *before* you run the tool: **how you reach the process**, **what
permissions you get**, and **how you avoid Kubernetes killing the pod out
from under you** while you debug. This doc is about those wrappers.

The mental model: a container is just a process in some namespaces with a
cgroup limit. Kubernetes debugging is mostly "get a tool into those
namespaces, with `ptrace` allowed, without tripping a probe."

## 1. Getting to the process

### If the image has a shell and the tools baked in

```bash
kubectl exec -it <pod> -c <container> -- py-spy dump --pid 1
kubectl exec -it <pod> -- /bin/sh          # then run tools interactively
```

**The app is almost always PID 1** in its container, so `--pid 1` is your
target. (PID 1 also has signal quirks - see the diagnostics-handler note in
[`02_diagnostics_signal_server.py`](02_diagnostics_signal_server.py).)

### If the image is distroless/slim (no shell, no tools)

Modern images often ship **no shell and no debug tools** - `kubectl exec`
fails because there's no `/bin/sh`. This is exactly what **ephemeral debug
containers** solve: attach a *separate* container, with your tools, into the
running pod, sharing the target's process namespace:

```bash
kubectl debug -it <pod> \
  --image=ghcr.io/your/debug-tools:latest \  # an image WITH py-spy/pystack/strace
  --target=<container> \                      # share THAT container's PID namespace
  --profile=sysadmin                          # grant elevated caps incl. SYS_PTRACE
```

- `--target=<container>` puts the debug container in the app's **process
  namespace**, so it can see and attach to PID 1 of the app.
- `--profile=sysadmin` (kubectl ≥ 1.28) runs the ephemeral container
  privileged, which includes the `SYS_PTRACE` capability the sampling tools
  need. Without a recent kubectl/cluster you must instead pre-provision the
  capability (next section).

Build a small "debug tools" image once (py-spy, pystack, strace, lsof, gdb,
memray) and keep it in your registry so it's ready during an incident.

### Copy the pod instead of touching the live one

`kubectl debug` can clone a pod so you experiment without risking the real
one (it won't be behind the Service):

```bash
kubectl debug <pod> --copy-to=<pod>-debug --container=<container> -it -- /bin/sh
```

## 2. Permissions - `ptrace` is the recurring blocker

`py-spy`, `pystack`, `strace`, and `gdb` all read another process's memory
via `ptrace` (see [`../01_stack_dumps/06_py_spy_dump.md`](../01_stack_dumps/06_py_spy_dump.md)).
In Kubernetes you grant it in one of three ways:

**a) On the workload, ahead of time** - the app container gets the capability:

```yaml
securityContext:
  capabilities:
    add: ["SYS_PTRACE"]
```

**b) A debug sidecar sharing the process namespace** - the app stays
unprivileged; a co-located container does the ptrace:

```yaml
spec:
  shareProcessNamespace: true          # all containers see each other's PIDs
  containers:
    - name: app
      image: myapp:1.4.2
    - name: debug                       # tools live here, not in the app image
      image: ghcr.io/your/debug-tools:latest
      securityContext:
        capabilities: { add: ["SYS_PTRACE"] }
      command: ["sleep", "infinity"]
```

With `shareProcessNamespace`, `py-spy dump --pid <app-pid>` from the `debug`
container works - and the app process is no longer PID 1, so you'll see it at
some higher PID (`ps aux` in the debug container to find it).

**c) `kubectl debug --profile=sysadmin`** - the on-demand version of (a),
shown above. Best when you didn't plan ahead.

> `ptrace_scope` on the **node** can still block you even with the
> capability. `SYS_PTRACE` is the k8s-level knob; the node's
> `kernel.yama.ptrace_scope` is the OS-level one from module 1.

## 3. Isolate the pod BEFORE you pause it (the probe trap)

The single most common self-inflicted Kubernetes debugging wound:

> You attach `pdb`/`debugpy` and hit a breakpoint, or run `gdb` and stop the
> process. The **liveness probe** can't get a response, Kubernetes decides
> the pod is dead, and **restarts it - destroying the exact state you were
> debugging.**

Read-only *snapshot* tools (`py-spy dump`, `pystack`) pause the process for
~1ms and are safe. Anything that **holds** the process stopped -
`pdb`/`debugpy` breakpoints, `gdb` - needs you to take the pod out of the
firing line first:

- **Remove it from its Service** by changing a label the selector matches, so
  traffic stops but the pod keeps running:
  ```bash
  kubectl label pod <pod> app=myapp-DEBUG --overwrite   # Service selector no longer matches
  ```
  The Deployment will spin up a replacement to carry traffic; your pod is now
  a quarantined copy you can freeze at will.
- **Or relax the probes** on a debug copy (`kubectl debug --copy-to`) by
  raising `timeoutSeconds`/`failureThreshold`, or removing the liveness probe.
- **Or scale up first** (`kubectl scale --replicas=+1`) so pausing one pod
  doesn't reduce capacity.

Only then attach an interactive debugger.

## 4. Interactive debugging: `port-forward` the socket out

`pdb`/`debugpy` need a connection, and you should **never** expose their
socket publicly (arbitrary code execution). Bind to localhost inside the pod
and tunnel with `port-forward`:

```bash
# App started with: python -m debugpy --listen 127.0.0.1:5678 --wait-for-client app.py
kubectl port-forward <pod> 5678:5678
# now attach VS Code / your IDE to localhost:5678 (see 09_debugpy.md in module 1)
```

The same trick exposes the stdlib remote-pdb console from
[`01_remote_pdb_server.py`](01_remote_pdb_server.py) - it binds `127.0.0.1`
by design precisely so `port-forward` is the only way in.

## 5. Trigger the built-in diagnostics handler

If you armed the `SIGUSR1` diagnostics handler from
[`02_diagnostics_signal_server.py`](02_diagnostics_signal_server.py), fire it
without any special tools or capabilities - it's just a signal:

```bash
kubectl exec <pod> -- kill -USR1 1        # dump threads/GC/memory to the handler's file
kubectl exec <pod> -- cat /var/log/myapp/diagnostics-*.txt
```

## 6. Getting artifacts out (flamegraphs, core files, profiles)

Anything you generate lands on the pod's ephemeral filesystem and dies with
the pod. Copy it out, or write it to a mounted volume:

```bash
kubectl cp <pod>:/tmp/profile.svg ./profile.svg       # py-spy flamegraph
kubectl cp <pod>:/tmp/core.1 ./core.1                 # a core dump
kubectl cp <pod>:/tmp/out.memray ./out.memray         # memray capture
```

For recurring capture, mount an `emptyDir` or persistent volume at the path
your handler writes to, so artifacts survive a container restart.

## 7. Core dumps in Kubernetes

Core dumps are the best way to debug a **crash** after the fact
([`../01_stack_dumps/08_pystack.md`](../01_stack_dumps/08_pystack.md)), but
k8s adds friction because `core_pattern` is a **node-level kernel setting**
(`/proc/sys/kernel/core_pattern`) shared by every pod on the node - it is
**not** namespaced, so you can't set it from inside a normal pod.

Options:

- **A privileged DaemonSet / node config** sets `core_pattern` to a path on a
  `hostPath` volume, and pods set `ulimit -c unlimited`. Cores land on the
  node; collect and analyze with `pystack core` offline.
- **`gcore` a wedged pod** from a debug container (`gcore <pid>`), then
  `kubectl cp` the core out - no crash required, and the process keeps
  running.
- Then, on your workstation: `pystack core ./core --native` (ship the image's
  libraries too, or use `--lib-search-root`).

## 8. OOMKilled - exit code 137

A container that exceeds its memory **limit** is `SIGKILL`ed by the kernel's
cgroup OOM killer - **exit code 137** (128 + 9), reason `OOMKilled`:

```bash
kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[0].lastState.terminated}{"\n"}'
# {"exitCode":137,"reason":"OOMKilled",...}
```

The cruel part: `SIGKILL` gives the process **no chance** to dump anything -
no traceback, no core, no diagnostics handler. So OOM debugging must be
**proactive**:

- Reproduce with `memray`/`tracemalloc` (module 3) on a copy running under a
  slightly lower limit, so you catch the growth *before* the kill.
- Check whether it's a genuine leak or just a limit set below the real
  working set - `kubectl top pod`, and container memory metrics over time.
- Distinguish **container** OOM (your cgroup limit - fix the app or raise the
  limit) from **node** OOM (the node ran out - a scheduling/limits problem).

## 9. "It's slow" might be CPU throttling, not your code

A CPU **limit** is enforced as a CFS quota. A pod can be **throttled** -
adding latency - while showing modest *average* CPU, which sends you chasing
a performance bug that isn't in your code. Before you trust a profiler,
rule this out:

```bash
# via metrics: container_cpu_cfs_throttled_periods_total climbing = throttling
kubectl top pod <pod>
```

If throttled, the fix is a limits/requests change, not a code change - and
`py-spy top` will show the process is idle (throttled) rather than busy.

## 10. Crashes and restarts: read the *previous* container's logs

```bash
kubectl logs <pod> --previous                 # logs from the container BEFORE it restarted
kubectl describe pod <pod>                      # events: OOMKilled, probe failures, image pulls
kubectl get pod <pod> -o wide                   # restarts count, node, status
```

`CrashLoopBackOff` means it keeps dying on startup; `--previous` logs plus the
exit code (137 = OOM, 139 = SIGSEGV → grab a core, 1 = app error → the
traceback is in those logs) tell you which module to open next.

## 11. Continuous profiling as cluster infrastructure

For "it was slow last night and I wasn't watching", run a **continuous
profiler** as a DaemonSet - Grafana Pyroscope / Parca (eBPF or `py-spy`-style
sampling) keep a rolling flamegraph of every pod. It's the always-on,
look-backwards version of `py-spy record`, without you needing to exec into
anything mid-incident. Distributed tracing
([`../06_observability/04_opentelemetry.md`](../06_observability/04_opentelemetry.md))
and error tracking ([`../06_observability/03_sentry.md`](../06_observability/03_sentry.md))
are the other two "always recording" layers you want wired in before trouble.

## A "debuggable by default" Deployment

Building on the startup snippet in this module's
[`README.md`](README.md), the Kubernetes-level version:

```yaml
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      shareProcessNamespace: true              # sidecar/ephemeral tools can see the app
      containers:
        - name: app
          image: myapp:1.4.2
          securityContext:
            capabilities:
              add: ["SYS_PTRACE"]              # allow py-spy/pystack/strace attach
          resources:
            requests: { memory: "512Mi", cpu: "250m" }
            limits:   { memory: "1Gi" }        # NB: no CPU limit -> no throttling surprises
          volumeMounts:
            - name: diag                        # somewhere for dumps/cores/profiles to land
              mountPath: /var/log/myapp
          livenessProbe:
            timeoutSeconds: 5
            failureThreshold: 6                 # tolerant enough to survive a brief pause
      volumes:
        - name: diag
          emptyDir: {}
```

## Quick command reference

```bash
# Snapshot a live pod (safe, ~1ms pause)
kubectl exec <pod> -- py-spy dump --pid 1
kubectl exec <pod> -- pystack remote 1 --native

# Distroless / no tools in image -> ephemeral debug container
kubectl debug -it <pod> --image=debug-tools --target=<container> --profile=sysadmin

# Interactive debugger, safely
kubectl label pod <pod> app=myapp-DEBUG --overwrite     # 1. drain from Service
kubectl port-forward <pod> 5678:5678                    # 2. tunnel debugpy/remote-pdb

# Trigger armed diagnostics, no caps needed
kubectl exec <pod> -- kill -USR1 1

# Post-crash forensics
kubectl logs <pod> --previous
kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[0].lastState.terminated}'
kubectl cp <pod>:/tmp/core.1 ./core.1 && pystack core ./core.1 --native
```

## When you're debugging in Kubernetes

1. **Snapshot first, non-invasively** - `py-spy dump` / `pystack remote` via
   `exec` or an ephemeral container. Usually enough, always safe.
2. **Need to interact?** Drain the pod from its Service (or use a copy),
   `port-forward`, then attach `debugpy`/remote-pdb.
3. **It already crashed?** `kubectl logs --previous` + exit code → OOM
   (proactive memory profiling) vs. segfault (core + `pystack`) vs. app error
   (the traceback / Sentry).
4. **It's a recurring mystery?** Wire in the always-on layers (continuous
   profiler, tracing, error tracking) so next time you're already recording.
