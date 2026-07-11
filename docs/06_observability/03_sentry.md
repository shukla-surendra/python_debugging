# Sentry - error tracking across a whole fleet

A traceback printed to a log helps one developer, once, if they happen to be
watching. **Sentry** is the production version of `traceback`: it captures
every unhandled exception across every instance of your service,
**deduplicates** them into issues, and keeps the **context** you'd otherwise
have to reproduce - the stack with local variables, the request, the release,
the user, and a trail of breadcrumbs leading up to the failure.

If module 1 is "attach to the process while it's broken", Sentry is "have
the process record its own crash, with evidence, so you can debug it after
the fact - even though you weren't watching."

Sentry is a hosted service (or self-hostable); this doc is about the Python
SDK. Other tools in this space work the same way (Rollbar, Bugsnag, Datadog
Error Tracking, GlitchTip) - the concepts transfer.

## Install & initialize

```bash
pip install sentry-sdk
```

```python
import sentry_sdk

sentry_sdk.init(
    dsn="https://<key>@o0.ingest.sentry.io/0",   # from your Sentry project
    environment="production",                    # separate prod/staging/dev
    release="myapp@1.4.2",                        # tie errors to a deploy
    traces_sample_rate=0.1,                       # 10% of requests get a perf trace
    send_default_pii=False,                       # DON'T ship PII by default
)
```

Call `init()` once at startup. From that point, **any unhandled exception is
captured automatically** - no `try/except` needed. The SDK ships
integrations that hook the frameworks you already use (Django, Flask,
FastAPI, Celery, `logging`, ASGI/WSGI), so request context and error-level
log records are attached without extra code.

## What a captured error contains

- The full **stack trace**, with **local variables** at each frame (the same
  forensic value as `pdb.post_mortem`, but captured automatically in prod).
- **Breadcrumbs**: a timeline of recent log lines, HTTP calls, and DB queries
  before the crash - the "how did we get here".
- **Tags & context**: release, environment, server, transaction, plus
  anything you attach.
- **Grouping**: identical errors collapse into one issue with a count and
  first/last-seen, so 10,000 occurrences are one line in your dashboard, not
  10,000 log entries.

## Enriching and capturing manually

```python
import sentry_sdk

sentry_sdk.set_user({"id": user.id})            # who hit it
sentry_sdk.set_tag("tenant", tenant.slug)       # filter/group by this
sentry_sdk.set_context("order", {"id": order.id, "total": order.total})

try:
    charge(order)
except PaymentError as exc:
    sentry_sdk.capture_exception(exc)           # report a HANDLED error too
    raise

sentry_sdk.capture_message("cache rebuild took >5s", level="warning")
```

`capture_exception` lets you report errors you *caught* but still want
visibility into; `capture_message` records noteworthy non-exception events.

## Production practices

- **Scrub PII.** Keep `send_default_pii=False`, and use `before_send` to
  redact anything sensitive before it leaves your process - local variables
  can contain passwords, tokens, and personal data.
- **Sample performance traces.** `traces_sample_rate` at 100% is expensive on
  a busy service; 1-10% is typical. Error capture itself is effectively
  always-on and cheap.
- **Set `release` and `environment`.** Without them you can't answer "did my
  deploy cause this?" or separate prod noise from staging.
- **Add breadcrumbs deliberately** for the operations that matter; the
  framework integrations add HTTP/DB ones for free.

## Sentry vs. the local tools

| | Local traceback / `pdb.post_mortem` | Sentry |
|---|---|---|
| Needs you watching when it breaks | **yes** | no - it records automatically |
| Aggregates across instances | no | **yes** (dedupe + counts) |
| Keeps locals/context after the fact | only if you captured it | **yes**, every time |
| Cross-service correlation | no | via tracing (see [OpenTelemetry](04_opentelemetry.md)) |

## When to reach for Sentry

- You run **more than one instance** and can't tail every log.
- You need to know about errors **users didn't report** (most of them).
- You want the crash **context preserved** - locals, request, release - for
  errors that are hard to reproduce.

For following a *slow* (not failing) request across services, pair it with
distributed tracing - [`04_opentelemetry.md`](04_opentelemetry.md). Sentry
also implements tracing and can consume/emit the same spans.
