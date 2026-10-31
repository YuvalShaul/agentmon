"""The crew at work: it takes one request after another and runs the crew on each.

If a run fails, it tries again, up to three times, waiting longer each time.
"""

import itertools
import logging
import os
import time

from crewai.events import crewai_event_bus

import observe  # noqa: F401  (the monitoring: logs, traces, metrics, heartbeats)
from crew import crew

TOPICS = ["bees", "volcanoes", "the moon", "coffee", "glaciers", "octopuses"]
RUN_EVERY = float(os.environ.get("RUN_EVERY", "5"))
ATTEMPTS = 3

log = logging.getLogger("crew")


def run(topic):
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return crew.kickoff(inputs={"topic": topic})
        except Exception as error:
            crewai_event_bus.flush()   # let the run's own log lines come first
            log.warning(f"attempt {attempt} of {ATTEMPTS} failed: {error}")
            if attempt < ATTEMPTS:
                time.sleep(2 ** attempt)   # wait 2 s, then 4 s
    log.error(f"gave up on topic={topic} after {ATTEMPTS} attempts")


for topic in itertools.cycle(TOPICS):
    run(topic)
    time.sleep(RUN_EVERY)
