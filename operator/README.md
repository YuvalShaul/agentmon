# Operating the demo

Two commands, run from anywhere:

- `./stage <1-5>`: starts the programs of that stage and stops the others.
- `./fault <target> <mode>`: breaks something on purpose.

Nothing here is the crew's code: the crew never asks which stage it is in.

To stop everything: `docker compose --profile '*' down`, from the repository's top directory.

## The stages

1. **Logs.** `docker compose logs -f crew`.
   - Each line carries `trace_id` and `span_id`: nothing reads them yet.
2. **Traces.** Jaeger, http://localhost:16686, service `crew`.
   - One trace per run: `crew.kickoff` → `invoke_agent <agent>` → `chat sim-1` / `execute_tool search`.
   - The log lines now also go to Loki, through the Collector.
3. **Metrics.** http://localhost:8000/metrics is the crew's own page of numbers.
   - Prometheus, http://localhost:9090, fetches it every 5 s: try `rate(crew_runs_total[1m])`.
4. **Grafana.** http://localhost:3000, the dashboard *The crew*.
   - A log line's `trace_id` opens its trace in Jaeger.
5. **The watchdog.** `docker compose logs -f watchdog`.

## The faults

| Command | What happens | Who sees it |
| --- | --- | --- |
| `./fault search slow` | each search takes 8 s | the trace (a long `execute_tool search`); the watchdog alerts `too_slow` |
| `./fault search error` | each search answers 503 | an ERROR log line and a red span; the run still "finishes" without facts |
| `./fault search hang` | the search never answers | the tool's 10 s timeout ends it: as above, 10 s later |
| `./fault model error` | the model answers 503 | runs fail; `main.py` retries 3 times; the watchdog alerts `failing` |
| `./fault model hang` | the model never answers | the heartbeats stop; the watchdog restarts the crew 3 times, then stops it and alerts |
| `./fault crew freeze` | the crew's process is paused | the health check fails; the watchdog restarts the crew |
| `./fault clear` | everything back to normal | |

After the watchdog stops the crew: `./fault clear`, then `./stage 5` again.

A hung run's spans are never sent: a span is sent when it ends. Its log lines, up to the last step, are
in Loki, and the watchdog's alert names its trace ID.
