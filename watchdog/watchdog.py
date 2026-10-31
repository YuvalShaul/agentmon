"""The watchdog: a separate program that watches the crew and acts when something is wrong.

It learns about the crew two ways:
  - health checks: every few seconds it asks http://crew:8001/health "are you alive?"
  - heartbeats: the crew tells it after every step "I just did something"

It finds four problems, and decides for each whether to recover, stop or alert:

  problem                                        found by        decision
  the crew does not answer its health check      health check    restart the crew
  a run made no progress for HEARTBEAT_TIMEOUT   heartbeats      restart the crew
  a run takes longer than RUN_TIMEOUT            heartbeats      alert (it is slow, not stuck)
  runs keep failing                              heartbeats      alert (the crew already retried)

Restarting is retried MAX_RESTARTS times in RESTART_WINDOW; after that a restart
is not helping, so it stops the crew and alerts a person.
"""

import json
import os
import socket
import threading
import time
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

from prometheus_client import Counter, Gauge, start_http_server

CREW_HEALTH = os.environ.get("CREW_HEALTH", "http://crew:8001/health")
CREW_CONTAINER = os.environ.get("CREW_CONTAINER", "crew")
CHECK_EVERY = 3            # seconds between health checks
HEALTH_FAILURES = 3        # failed health checks in a row before acting
HEARTBEAT_TIMEOUT = 20     # seconds a run may go without a heartbeat
RUN_TIMEOUT = 12           # seconds a run may take
FAILED_RUNS = 3            # failed runs in FAILURE_WINDOW before alerting
FAILURE_WINDOW = 120
MAX_RESTARTS = 3           # restarts in RESTART_WINDOW before giving up
RESTART_WINDOW = 300

alerts = Counter("watchdog_alerts", "Alerts sent to a person", ["problem"])
restarts = Counter("watchdog_restarts", "Times the watchdog restarted the crew")
last_heartbeat = Gauge("watchdog_last_heartbeat_timestamp_seconds", "When the crew last sent a heartbeat")
crew_up = Gauge("watchdog_crew_up", "1 if the crew answered its last health check")


def say(text):
    print(f"{time.strftime('%H:%M:%S')} {text}", flush=True)


# --- what the watchdog knows ------------------------------------------------------------

state = {
    "run_started": None,     # when the run in progress started, or None
    "trace_id": "",          # the run's trace ID, to find it in Jaeger
    "last_beat": None,       # when the last heartbeat arrived
    "last_step": "",         # what the crew said it did last
    "failed_runs": [],       # when recent runs failed
    "restarts": [],          # when we restarted the crew
    "health_failures": 0,    # failed health checks in a row
    "alerted": set(),        # problems alerted and not over yet
    "stopped": False,        # we gave up and stopped the crew
}


def on_heartbeat(beat):
    now = time.time()
    state["last_beat"] = now
    last_heartbeat.set(now)
    state["last_step"] = " ".join(x for x in (beat["agent"], beat["kind"], beat["name"], beat["phase"]) if x)
    if beat["kind"] == "crew" and beat["phase"] == "start":
        state["run_started"] = now
        state["trace_id"] = beat["trace_id"]
        state["alerted"] -= {"too_slow", "no_progress"}   # those were about the last run
    elif beat["kind"] == "crew":
        state["run_started"] = None
        if beat["phase"] == "error":
            state["failed_runs"].append(now)


class Heartbeats(BaseHTTPRequestHandler):
    def do_POST(self):
        on_heartbeat(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


# --- the checks -------------------------------------------------------------------------

def healthy():
    try:
        with urlopen(CREW_HEALTH, timeout=2) as reply:
            return reply.status == 200
    except OSError:
        return False


def problems():
    """Every problem found now: (name, what is wrong)."""
    now = time.time()
    found = []
    if healthy():
        state["health_failures"] = 0
        crew_up.set(1)
    else:
        state["health_failures"] += 1
        crew_up.set(0)
        if state["health_failures"] >= HEALTH_FAILURES:
            found.append(("not_responding", f"the crew failed {state['health_failures']} health checks in a row"))
    running = state["run_started"]
    if running and now - state["last_beat"] > HEARTBEAT_TIMEOUT:
        found.append(("no_progress", f"no heartbeat for {now - state['last_beat']:.0f} s, "
                                     f"last step: {state['last_step']}, trace {state['trace_id']}"))
    if running and now - running > RUN_TIMEOUT:
        found.append(("too_slow", f"the run has taken {now - running:.0f} s, trace {state['trace_id']}"))
    state["failed_runs"] = [t for t in state["failed_runs"] if now - t < FAILURE_WINDOW]
    if len(state["failed_runs"]) < FAILED_RUNS:
        state["alerted"].discard("failing")               # over: alert again next time
    else:
        found.append(("failing", f"{len(state['failed_runs'])} runs failed in {FAILURE_WINDOW} s"))
    return found


# --- the decisions ----------------------------------------------------------------------

def decide(problem):
    """recover, or alert. A recovery that keeps failing turns into stop."""
    if problem in ("not_responding", "no_progress"):
        return "recover"
    return "alert"


def alert(problem, text):
    if problem in state["alerted"]:
        return
    state["alerted"].add(problem)
    alerts.labels(problem).inc()
    say(f"ALERT {problem}: {text}")


def recover(problem, text):
    now = time.time()
    state["restarts"] = [t for t in state["restarts"] if now - t < RESTART_WINDOW]
    if len(state["restarts"]) >= MAX_RESTARTS:
        stop(problem, text)
        return
    say(f"RESTART {problem}: {text}")
    state["restarts"].append(now)
    restarts.inc()
    docker("POST", f"/containers/{CREW_CONTAINER}/restart?t=2")
    state.update(run_started=None, last_beat=None, health_failures=0)


def stop(problem, text):
    say(f"STOP {problem}: {text}; {MAX_RESTARTS} restarts in {RESTART_WINDOW} s did not help")
    docker("POST", f"/containers/{CREW_CONTAINER}/stop?t=2")
    state["stopped"] = True
    alert("gave_up", f"stopped the crew after {MAX_RESTARTS} restarts: {text}")


def docker(method, path):
    """Ask Docker to act on a container, through its socket."""
    class DockerSocket(HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX)
            self.sock.connect("/var/run/docker.sock")
    connection = DockerSocket("docker", timeout=30)
    connection.request(method, path)
    status = connection.getresponse().status
    if status >= 300:
        say(f"docker {path}: {status}")


# --- the loop ---------------------------------------------------------------------------

start_http_server(9001)
threading.Thread(target=ThreadingHTTPServer(("", 9000), Heartbeats).serve_forever, daemon=True).start()
say("watching the crew")
while not state["stopped"]:
    for problem, text in problems():
        if decide(problem) == "recover":
            recover(problem, text)
            break
        alert(problem, text)
    time.sleep(CHECK_EVERY)
say("stopped watching: a person has to look")
while True:
    time.sleep(3600)
