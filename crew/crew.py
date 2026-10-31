"""The crew: four agents, each doing its task in turn."""

from crewai import Crew, Process

from agents.planner import planner, plan
from agents.researcher import researcher, research
from agents.writer import writer, write
from agents.reviewer import reviewer, review

crew = Crew(
    agents=[planner, researcher, writer, reviewer],
    tasks=[plan, research, write, review],
    process=Process.sequential,
)
