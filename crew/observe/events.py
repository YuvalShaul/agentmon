"""CrewAI announces every step it takes as an event: "agent started", "tool finished", ...

We listen to the events, turn each into a Step, and hand it to each signal in turn.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from crewai.events import BaseEventListener
from crewai.events.types.agent_events import AgentExecutionCompletedEvent, AgentExecutionErrorEvent, AgentExecutionStartedEvent
from crewai.events.types.crew_events import CrewKickoffCompletedEvent, CrewKickoffFailedEvent, CrewKickoffStartedEvent
from crewai.events.types.flow_events import FlowFailedEvent, FlowFinishedEvent, FlowStartedEvent
from crewai.events.types.llm_events import LLMCallCompletedEvent, LLMCallFailedEvent, LLMCallStartedEvent
from crewai.events.types.task_events import TaskCompletedEvent, TaskFailedEvent, TaskStartedEvent
from crewai.events.types.tool_usage_events import ToolUsageErrorEvent, ToolUsageFinishedEvent, ToolUsageStartedEvent

from observe import heartbeat, logs, metrics, traces

# Each event: what kind of step it is about, and whether the step starts, ends or fails.
# "inner" steps are CrewAI's own bookkeeping (a task, the agent's internal flow): they
# get no span of their own; what happens inside them belongs to the step above.
KINDS = {
    CrewKickoffStartedEvent: ("crew", "start"),
    CrewKickoffCompletedEvent: ("crew", "end"),
    CrewKickoffFailedEvent: ("crew", "error"),
    AgentExecutionStartedEvent: ("agent", "start"),
    AgentExecutionCompletedEvent: ("agent", "end"),
    AgentExecutionErrorEvent: ("agent", "error"),
    LLMCallStartedEvent: ("llm", "start"),
    LLMCallCompletedEvent: ("llm", "end"),
    LLMCallFailedEvent: ("llm", "error"),
    ToolUsageStartedEvent: ("tool", "start"),
    ToolUsageFinishedEvent: ("tool", "end"),
    ToolUsageErrorEvent: ("tool", "error"),
    TaskStartedEvent: ("inner", "start"),
    TaskCompletedEvent: ("inner", "end"),
    TaskFailedEvent: ("inner", "error"),
    FlowStartedEvent: ("inner", "start"),
    FlowFinishedEvent: ("inner", "end"),
    FlowFailedEvent: ("inner", "error"),
}


@dataclass
class Step:
    kind: str              # crew, agent, llm, tool or inner
    phase: str             # start, end or error
    id: str                # this event's id
    parent: str | None     # the id of the step this one happens inside
    started: str | None    # for an end or error: the id of the step's start
    at: datetime
    agent: str = ""        # the agent's role: Planner, Researcher, ...
    name: str = ""         # the model, the tool, or the run's topic
    seconds: float = 0.0   # for an end or error: how long the step took
    tokens: dict = field(default_factory=dict)
    error: str = ""


started = {}   # step id -> (kind, when it started)


def to_step(event):
    """The event as a Step, or None for an end that does not match its start
    (CrewAI sometimes reports one failure twice)."""
    kind, phase = KINDS[type(event)]
    if phase != "start" and started.get(event.started_event_id, (kind,))[0] != kind:
        return None
    agent = getattr(event, "agent", None)
    step = Step(kind, phase, event.event_id, event.parent_event_id, event.started_event_id, event.timestamp,
                agent=event.agent_role or getattr(agent, "role", "") or "",
                name=getattr(event, "tool_name", None) or getattr(event, "model", None) or "",
                tokens=getattr(event, "usage", None) or {},
                error=str(getattr(event, "error", "") or ""))
    if kind == "crew" and phase == "start":
        step.name = (event.inputs or {}).get("topic", "")
    if phase == "start":
        started[step.id] = (kind, step.at)
    else:
        step.seconds = (step.at - started.pop(step.started, (kind, step.at))[1]).total_seconds()
    return step


class Listener(BaseEventListener):
    def setup_listeners(self, bus):
        for event_type in KINDS:
            # An async handler: CrewAI runs them one at a time, in the order the events happened.
            @bus.on(event_type)
            async def on_event(source, event):
                try:
                    step = to_step(event)
                    if step is None:
                        return
                    traces.record(step)
                    logs.record(step)
                    metrics.record(step)
                    heartbeat.record(step)
                except Exception:
                    logging.getLogger("observe").exception("could not record %s", event.type)


Listener()
