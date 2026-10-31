"""Logs: one line per step, carrying the trace ID and span ID of the step.

The lines go to stdout (docker compose logs crew). The OpenTelemetry SDK also
sends them to wherever OTEL_LOGS_EXPORTER says, with the same IDs.
"""

import logging
import sys

from opentelemetry import trace

from observe import traces

log = logging.getLogger("crew")
log.setLevel(logging.INFO)
to_stdout = logging.StreamHandler(sys.stdout)
to_stdout.setFormatter(logging.Formatter(
    "%(asctime)s %(levelname)-5s trace_id=%(trace_id)s span_id=%(span_id)s %(message)s"))


def no_ids(record):
    """A line written outside any step (main.py's retries) has no IDs: show '-'."""
    record.__dict__.setdefault("trace_id", "-")
    record.__dict__.setdefault("span_id", "-")
    return True


to_stdout.addFilter(no_ids)
log.addHandler(to_stdout)
logging.getLogger("crewai").setLevel(logging.ERROR)


def message(step):
    who = step.agent
    if step.kind == "crew":
        return {"start": f"run started: topic={step.name}",
                "end": f"run finished in {step.seconds:.1f} s",
                "error": f"run failed after {step.seconds:.1f} s: {step.error}"}[step.phase]
    if step.kind == "agent":
        return {"start": f"{who} started",
                "end": f"{who} finished in {step.seconds:.1f} s",
                "error": f"{who} failed: {step.error}"}[step.phase]
    if step.kind == "llm":
        return {"start": f"{who} asks the model",
                "end": f"{who} got the model's answer in {step.seconds:.1f} s, "
                       f"{step.tokens.get('total_tokens', 0)} tokens",
                "error": f"{who}'s model call failed after {step.seconds:.1f} s: {step.error}"}[step.phase]
    if step.kind == "tool":
        return {"start": f"{who} calls {step.name}",
                "end": f"{step.name} answered {who} in {step.seconds:.1f} s",
                "error": f"{step.name} failed for {who} after {step.seconds:.1f} s: {step.error}"}[step.phase]
    return None


def record(step):
    text = message(step)
    if not text:
        return
    span = traces.span_of(step) or trace.INVALID_SPAN
    ids = span.get_span_context()
    with trace.use_span(span):
        log.log(logging.ERROR if step.phase == "error" else logging.INFO, text,
                extra={"trace_id": f"{ids.trace_id:032x}", "span_id": f"{ids.span_id:016x}"})
