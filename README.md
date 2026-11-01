# agentmon: observing a crew of AI agents

**[Agent Monitoring: a Crew Observed](https://www.yuval.guide/ai/agent-monitoring/agent-monitoring-crew/)** is an
interactive viewer that replays this repository, stage by stage: what each program does, and what to look for.

A small [CrewAI](https://docs.crewai.com/) crew of four agents, and the programs that observe it:
its logs, traces and metrics, a Grafana dashboard, and a watchdog.
Everything runs on one machine, with Docker Compose, and is read in a local browser.

## What runs

- **The crew** (`crew/`): four agents working in turn on one topic after another.
  - Planner → Researcher (with a `search` tool) → Writer → Reviewer.
  - One agent per file, in `crew/agents/`.
  - It always makes its logs, spans and metrics: `crew/observe/`, one file per signal.
- **The world outside** (`world/`): 
  - a fake model API
  - a fake search API
  - They answer like the real thing, cost nothing, and can be broken on purpose.
- **The programs that observe the crew**, each in its own container, each called by its product name:
  - [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/): receives the crew's traces and logs.
  - [Jaeger](https://www.jaegertracing.io/docs/): stores and shows the traces.
  - [Loki](https://grafana.com/docs/loki/latest/): stores the log lines.
  - [Prometheus](https://prometheus.io/docs/): fetches and stores the metrics.
  - [Grafana](https://grafana.com/docs/grafana/latest/): reads all three.
- **The watchdog** (`watchdog/`): health checks, heartbeats, restarts and alerts.

## Trying it yourself

You need Docker with Compose, and nothing else: no API key, no internet once the images are downloaded.

1. Clone this repository and go into it.
2. Run `./operator/stage 1`, and watch the crew's log lines with `docker compose logs -f crew`.
3. Go on with stages 2 to 5, then break things with `./operator/fault`.

[`operator/README.md`](operator/README.md) is the guide: what each stage adds, what to open, and what
each fault does and where it shows.

## Running it

Docker with Compose is all it needs. From this directory:

```bash
./operator/stage 5              # everything; or 1-4 for fewer programs (see below)
docker compose logs -f crew     # the crew's log lines
```

| Stage | Programs added | Open |
| --- | --- | --- |
| 1 | the crew alone | `docker compose logs -f crew` |
| 2 | Collector, Jaeger, Loki | http://localhost:16686 (Jaeger) |
| 3 | Prometheus | http://localhost:8000/metrics (the crew's numbers), http://localhost:9090 |
| 4 | Grafana | http://localhost:3000 |
| 5 | the watchdog | `docker compose logs -f watchdog` |

The crew's code is the same at every stage: a stage only starts the programs that collect what the
crew already makes. `operator/stages/*.env` holds each stage's settings.

`./operator/fault` breaks things on purpose: a slow or failing search, a model that never answers,
a frozen crew. `docker compose --profile '*' down` stops everything.

## Calling each service

Every address below is on this machine. A service with no port here is reached only by the other
containers, by its service name (`http://loki:3100`).

- **The crew** sets its own work: `main.py` runs the crew on each topic in `TOPICS`, one run every
  `RUN_EVERY` seconds (5), round and round. To give it other topics, edit `TOPICS` and run the stage again.
  - `curl localhost:8001/health`: `{"status": "ok"}` while the process runs.
  - `curl localhost:8000/metrics`: its counts and durations, as Prometheus reads them.
- **The model API**, port 8081: OpenAI's chat completions format. The agent is found by its role in
  the system message.
  ```bash
  curl -s localhost:8081/v1/chat/completions -d '{"model": "sim-1", "messages": [
    {"role": "system", "content": "You are the Planner."},
    {"role": "user", "content": "Plan it.\nTopic: bees"}]}'
  ```
- **The search API**, port 8082: `curl 'localhost:8082/search?q=bees'`.
- **Both fake APIs** take a fault: `curl localhost:8081/fault` shows it, and
  `curl -X POST localhost:8081/fault -d '{"mode": "slow"}'` sets it (`ok`, `slow`, `error`, `hang`).
  `operator/fault` does this for you.
- **The OpenTelemetry Collector**: no port here. The crew sends it OTLP at
  `http://opentelemetry-collector:4318` (HTTP; gRPC on 4317), and it passes the spans to Jaeger and the
  log lines to Loki.
- **Jaeger**, port 16686: the UI at http://localhost:16686. Its API:
  - `curl localhost:16686/api/v3/services`: the services that sent spans (`crew`).
  - `curl localhost:16686/api/v3/traces/<trace_id>`: one trace, by the ID in a log line.
- **Loki**: no port here. Read its log lines in Grafana (Explore → Loki, `{service_name="crew"}`).
- **Prometheus**, port 9090: the UI at http://localhost:9090, or its API:
  `curl 'localhost:9090/api/v1/query?query=crew_runs_total'`.
- **Grafana**, port 3000: http://localhost:3000, no login; it opens on the dashboard *The crew*.
- **The watchdog**: no port here; read it with `docker compose logs -f watchdog`.
  - The crew posts its heartbeats to `http://watchdog:9000/heartbeat`.
  - Prometheus reads its numbers from `http://watchdog:9001/metrics`.

## Reading the code

[`CODE.md`](CODE.md) goes through the monitoring, file by file: what each piece does, and the documentation
it rests on.
