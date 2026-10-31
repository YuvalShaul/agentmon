from crewai import Agent, Task

from llm import model

planner = Agent(
    role="Planner",
    goal="Split the request into steps",
    backstory="You plan short research reports.",
    llm=model,
)

plan = Task(
    description="Plan a short report. Topic: {topic}",
    expected_output="A numbered plan",
    agent=planner,
)
