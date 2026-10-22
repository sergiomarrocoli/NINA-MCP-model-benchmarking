"""One conversation with a model, whichever API it speaks. run.py only sees this.

    chat = open_chat(provider, system, user, tools)
    turn = chat.step()                 # the model's next reply
    chat.add_tool_results([(id, text, failed), ...])   # then step() again

`tools` are in the OpenAI function format (harness/run.py:openai_tools); a backend converts them if its API wants
another shape. Each turn's `usage` is logged as it is and uses the OpenAI field names (`prompt_tokens`,
`prompt_tokens_details.cached_tokens`), so the report reads every backend the same way.
"""
from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI

from harness.providers import Provider


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON text, as the model wrote it


@dataclass
class Turn:
    text: str | None
    tool_calls: list[ToolCall]
    prompt_tokens: int  # all input, cached or not
    completion_tokens: int
    usage: dict
    stop_reason: str | None = None


class Chat(Protocol):
    def step(self) -> Turn: ...

    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None:
        """Answer the last turn's tool calls: (tool call id, result text, whether the call failed)."""


class OpenAIChat:
    """The OpenAI chat-completions API, which OpenAI, DeepSeek and Ollama all speak."""

    def __init__(self, provider: Provider, system: str, user: str, tools: list[dict]):
        self.provider, self.tools = provider, tools
        self.client = OpenAI(api_key=provider.api_key, base_url=provider.base_url)
        self.messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def step(self) -> Turn:
        resp = self.client.chat.completions.create(
            model=self.provider.model, messages=self.messages, tools=self.tools, **self.provider.request_options)
        msg = resp.choices[0].message
        self.messages.append(msg.model_dump(exclude_none=True))
        return Turn(
            text=msg.content,
            tool_calls=[ToolCall(tc.id, tc.function.name, tc.function.arguments or "") for tc in msg.tool_calls or []],
            prompt_tokens=resp.usage.prompt_tokens, completion_tokens=resp.usage.completion_tokens,
            usage=resp.usage.model_dump(), stop_reason=resp.choices[0].finish_reason)

    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None:
        for call_id, text, _failed in results:
            self.messages.append({"role": "tool", "tool_call_id": call_id, "content": text})


def open_chat(provider: Provider, system: str, user: str, tools: list[dict]) -> Chat:
    if provider.api == "anthropic":
        from harness.anthropic_chat import AnthropicChat  # only here, so the other providers do not need the package
        return AnthropicChat(provider, system, user, tools)
    return OpenAIChat(provider, system, user, tools)
