"""The Anthropic Messages API behind harness.llm.Chat.

Anthropic's OpenAI-compatible endpoint would do, but it has no prompt caching (the cost would be overstated several
times over) and no way to carry thinking between turns. So this speaks the native API.

- Tools: the OpenAI function format becomes `name` / `description` / `input_schema`.
- Caching: top-level automatic `cache_control`, so every turn caches the tools, system prompt and history so far.
- Turns: the whole `response.content` goes back as the assistant message (thinking blocks, when thinking is on,
  must be passed back unchanged), and all of a turn's tool results go back in one user message.
- Usage: mapped to the OpenAI field names that harness/report.py reads. `prompt_tokens` counts every input token,
  cache reads and writes included, as OpenAI's does.
"""
import json

import anthropic

from harness.llm import ToolCall, Turn
from harness.providers import Provider

MAX_TOKENS = 16_000  # per reply; the tool calls here are short, this only has to be large enough never to cut one off


def anthropic_tools(tools: list[dict]) -> list[dict]:
    return [
        {"name": t["function"]["name"], "description": t["function"]["description"], "input_schema": t["function"]["parameters"]}
        for t in tools
    ]


class AnthropicChat:
    def __init__(self, provider: Provider, system: str, user: str, tools: list[dict], client: anthropic.Anthropic | None = None):
        self.provider = provider
        self.client = client or anthropic.Anthropic(api_key=provider.api_key)
        self.system = system
        self.tools = anthropic_tools(tools)
        self.messages = [{"role": "user", "content": user}]

    def step(self) -> Turn:
        resp = self.client.messages.create(
            model=self.provider.model, max_tokens=MAX_TOKENS, system=self.system, tools=self.tools,
            messages=self.messages, cache_control={"type": "ephemeral"}, **self.provider.request_options)
        self.messages.append({"role": "assistant", "content": resp.content})
        text = "".join(b.text for b in resp.content if b.type == "text") or None
        calls = [ToolCall(b.id, b.name, json.dumps(b.input)) for b in resp.content if b.type == "tool_use"]
        u = resp.usage
        read, written = u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0
        prompt = u.input_tokens + read + written
        usage = {
            "prompt_tokens": prompt, "completion_tokens": u.output_tokens, "total_tokens": prompt + u.output_tokens,
            "prompt_tokens_details": {"cached_tokens": read, "cache_write_tokens": written},
        }
        return Turn(text=text, tool_calls=calls, prompt_tokens=prompt, completion_tokens=u.output_tokens,
                    usage=usage, stop_reason=resp.stop_reason)

    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None:
        blocks = [{"type": "tool_result", "tool_use_id": call_id, "content": text, "is_error": failed}
                  for call_id, text, failed in results]
        self.messages.append({"role": "user", "content": blocks})
