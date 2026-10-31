"""The world outside the crew: a model API and a search API, both fake.

One program, two roles (ROLE=model or ROLE=search). Each answers at once,
costs nothing and gives the same answer every time. The instructor flips a
fault switch with POST /fault {"mode": "ok" | "slow" | "error" | "hang"}:

  slow   every answer takes SLOW_SECONDS
  error  every answer is 503 Service Unavailable
  hang   no answer at all: the connection stays open

Not student code: in real life these are someone else's services.
"""

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROLE = os.environ.get("ROLE", "model")
PORT = int(os.environ.get("PORT", "8080"))
SLOW_SECONDS = float(os.environ.get("SLOW_SECONDS", "8"))

fault = {"mode": "ok"}

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


def model_reply(body):
    messages = body.get("messages", [])
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user = next((m["content"] for m in messages if m["role"] == "user"), "")
    role = next((r for r in ANSWERS if r in system), "Writer")
    time.sleep(THINK[role] * (0.8 + 0.4 * (len(messages) % 3) / 2))
    topic = user.split("Topic:", 1)[1].split("\n", 1)[0].strip() if "Topic:" in user else "the topic"
    used_tool = any(m["role"] == "tool" for m in messages)
    if role == "Researcher" and body.get("tools") and not used_tool:
        message = {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": body["tools"][0]["function"]["name"], "arguments": json.dumps({"query": topic})},
        }]}
        finish = "tool_calls"
    else:
        message = {"role": "assistant", "content": ANSWERS[role].format(topic=topic)}
        finish = "stop"
    prompt_tokens = sum(len(str(m.get("content") or "")) for m in messages) // 4
    completion_tokens = len(str(message["content"] or "")) // 4 + 10
    return {
        "id": "chatcmpl-sim", "object": "chat.completion", "created": int(time.time()), "model": body.get("model", "sim-1"),
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                  "total_tokens": prompt_tokens + completion_tokens},
    }


def search_reply(query):
    time.sleep(SEARCH_SECONDS)
    return {"query": query, "results": [f"{query}: fact {n}" for n in (1, 2, 3)]}


class Handler(BaseHTTPRequestHandler):
    def send(self, code, data):
        raw = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def answer(self, make):
        if fault["mode"] == "hang":
            time.sleep(3600)
        if fault["mode"] == "slow":
            time.sleep(SLOW_SECONDS)
        if fault["mode"] == "error":
            return self.send(503, {"error": {"message": "Service Unavailable", "type": "overloaded"}})
        self.send(200, make())

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/fault":
            return self.send(200, fault)
        if ROLE == "search" and url.path == "/search":
            query = parse_qs(url.query).get("q", [""])[0]
            return self.answer(lambda: search_reply(query))
        self.send(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/fault":
            fault["mode"] = body.get("mode", "ok")
            print(f"fault: {ROLE} is now {fault['mode']}", flush=True)
            return self.send(200, fault)
        if ROLE == "model" and self.path.endswith("/chat/completions"):
            return self.answer(lambda: model_reply(body))
        self.send(404, {"error": "not found"})

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("", PORT), Handler).serve_forever()
