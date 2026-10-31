"""The monitoring: CrewAI's events, turned into logs, traces, metrics and heartbeats,
and a health check.

Importing this package is all main.py does. The agents' code knows nothing about it.
"""

from observe import events, health  # noqa: F401  (starts listening and answering)
