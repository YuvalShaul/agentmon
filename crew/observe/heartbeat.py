"""Heartbeats: after every step, the crew tells the watchdog it is still making progress.

A heartbeat says "I just did something". When a step hangs, the heartbeats stop,
even though the process is still alive. Sent only if WATCHDOG_URL is set.
"""

import json
import os
import threading
from urllib.request import Request, urlopen

from observe import traces

WATCHDOG_URL = os.environ.get("WATCHDOG_URL")


def send(beat):
    try:
        urlopen(Request(f"{WATCHDOG_URL}/heartbeat", json.dumps(beat).encode(),
                        {"Content-Type": "application/json"}), timeout=1)
    except OSError:
        pass   # no watchdog running: nobody is listening


def record(step):
    if not WATCHDOG_URL or step.kind == "inner":
        return
    span = traces.span_of(step)
    trace_id = f"{span.get_span_context().trace_id:032x}" if span else ""
    beat = {"kind": step.kind, "phase": step.phase, "agent": step.agent, "name": step.name,
            "error": step.error, "trace_id": trace_id}
    threading.Thread(target=send, args=(beat,), daemon=True).start()
