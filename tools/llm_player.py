#!/usr/bin/env python3
"""Replay recorded LLM sessions against an OpenAI-compatible proxy server.

Usage:
    python player.py recordings/test_24_openai-compatible.jsonl
    python player.py recordings/test_24_xai.jsonl
    python player.py recordings/test_24_ollama.jsonl

Each request from the recording is sent to the proxy server one by one.
This isolates the proxy server behavior so you can debug session handling.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

PROXY_URL = "http://localhost:5005/v1/chat/completions"


def replay(recording_path: str | Path, proxy_url: str = PROXY_URL) -> None:
    """Replay each recorded request against the proxy server."""
    recording_path = Path(recording_path)
    if not recording_path.exists():
        print(f"Error: {recording_path} not found")
        sys.exit(1)

    lines = recording_path.read_text().strip().split("\n")
    records = [json.loads(line) for line in lines if line.strip()]

    print(f"Replaying {len(records)} API calls from {recording_path.name}")
    print(f"Target: {proxy_url}")
    print("=" * 60)

    for i, record in enumerate(records, 1):
        req = record["request"]
        resp_record = record["response"]

        # Build the messages array
        messages = []
        if req.get("system"):
            messages.append({"role": "system", "content": req["system"]})
        if req.get("messages"):
            messages.extend(req["messages"])

        # Build the request payload
        payload = {
            "model": req.get("model") or "default",
            "messages": messages,
            "temperature": req.get("temperature", 0.3),
            "max_tokens": req.get("max_tokens", 4096),
        }

        if req.get("tools"):
            payload["tools"] = req["tools"]
            payload["tool_choice"] = "auto"

        print(f"\n--- Call {i}/{len(records)} ---")
        print(f"  Messages: {len(messages)}")
        print(f"  Tools: {len(req.get('tools') or [])}")
        print(
            f"  Original response: tool_calls={len(resp_record.get('tool_calls', []))}"
        )

        try:
            response = requests.post(proxy_url, json=payload, timeout=120)
            print(f"  HTTP {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                content = message.get("content", "")
                tool_calls = message.get("tool_calls", [])
                finish_reason = choice.get("finish_reason", "")

                print(f"  Finish: {finish_reason}")
                if tool_calls:
                    print(f"  Tool calls: {len(tool_calls)}")
                    for tc in tool_calls:
                        func = tc.get("function", {})
                        print(f"    - {func.get('name', '?')}")
                if content:
                    preview = content[:200]
                    print(f"  Content: {preview}{'...' if len(content) > 200 else ''}")
            else:
                print(f"  Error: {response.text[:500]}")

        except Exception as e:
            print(f"  Request failed: {e}")

    print("\n" + "=" * 60)
    print(f"Replayed {len(records)} calls. Check your proxy logs for session count.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python player.py <recording.jsonl>")
        sys.exit(1)

    replay(sys.argv[1])
