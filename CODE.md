# Reading the code: the monitoring

How the crew is monitored, file by file: what each piece does, and the documentation it rests on.
The agents are left out: they are CrewAI configuration, and know nothing about the monitoring.

- [The files](#the-files)
- [`import observe`: the monitoring switched on](#import-observe-the-monitoring-switched-on)
- [`opentelemetry-instrument`: the SDK started](#opentelemetry-instrument-the-sdk-started)
- [`events.py`: CrewAI's events as steps](#eventspy-crewais-events-as-steps)
- [`traces.py`: one span per step](#tracespy-one-span-per-step)
- [`logs.py`: one log line per step](#logspy-one-log-line-per-step)
- [`metrics.py`: counts and durations](#metricspy-counts-and-durations)
- [`heartbeat.py` and `health.py`: the watchdog's two inputs](#heartbeatpy-and-healthpy-the-watchdogs-two-inputs)
- [The OpenTelemetry Collector](#the-opentelemetry-collector)
- [The stores: Jaeger, Loki, Prometheus](#the-stores-jaeger-loki-prometheus)
- [Grafana](#grafana)
- [The watchdog](#the-watchdog)

## The files

- **The crew**, `crew/`:
  - [`main.py`](crew/main.py): takes one topic after another, retrying a failed run.
  - [`crew.py`](crew/crew.py): puts the four agents together; [`agents/`](crew/agents): one agent and its task each.
  - [`llm.py`](crew/llm.py) and [`tools/search.py`](crew/tools/search.py): the model and the `search` tool.
- **The monitoring inside the crew**, [`crew/observe/`](crew/observe), one file per signal:
  - [`events.py`](crew/observe/events.py): CrewAI announces every step as an event; this hands each to the signals.
  - [`traces.py`](crew/observe/traces.py): one span per step, inside the span of the step that started it.
  - [`logs.py`](crew/observe/logs.py): one log line per step, with the step's trace ID and span ID.
  - [`metrics.py`](crew/observe/metrics.py): counts and durations, served at `/metrics`.
  - [`heartbeat.py`](crew/observe/heartbeat.py): tells the watchdog after every step that the crew is making progress.
  - [`health.py`](crew/observe/health.py): answers `/health` while the process runs.
- **The programs that observe the crew**, configured in [`compose.yaml`](compose.yaml) and [`stack/`](stack):
  - [`stack/opentelemetry-collector.yaml`](stack/opentelemetry-collector.yaml): where the spans and log lines go.
  - [`stack/loki.yaml`](stack/loki.yaml), [`stack/prometheus.yml`](stack/prometheus.yml): two of the stores.
  - [`stack/grafana/`](stack/grafana): Grafana's sources and its dashboard *The crew*.
- **The watchdog**, [`watchdog/watchdog.py`](watchdog/watchdog.py): finds four problems and decides for each: restart,
  stop or alert.
- **The stages**, [`operator/stages/*.env`](operator/stages): each stage's settings, the only thing a stage changes.

## `import observe`: the monitoring switched on

One line in [`main.py`](crew/main.py) switches on all the monitoring inside the crew:

```python
import observe  # noqa: F401  (the monitoring: logs, traces, metrics, heartbeats)
```

- **Importing runs the module's code.** Python runs a module's top-level code the first time it is imported
  ([the import system](https://docs.python.org/3/reference/import.html)).
  - [`observe/__init__.py`](crew/observe/__init__.py) imports `events` and `health`.
  - `events` imports the four signal modules: `traces`, `logs`, `metrics`, `heartbeat`.
- **What their top-level code starts**:
  - `events.py`: the event listener, registered on CrewAI's event bus by its last line, `Listener()`.
  - `traces.py`: the tracer named `crew`.
  - `logs.py`: the `crew` logger, writing to stdout.
  - `metrics.py`: the metrics, and the HTTP server on port 8000 that serves them.
  - `health.py`: the HTTP server on port 8001 that answers `/health`.
- **`main.py` never uses the name.** The import is for what it starts, so `# noqa: F401` tells the linter that the
  unused import is on purpose.
- **The agents' code knows nothing about it.** The monitoring is this one import, plus the command that starts the
  SDK (next section).

## `opentelemetry-instrument`: the SDK started

The OpenTelemetry SDK, which sends the spans and log lines out of the crew, is started by the command that runs
the crew, not by its code. [`compose.yaml`](compose.yaml):

```yaml
command: ["opentelemetry-instrument", "python", "-u", "main.py"]
```

- **[`opentelemetry-instrument`](https://opentelemetry.io/docs/zero-code/python/)**:  
  The OpenTelemetry launcher for Python, from the `opentelemetry-distro` package.
  - It sets up the SDK, then runs `main.py`.
  - The SDK sits behind the API that `traces.py` and `logs.py` call: they make spans and log lines; the SDK sends them.
  - No library is instrumented here: no instrumentation package is installed, so every span is made by `traces.py`.
- **The `OTEL_*` variables** set the SDK up ([configuration](https://opentelemetry.io/docs/zero-code/python/configuration/),
  [the full list](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/)):
  - `OTEL_SERVICE_NAME=crew`: the service every span and log line names; Jaeger's service, Loki's `service_name`.
  - `OTEL_TRACES_EXPORTER`, `OTEL_LOGS_EXPORTER`: `none` in stage 1, `otlp` from stage 2.
    - With `none`, the spans are still made, and their IDs are in every log line; they go nowhere.
  - `OTEL_METRICS_EXPORTER=none`: the metrics go to Prometheus, from `/metrics`.
  - `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_PROTOCOL`: the Collector, OTLP over HTTP
    ([OTLP exporter](https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/)).
  - `OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true`: the SDK adds its own handler to Python's root logger, so
    every log line also goes to the Collector.
- **The SDK sends in batches**: the ended spans every 5 s, the log lines every second.

## `events.py`: CrewAI's events as steps

CrewAI announces every step it takes as an event, and [`events.py`](crew/observe/events.py) turns each into a
`Step` that the four signals share ([event listeners](https://docs.crewai.com/en/concepts/event-listener)).

- **`Listener`**:  
  A `BaseEventListener` whose `setup_listeners` puts one handler on the event bus per event type.
  - CrewAI runs async handlers one at a time, in the order the events happened.
- **`KINDS`**:  
  Each event type, as a kind and a phase.
  - The kinds: `crew` (a run), `agent`, `llm` (a model call), `tool`.
  - The phases: `start`, `end`, `error`.
  - `inner`: CrewAI's own bookkeeping (a task, the agent's internal flow), which gets no span of its own.
- **`Step`**:  
  One event, in the fields the signals need.
  - `parent`: the step this one happens inside (CrewAI's `parent_event_id`).
  - `started`: for an end or an error, the step's start (CrewAI's `started_event_id`).
  - `seconds`, `tokens`, `error`: how long it took, the model's token counts, what went wrong.
- **The handler**:  
  Hands each step to `traces`, `logs`, `metrics` and `heartbeat`, in that order.
  - Traces come first: the log line and the heartbeat carry the span's IDs.
  - An exception is logged, never raised: the monitoring never breaks a run.

## `traces.py`: one span per step

[`traces.py`](crew/observe/traces.py) opens a span when a step starts and ends it when the step ends, so a run is
one trace: `crew.kickoff` → `invoke_agent <agent>` → `chat sim-1` / `execute_tool search`.

- **`tracer = trace.get_tracer("crew")`**:  
  The OpenTelemetry API's tracer ([trace API](https://opentelemetry-python.readthedocs.io/en/latest/api/trace.html)).
  - The SDK that `opentelemetry-instrument` started is behind it.
- **A start: `tracer.start_span(...)`**:
  - `context`: the parent step's span. The new span takes its trace ID and records its span ID as the parent.
  - `crew.kickoff` has no parent, so it starts a new trace.
  - `start_time`: the event's own time, not the moment the handler runs.
  - `spans` keeps the run's spans by the step's id, so an end finds its span; a new run empties it.
- **An end: `span.end(...)`**:
  - The token counts become attributes.
  - An error sets the span's status to `ERROR` and adds an `exception` event.
  - Only now does the SDK queue the span for its next batch: a span that never ends is never sent.
- **Names and attributes** follow OpenTelemetry's conventions for AI:
  [agent spans](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/) (`invoke_agent`), and
  [model and tool spans](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/) (`chat`, `execute_tool`,
  `gen_ai.*`).
- **`span_of(step)`**:  
  The span a step happened in, for `logs.py` and `heartbeat.py`.

## `logs.py`: one log line per step

[`logs.py`](crew/observe/logs.py) writes one line per step with Python's
[`logging`](https://docs.python.org/3/library/logging.html), and each line reaches two handlers.

- **The `crew` logger, with a handler to stdout**:
  - Its format adds `trace_id=… span_id=…` to every line.
  - `no_ids` puts `-` in their place on a line written outside any step (`main.py`'s retries).
  - Docker keeps the container's stdout: `docker compose logs -f crew`.
- **`record(step)`**:
  - `message(step)`: the line's text, such as `Writer finished in 1.9 s`.
  - `with trace.use_span(span)`: makes the step's span the current one while the line is written.
  - `extra=`: the IDs, for the stdout format.
- **The SDK's handler**:  
  The `LoggingHandler` that `opentelemetry-instrument` adds to the root logger
  ([logs SDK](https://opentelemetry-python.readthedocs.io/en/latest/sdk/_logs.html)).
  - The `crew` logger passes every line up to the root logger, so this handler gets each line too.
  - It reads the trace ID and span ID from the current span, which is why `record` makes the step's span current.
  - It sends the line to the Collector, with the IDs as fields of their own
    ([log data model](https://opentelemetry.io/docs/specs/otel/logs/data-model/)).
- **CrewAI's own logging** is set to `ERROR`, so its lines do not crowd the crew's.

## `metrics.py`: counts and durations

[`metrics.py`](crew/observe/metrics.py) keeps numbers that add up every run, and serves them for Prometheus to
fetch, with [`prometheus_client`](https://prometheus.github.io/client_python/) (not OpenTelemetry).

- **The metric types** ([Prometheus's types](https://prometheus.io/docs/concepts/metric_types/)):
  - [`Counter`](https://prometheus.github.io/client_python/instrumenting/counter/): only goes up; `crew_runs` is
    served as `crew_runs_total`.
  - [`Gauge`](https://prometheus.github.io/client_python/instrumenting/gauge/): goes up and down;
    `crew_runs_in_progress`.
  - [`Histogram`](https://prometheus.github.io/client_python/instrumenting/histogram/): counts durations into buckets
    (`SECONDS`), so a percentile can be computed from it later.
- **[Labels](https://prometheus.github.io/client_python/instrumenting/labels/)**:  
  One series per value: `agent`, `status` (`ok` or `error`), `tool`, `direction` (tokens in or out).
- **`start_http_server(8000)`**:  
  Serves every metric at `http://crew:8000/metrics`, in a thread of its own
  ([exporting over HTTP](https://prometheus.github.io/client_python/exporting/http/)).
- **`record(step)`**:  
  Counts a step and records its duration when it ends; a run's start raises `crew_runs_in_progress`.
- **A metric names no run**: it adds them all up, so finding one run takes a trace or a log line.

## `heartbeat.py` and `health.py`: the watchdog's two inputs

The watchdog learns about the crew in two ways, and each comes from one file.

- **[`heartbeat.py`](crew/observe/heartbeat.py)**:  
  After every step, a short message to the watchdog: "I just did something".
  - A JSON `POST` to `$WATCHDOG_URL/heartbeat`, in a thread of its own, with a 1 s timeout.
  - It carries the run's trace ID, which the watchdog puts in its alerts.
  - `WATCHDOG_URL` is empty before stage 5, so nothing is sent.
- **[`health.py`](crew/observe/health.py)**:  
  An HTTP server on port 8001, in a thread of its own
  ([`http.server`](https://docs.python.org/3/library/http.server.html)).
  - It answers `/health` with `200` for as long as the process runs.
  - It says the process is alive, not that it is making progress: the heartbeats say that.

## The OpenTelemetry Collector

[`stack/opentelemetry-collector.yaml`](stack/opentelemetry-collector.yaml) receives what the crew's SDK sends and
passes each signal to its store ([configuration](https://opentelemetry.io/docs/collector/configuration/)).

- **`receivers`**: `otlp`, on 4317 (gRPC) and 4318 (HTTP, the one the crew uses).
- **`processors`**:
  - [`batch`](https://github.com/open-telemetry/opentelemetry-collector/tree/main/processor/batchprocessor): sends on
    in batches.
  - [`attributes/no-code`](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/attributesprocessor):
    deletes the Python file, function and line number the SDK adds to every log line.
- **`exporters`**: the spans to Jaeger (OTLP over gRPC), the log lines to Loki's OTLP endpoint, `/otlp`.
- **`pipelines`**: `traces` and `logs`. There is no `metrics` pipeline: the metrics go from the crew straight to
  Prometheus.

## The stores: Jaeger, Loki, Prometheus

- **[Jaeger](https://www.jaegertracing.io/docs/2.20/)**:  
  A database for traces, with its own UI.
  - Pinned to 2.20.0 in [`compose.yaml`](compose.yaml): the last release serving the HTTP API that Grafana's Jaeger
    source searches with (`/api/services`, `/api/traces`).
  - It keeps the traces in memory: a restart drops them.
- **[Loki](https://grafana.com/docs/loki/latest/)**:  
  A database for log lines only. [`stack/loki.yaml`](stack/loki.yaml) runs one process, on its own disk.
  - It indexes each line's labels, never its text. A line sent over OTLP gets `service_name` from the SDK's
    `service.name` ([Loki and OpenTelemetry](https://grafana.com/docs/loki/latest/send-data/otel/)).
  - `allow_structured_metadata: true`: the line's `trace_id` and `span_id` are kept beside it, not in its text
    ([structured metadata](https://grafana.com/docs/loki/latest/get-started/labels/structured-metadata/)).
- **[Prometheus](https://prometheus.io/docs/)**:  
  A collector and database for metrics.
  - [`stack/prometheus.yml`](stack/prometheus.yml) fetches `crew:8000/metrics` and `watchdog:9001/metrics` every 5 s
    ([scrape configuration](https://prometheus.io/docs/prometheus/latest/configuration/configuration/)).

## Grafana

[`stack/grafana/`](stack/grafana) is Grafana's provisioning: the files Grafana reads at startup, so it opens set up
([provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)).

- **[`datasources/datasources.yaml`](stack/grafana/datasources/datasources.yaml)**: the three stores, and the links
  between them.
  - Loki's `derivedFields`: a log line's `trace_id` opens its trace in Jaeger
    ([Loki source](https://grafana.com/docs/grafana/latest/datasources/loki/configure/)).
  - Jaeger's `tracesToLogsV2`: a span's *Related logs* asks Loki for the lines with its trace ID
    ([Jaeger source](https://grafana.com/docs/grafana/latest/datasources/jaeger/configure/)).
    - The query filters on the field, `| trace_id="…"`: Loki keeps the ID beside the line, so a text search finds
      nothing.
- **[`dashboards/crew.json`](stack/grafana/dashboards/crew.json)**: the dashboard *The crew*, Grafana's home page.

## The watchdog

[`watchdog/watchdog.py`](watchdog/watchdog.py) is a separate program, in a container of its own, that watches the
crew and acts when something is wrong.

- **What it learns**:
  - Health checks: every 3 s it asks `http://crew:8001/health`, with a 2 s timeout.
  - Heartbeats: the crew posts them to its port 9000.
- **The four problems, and the decision for each**:
  - No answer to 3 health checks in a row: restart the crew.
  - No heartbeat for 20 s during a run: restart the crew.
  - A run longer than 12 s: alert (it is slow, not stuck).
  - 3 failed runs in 120 s: alert (the crew already retried).
  - A restart due after 3 restarts in 300 s: stop the crew and alert, since restarting is not helping.
- **How it acts**: through Docker's own API, on `/var/run/docker.sock`, mounted into its container
  ([Docker Engine API](https://docs.docker.com/reference/api/engine/)).
  - `POST /containers/crew/restart?t=2` and `/stop?t=2`: Docker sends SIGTERM, then kills after 2 s.
- **Its alerts are lines on its stdout**: `docker compose logs -f watchdog`.
  - It also counts them, with its restarts and the last heartbeat's time, at `watchdog:9001/metrics`; Prometheus
    fetches them, and the dashboard shows them.
