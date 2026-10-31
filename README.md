# agentmon: observing a crew of AI agents

A small [CrewAI](https://docs.crewai.com/) crew of four agents, and the programs that observe it:
its logs, traces and metrics, a Grafana dashboard, and a watchdog.
Everything runs on one machine, with Docker Compose, and is read in a local browser.

## What runs

- **The crew** (`crew/`): four agents working in turn on one topic after another.
  - Planner → Researcher (with a `search` tool) → Writer → Reviewer.
  - One agent per file, in `crew/agents/`.
  - It always makes its logs, spans and metrics: `crew/observe/`, one file per signal.
- **The world outside** (`world/`): a fake model API and a fake search API.
  - They answer like the real thing, cost nothing, and can be broken on purpose.
- **The programs that observe the crew**, each in its own container, each called by its product name:
  - [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/): receives the crew's traces and logs.
  - [Jaeger](https://www.jaegertracing.io/docs/): stores and shows the traces.
  - [Loki](https://grafana.com/docs/loki/latest/): stores the log lines.
  - [Prometheus](https://prometheus.io/docs/): fetches and stores the metrics.
  - [Grafana](https://grafana.com/docs/grafana/latest/): reads all three.
- **The watchdog** (`watchdog/`): health checks, heartbeats, restarts and alerts.

## Running it

Docker with Compose is all it needs. From this directory:

```bash
./instructor/stage 5            # everything; or 1-4 for fewer programs (see below)
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
crew already makes. `instructor/stages/*.env` holds each stage's settings.

`./instructor/fault` breaks things on purpose: a slow or failing search, a model that never answers,
a frozen crew. `docker compose --profile '*' down` stops everything.

## Reading the code

- `crew/main.py`: takes one topic after another, retrying a failed run.
- `crew/crew.py`: puts the four agents together.
- `crew/agents/*.py`: one agent and its task each.
- `crew/observe/events.py`: CrewAI announces every step as an event; this hands each to the signals.
  - `traces.py`: one span per step, inside the span of the step that started it.
  - `logs.py`: one log line per step, with the step's trace ID and span ID.
  - `metrics.py`: counts and durations, served at `/metrics`.
  - `heartbeat.py`: tells the watchdog after every step that the crew is making progress.
  - `health.py`: answers `/health` while the process runs.
- `watchdog/watchdog.py`: finds four problems and decides for each: restart, stop or alert.
