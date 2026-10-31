from crewai import Agent, Task

from llm import model
from tools.search import search

researcher = Agent(
    role="Researcher",
    goal="Find facts with the search tool",
    backstory="You look things up before you answer.",
    tools=[search],
    llm=model,
)

research = Task(
    description="Find three facts. Topic: {topic}",
    expected_output="Three facts",
    agent=researcher,
)
