from crewai import Agent, Task

from llm import model

writer = Agent(
    role="Writer",
    goal="Write a short paragraph from the facts",
    backstory="You write plainly.",
    llm=model,
)

write = Task(
    description="Write one paragraph from the facts. Topic: {topic}",
    expected_output="One paragraph",
    agent=writer,
)
