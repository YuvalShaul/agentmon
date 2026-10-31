"""The researcher's tool: a web search API at SEARCH_API."""

import json
import os
from urllib.parse import quote
from urllib.request import urlopen

from crewai.tools import tool


@tool("search")
def search(query: str) -> str:
    """Search the web and return the top results."""
    with urlopen(f"{os.environ['SEARCH_API']}/search?q={quote(query)}", timeout=10) as reply:
        return "\n".join(json.load(reply)["results"])
