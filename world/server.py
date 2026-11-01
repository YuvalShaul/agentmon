"""The world outside the crew: a model API and a search API, both fake.

One program, two roles: compose runs it twice, as model-api and search-api.
Each answers at once, costs nothing and gives the same answer every time.
The operator flips a fault switch with POST /fault {"mode": "ok" | "slow" | "error" | "hang"}:

  slow   every answer takes SLOW_SECONDS
  error  every answer is 503 Service Unavailable
  hang   no answer at all: the connection stays open until the mode changes

Not the crew's code: in real life these are someone else's services.
"""

import json
import logging
import os
import time

from flask import Flask, jsonify, request

ROLE = os.environ.get("ROLE", "model")
SLOW_SECONDS = float(os.environ.get("SLOW_SECONDS", "8"))

# How long a healthy answer takes, in seconds: the writer's answers are the longest.
THINK = {"Planner": 0.6, "Researcher": 0.5, "Writer": 1.6, "Reviewer": 0.7}
SEARCH_SECONDS = 0.4

# What each agent writes, found by its role in the system prompt.
ANSWERS = {
    "Planner": "Plan: 1. find three facts on {topic}. 2. write a short paragraph. 3. check it.",
    "Writer": "{topic}: a short paragraph built on the researcher's three facts.",
    "Reviewer": "Approved. The paragraph on {topic} is clear and matches the facts.",
    "Researcher": "Three facts on {topic}, taken from the search results.",
}

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)   # no line per request
fault = {"mode": "ok"}


# --- the fault switch -------------------------------------------------------------------

@app.get("/fault")
def show_fault():
    return fault


@app.post("/fault")
def set_fault():
    fault["mode"] = request.get_json(force=True).get("mode", "ok")
    print(f"fault: {ROLE} is now {fault['mode']}", flush=True)
    return fault


def broken():
    """Apply the fault: wait, never answer, or return the error to send instead of an answer."""
    while fault["mode"] == "hang":   # until the operator clears the fault
        time.sleep(0.5)
    if fault["mode"] == "slow":
        time.sleep(SLOW_SECONDS)
    if fault["mode"] == "error":
        return jsonify(error={"message": "Service Unavailable", "type": "overloaded"}), 503
    return None


# --- the model API: OpenAI's chat completions ----------------------------------------------

@app.post("/v1/chat/completions")
def chat():
    if error := broken():
        return error
    body = request.get_json(force=True)
    messages = body.get("messages", [])
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user = next((m["content"] for m in messages if m["role"] == "user"), "")
    role = next((r for r in ANSWERS if r in system), "Writer")
    topic = user.split("Topic:", 1)[1].split("\n", 1)[0].strip() if "Topic:" in user else "the topic"
    time.sleep(THINK[role] * (0.8 + 0.4 * (len(messages) % 3) / 2))

    # The researcher's first answer asks for a search; every other answer is text.
    used_tool = any(m["role"] == "tool" for m in messages)
    if role == "Researcher" and body.get("tools") and not used_tool:
        tool = body["tools"][0]["function"]["name"]
        message = {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": tool, "arguments": json.dumps({"query": topic})},
        }]}
        finish = "tool_calls"
    else:
        message = {"role": "assistant", "content": ANSWERS[role].format(topic=topic)}
        finish = "stop"

    # Roughly four characters to a token.
    prompt_tokens = sum(len(str(m.get("content") or "")) for m in messages) // 4
    completion_tokens = len(str(message["content"] or "")) // 4 + 10
    return {
        "id": "chatcmpl-sim", "object": "chat.completion", "created": int(time.time()),
        "model": body.get("model", "sim-1"),
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                  "total_tokens": prompt_tokens + completion_tokens},
    }


# --- the search API -------------------------------------------------------------------------

@app.get("/search")
def search():
    if error := broken():
        return error
    query = request.args.get("q", "")
    time.sleep(SEARCH_SECONDS)
    return {"query": query, "results": [f"{query}: fact {n}" for n in (1, 2, 3)]}


app.run(host="0.0.0.0", port=8080, threaded=True)
