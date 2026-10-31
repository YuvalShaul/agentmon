"""Metrics: counts and durations, served at http://crew:8000/metrics for Prometheus to fetch.

A metric adds up every run; it cannot name one. Each line it serves is
  name{labels} value
"""

from prometheus_client import Counter, Gauge, Histogram, start_http_server

SECONDS = (0.1, 0.5, 1, 2, 5, 10, 20, 30, 60, 120)

runs = Counter("crew_runs", "Runs of the crew, by how they ended", ["status"])
runs_in_progress = Gauge("crew_runs_in_progress", "Runs started and not yet ended")
run_seconds = Histogram("crew_run_duration_seconds", "How long a run took", buckets=SECONDS)
agent_runs = Counter("agent_runs", "Agent steps, by agent and how they ended", ["agent", "status"])
agent_seconds = Histogram("agent_duration_seconds", "How long an agent took", ["agent"], buckets=SECONDS)
llm_calls = Counter("llm_calls", "Calls to the model, by agent and how they ended", ["agent", "status"])
llm_seconds = Histogram("llm_call_duration_seconds", "How long the model took to answer", ["agent"], buckets=SECONDS)
llm_tokens = Counter("llm_tokens", "Tokens sent to and received from the model", ["agent", "direction"])
tool_calls = Counter("tool_calls", "Tool calls, by tool and how they ended", ["tool", "status"])
tool_seconds = Histogram("tool_call_duration_seconds", "How long a tool took", ["tool"], buckets=SECONDS)

start_http_server(8000)


def record(step):
    status = "ok" if step.phase == "end" else "error"
    if step.kind == "crew":
        if step.phase == "start":
            runs_in_progress.inc()
            return
        runs_in_progress.dec()
        runs.labels(status).inc()
        run_seconds.observe(step.seconds)
    elif step.phase == "start":
        return
    elif step.kind == "agent":
        agent_runs.labels(step.agent, status).inc()
        agent_seconds.labels(step.agent).observe(step.seconds)
    elif step.kind == "llm":
        llm_calls.labels(step.agent, status).inc()
        llm_seconds.labels(step.agent).observe(step.seconds)
        llm_tokens.labels(step.agent, "input").inc(step.tokens.get("prompt_tokens", 0))
        llm_tokens.labels(step.agent, "output").inc(step.tokens.get("completion_tokens", 0))
    elif step.kind == "tool":
        tool_calls.labels(step.name, status).inc()
        tool_seconds.labels(step.name).observe(step.seconds)
