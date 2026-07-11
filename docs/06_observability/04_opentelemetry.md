# OpenTelemetry - following one request across services

Every tool so far stops at the process boundary. But in a real system a
single request fans out: web handler -> message queue -> background worker
-> database -> a third-party API. When "the request is slow" or "it fails
sometimes", no single-process profiler or debugger can follow it, because the
work happens in **different processes on different machines**.

**OpenTelemetry (OTel)** solves this by propagating a **trace ID** across
service boundaries. Each service records **spans** (timed units of work) and
tags them with that shared trace ID, so the whole request reassembles into
one connected timeline - a **distributed trace** - showing exactly which hop
was slow or where it errored.

OTel is a **vendor-neutral standard** (API + SDK + wire protocol, OTLP). You
instrument once and export to whatever backend you like: Jaeger, Grafana
Tempo, Datadog, Honeycomb, Sentry, etc. The concepts below are the payoff;
the backend is a config detail.

## The model in three words

- **Trace** - one request's whole journey (a tree of spans, sharing a trace ID).
- **Span** - one operation within it (an HTTP handler, a DB query, a function),
  with a start/end time, attributes, and a parent span.
- **Context propagation** - passing the trace/span IDs across the boundary
  (e.g. the W3C `traceparent` HTTP header, or a message header) so the
  downstream service's spans attach to the same trace.

## Install

```bash
pip install opentelemetry-api opentelemetry-sdk \
            opentelemetry-exporter-otlp opentelemetry-distro
```

## 1. Zero-code auto-instrumentation (fastest start)

`opentelemetry-instrument` wraps common libraries (requests, Flask, Django,
FastAPI, psycopg, SQLAlchemy, Celery, ...) and produces spans automatically -
no code changes:

```bash
opentelemetry-bootstrap -a install          # install matching instrumentations
OTEL_SERVICE_NAME=checkout \
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4317 \
opentelemetry-instrument python app.py
```

Out of the box you now get a span per incoming request and per outgoing
HTTP/DB call, with the trace context propagated across services - so a
request touching three services shows up as one trace.

## 2. Manual spans for your own logic

Auto-instrumentation covers the I/O edges; add spans around the *business*
logic you care about:

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

def process_order(order):
    with tracer.start_as_current_span("process_order") as span:
        span.set_attribute("order.id", order.id)
        span.set_attribute("order.total", order.total)
        with tracer.start_as_current_span("charge_card"):
            charge(order)                 # a child span, timed separately
```

Now the trace shows `process_order` with a `charge_card` child - you can see
which sub-step ate the latency, with your own attributes attached for
filtering.

## 3. Correlate traces with logs

Put the trace ID into your log lines and you can jump from a log entry
straight to the full distributed trace (and back):

```python
from opentelemetry import trace
span = trace.get_current_span()
trace_id = format(span.get_span_context().trace_id, "032x")
logger.info("charge failed", extra={"trace_id": trace_id})
```

This is the glue between the "above" tools: an error in **Sentry**
([`03_sentry.md`](03_sentry.md)) that carries a trace ID links to the OTel
trace that shows *where in the request path* it went wrong.

## Metrics and logs, too

OTel isn't only traces - it's a single SDK for the "three pillars":

- **Traces** - the request timelines above (the headline feature).
- **Metrics** - counters/histograms (request rate, latency, error count) on a
  neutral standard, exportable to Prometheus and others.
- **Logs** - structured logs correlated with traces via the shared context.

## Production practices

- **Sample.** Recording every span on a high-traffic service is expensive;
  use head- or tail-based sampling (keep all *errored*/slow traces, sample
  the rest).
- **Name spans low-cardinality.** `GET /orders/{id}`, not
  `GET /orders/12345` - or you'll blow up cardinality in the backend.
- **Run a Collector.** Export via the OTel Collector rather than wiring every
  service directly to a vendor - it centralizes batching, sampling, and
  re-routing without redeploys.
- **Propagate context at every boundary.** For HTTP the auto-instrumentation
  handles it; for custom transports (a queue, gRPC) make sure you inject and
  extract the context, or the trace breaks into disconnected pieces.

## Where OTel fits vs. everything else

| Question | Tool |
|---|---|
| Which **function/line** in one process is slow? | `py-spy` / `cProfile` (modules 1-2) |
| In what **order** did concurrent tasks run? | VizTracer ([module 4](../04_concurrency_debugging/05_viztracer_timeline.md)) |
| What **crashed**, aggregated across the fleet? | Sentry ([03](03_sentry.md)) |
| Which **service/hop** in a multi-service request was slow or failed? | **OpenTelemetry** |

## When to reach for OpenTelemetry

- Your system is **more than one service** and a request crosses boundaries.
- "It's slow" but the slow part could be *any* hop - you need to see the
  whole path to know where to point a profiler.
- You want **vendor-neutral** instrumentation you won't have to rewrite when
  you change observability backends.

Once OTel points you at the guilty service, you're back to modules 1-5:
attach `py-spy`, take a `pystack` dump, or profile *that* process to find the
line.
