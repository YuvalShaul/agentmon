"""Traces: one span per step, each inside the span of the step that started it.

A run of the crew is one trace:
    crew.kickoff
      invoke_agent Planner
        chat sim-1
      invoke_agent Researcher
        chat sim-1
        execute_tool search
        chat sim-1
      ...
The OpenTelemetry SDK sends each span when it ends, to wherever
OTEL_TRACES_EXPORTER says (set in compose.yaml).
"""

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

tracer = trace.get_tracer("crew")
spans = {}   # step id -> its span


def span_name(step):
    if step.kind == "crew":
        return "crew.kickoff"
    if step.kind == "agent":
        return f"invoke_agent {step.agent}"
    if step.kind == "llm":
        return f"chat {step.name}"
    return f"execute_tool {step.name}"


def attributes(step):
    # The names come from OpenTelemetry's conventions for AI ("gen_ai.*").
    found = {"crew.topic": step.name} if step.kind == "crew" else {}
    if step.agent:
        found["gen_ai.agent.name"] = step.agent
    if step.kind == "llm":
        found["gen_ai.operation.name"] = "chat"
        found["gen_ai.request.model"] = step.name
    if step.kind == "tool":
        found["gen_ai.operation.name"] = "execute_tool"
        found["gen_ai.tool.name"] = step.name
    return found


def ns(at):
    return int(at.timestamp() * 1e9)


def record(step):
    if step.phase == "start":
        if step.kind == "crew":
            spans.clear()                 # a new run: forget the last one's spans
        parent = spans.get(step.parent)
        if step.kind == "inner":
            spans[step.id] = parent       # no span of its own
            return
        context = trace.set_span_in_context(parent) if parent else None
        spans[step.id] = tracer.start_span(span_name(step), context=context,
                                           start_time=ns(step.at), attributes=attributes(step))
        return
    span = spans.get(step.started)
    if step.kind == "inner" or span is None:
        return
    if step.tokens:
        span.set_attribute("gen_ai.usage.input_tokens", step.tokens.get("prompt_tokens", 0))
        span.set_attribute("gen_ai.usage.output_tokens", step.tokens.get("completion_tokens", 0))
    if step.phase == "error":
        span.set_status(Status(StatusCode.ERROR, step.error))
        span.add_event("exception", {"exception.message": step.error})
    span.end(end_time=ns(step.at))


def span_of(step):
    """The span a step happened in: its own, or the one it is inside."""
    return spans.get(step.started) or spans.get(step.id) or spans.get(step.parent)
