# Logging - the debugging tool you use before all the others

Every other tool in this repo is something you reach for *after* you know
there's a problem. **Logging** is what tells you there's a problem in the
first place, and it's the single most-used production debugging tool there
is. Done well, a log stream answers "what was this process doing, in what
order, with what values" without attaching anything - which is exactly the
question stack dumps and tracers answer, but *continuously* and *after the
fact*.

This doc is about using Python's `logging` properly, and the structured-
logging upgrade that makes logs queryable in production.

## Why `logging`, not `print()`

`print()` has no levels, no timestamps, no source location, no way to turn
off in production, and no routing. `logging` gives you all of that for free:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
)
log = logging.getLogger(__name__)

log.debug("cache miss for key=%s", key)     # off unless level=DEBUG
log.info("request handled in %d ms", ms)
log.warning("retrying (%d/%d)", attempt, max_attempts)
log.error("payment failed for order=%s", order_id)
```

Two habits that matter:

- **Use lazy `%s` formatting**, not f-strings, in log calls:
  `log.info("x=%s", x)` - the string is only built if that level is enabled,
  so `DEBUG` logs cost nothing in production.
- **One logger per module** via `logging.getLogger(__name__)` - this gives
  every message a dotted name (`myapp.orders.payment`) you can filter and
  route on.

## Log the exception, with its traceback

Inside an `except`, `log.exception()` records the message **and** the full
traceback automatically - the logging equivalent of `traceback.print_exc()`
from module 1, but routed through your handlers:

```python
try:
    charge(order)
except PaymentError:
    log.exception("charge failed for order=%s", order.id)   # includes traceback
    raise
```

(`log.error(..., exc_info=True)` does the same if you don't want ERROR-vs-
EXCEPTION distinction.)

## Configure once, centrally: `dictConfig`

For anything beyond a script, configure logging in one place with
`logging.config.dictConfig` - levels per logger, formatters, and handlers
(console, rotating file, syslog, etc.):

```python
from logging.config import dictConfig

dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "std"},
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "myapp.orders": {"level": "DEBUG"},      # noisier for one subsystem
        "urllib3": {"level": "WARNING"},         # quieter third-party
    },
})
```

## Structured logging - make logs queryable

Plain text logs are readable by humans but painful to search at scale
("find every failed charge for tenant X last night"). **Structured logging**
emits key/value records (usually JSON) that a log system (Loki, ELK,
CloudWatch, Datadog) can filter and aggregate.

Two common approaches:

```python
# 1. structlog - ergonomic structured logging
import structlog
log = structlog.get_logger()
log.info("charge_failed", order_id=order.id, tenant=tenant.slug, amount=order.total)
# -> {"event": "charge_failed", "order_id": 42, "tenant": "acme", "amount": 19.99, ...}
```

```python
# 2. python-json-logger - keep stdlib logging, just emit JSON
from pythonjsonlogger import jsonlogger
handler = logging.StreamHandler()
handler.setFormatter(jsonlogger.JsonFormatter())
```

Both are `pip install` extras (not pinned in this repo's requirements -
add the one you prefer). In containers/Kubernetes, **log to stdout as JSON**
and let the platform collect it - don't write your own log files inside a
pod (see [`../05_production_playbook/04_kubernetes_debugging.md`](../05_production_playbook/04_kubernetes_debugging.md)).

## Correlation IDs - tie a log line to a request (and a trace)

The thing that turns logs from "a wall of lines" into "the story of one
request" is a **correlation/trace ID** attached to every line for that
request. Bind it once and every subsequent log carries it:

```python
# structlog: bind context for the rest of this request
structlog.contextvars.bind_contextvars(request_id=req_id, trace_id=trace_id)
```

With the stdlib, a `logging.Filter` that injects a `contextvars` value into
each record achieves the same. Use the **same** trace ID your distributed
tracing uses ([`04_opentelemetry.md`](04_opentelemetry.md)) and your error
tracker records ([`03_sentry.md`](03_sentry.md)), and you can pivot from a
log line → the full trace → the captured exception, and back.

## Production practices

- **Levels mean something.** DEBUG = developer detail (off in prod),
  INFO = normal milestones, WARNING = recoverable oddity, ERROR = a failed
  operation, CRITICAL = the process can't continue. Alert on ERROR+, not INFO.
- **Don't log in tight loops** - a log call per iteration of a hot path can
  dominate runtime and flood storage. Sample or aggregate instead.
- **Never log secrets/PII** - tokens, passwords, full card numbers, personal
  data. Scrub at the formatter/processor level, same discipline as Sentry.
- **Log to stdout in containers**, structured (JSON), and let the platform
  route it. Rotating files belong on classic hosts, not pods.
- **Make it greppable and queryable**: stable event names + fields beat
  free-form prose sentences you can't filter on.

## Where logging sits vs. the rest of the toolbox

| Question | Tool |
|---|---|
| "What was it doing, over time, after the fact?" | **logging** (this doc) |
| "What is it doing *right now*?" | stack dumps (module 1) |
| "What crashed, aggregated across the fleet?" | Sentry ([03](03_sentry.md)) |
| "Which service/hop in the request was slow?" | OpenTelemetry ([04](04_opentelemetry.md)) |

Logging is the always-on baseline the incident tools build on: good logs
often *are* the diagnosis, and when they aren't, they tell you which of the
other modules to open.
