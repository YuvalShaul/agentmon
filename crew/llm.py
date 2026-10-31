"""The model every agent uses: an OpenAI-compatible API at MODEL_API."""

import os

from crewai import LLM

model = LLM(model="openai/sim-1", base_url=os.environ["MODEL_API"], api_key="not-needed")
