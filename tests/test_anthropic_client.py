"""The Anthropic adapter against a local stand-in for the Messages API.

This checks the real SDK path end to end (request serialisation, tool definitions, response
parsing, token usage) without an API key or network access.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import anthropic

from refresolver.llm import AnthropicClient
from refresolver.resolver import EXTRACT_TOOL

RESPONSE = {
    "id": "msg_test",
    "type": "message",
    "role": "assistant",
    "model": "claude-test",
    "content": [
        {"type": "text", "text": "Recording the fields."},
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "record_references",
            "input": {
                "references": [
                    {
                        "index": 1,
                        "authors": ["Autor"],
                        "year": 2015,
                        "title": "Why are there still so many jobs?",
                        "container": None,
                    }
                ]
            },
        },
    ],
    "stop_reason": "tool_use",
    "stop_sequence": None,
    "usage": {"input_tokens": 321, "output_tokens": 45},
}


class FakeMessagesApi(BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self):  # noqa: N802 (name required by BaseHTTPRequestHandler)
        length = int(self.headers["Content-Length"])
        FakeMessagesApi.received.append(
            {"path": self.path, "body": json.loads(self.rfile.read(length))}
        )
        payload = json.dumps(RESPONSE).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def test_adapter_round_trip_through_the_sdk():
    server = HTTPServer(("127.0.0.1", 0), FakeMessagesApi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        sdk = anthropic.Anthropic(
            api_key="test-key", base_url=f"http://127.0.0.1:{server.server_port}", max_retries=0
        )
        client = AnthropicClient("claude-test", api_client=sdk)
        reply = client.create(
            system="Extract fields.",
            messages=[{"role": "user", "content": "1. Autor (2015), Why are there still..."}],
            tools=[EXTRACT_TOOL],
            tool_choice={"type": "tool", "name": "record_references"},
        )
    finally:
        server.shutdown()

    sent = FakeMessagesApi.received[-1]
    assert sent["path"] == "/v1/messages"
    assert sent["body"]["tool_choice"] == {"type": "tool", "name": "record_references"}
    assert sent["body"]["tools"][0]["name"] == "record_references"

    assert reply.tool_calls[0].input["references"][0]["year"] == 2015
    assert (reply.input_tokens, reply.output_tokens) == (321, 45)
    assert reply.text == "Recording the fields."
    # Content blocks come back in a form that can be sent again in the next turn.
    assert reply.content[1] == {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "record_references",
        "input": RESPONSE["content"][1]["input"],
    }
