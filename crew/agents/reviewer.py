from crewai import Agent, Task

from llm import model

reviewer = Agent(
    role="Reviewer",
    goal="Check the paragraph against the facts",
    backstory="You approve or reject.",
    llm=model,
)

review = Task(
    description="Review the paragraph. Topic: {topic}",
    expected_output="Approved or rejected, with one reason",
    agent=reviewer,
)
