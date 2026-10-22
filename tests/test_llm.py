"""The chat backends (harness/llm.py, harness/anthropic_chat.py), against fake clients: no network."""
import json
from types import SimpleNamespace as NS

import pytest

from harness import llm
from harness.anthropic_chat import AnthropicChat, anthropic_tools
from harness.llm import OpenAIChat, open_chat
from harness.pricing import cost
from harness.providers import PROVIDERS, Provider
from harness.report import load_run

OPENAI_TOOLS = [{"type": "function", "function": {
    "name": "nina_park_mount", "description": "Park the mount.",
    "parameters": {"type": "object", "properties": {"x": {"type": "integer"}}}}}]


def anthropic_provider():
    return Provider("anthropic-test", None, None, "ANTHROPIC_TEST_MODEL", api="anthropic",
                    request_options={"thinking": {"type": "disabled"}})


class FakeMessages:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})  # as sent: the real list grows afterwards
        return self.replies.pop(0)


def reply(content, stop="end_turn", input_tokens=100, output_tokens=10, read=0, written=0):
    usage = NS(input_tokens=input_tokens, output_tokens=output_tokens, cache_read_input_tokens=read, cache_creation_input_tokens=written)
    return NS(content=content, stop_reason=stop, usage=usage)


def text(t):
    return NS(type="text", text=t)


def tool_use(id, name, input):
    return NS(type="tool_use", id=id, name=name, input=input)


@pytest.fixture
def chat(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_TEST_MODEL", "claude-test")
    fake = NS(messages=FakeMessages([]))
    return AnthropicChat(anthropic_provider(), "system text", "Park the mount.", OPENAI_TOOLS, client=fake), fake.messages


def test_tools_are_converted_to_the_messages_api_shape():
    assert anthropic_tools(OPENAI_TOOLS) == [{"name": "nina_park_mount", "description": "Park the mount.",
                                              "input_schema": {"type": "object", "properties": {"x": {"type": "integer"}}}}]


def test_a_tool_call_comes_back_as_json_text_and_the_request_carries_the_provider_options(chat):
    chat, api = chat
    api.replies = [reply([text("Parking."), tool_use("tu_1", "nina_park_mount", {"x": 1})], stop="tool_use")]
    turn = chat.step()
    assert turn.text == "Parking." and turn.stop_reason == "tool_use"
    assert [(c.id, c.name, json.loads(c.arguments)) for c in turn.tool_calls] == [("tu_1", "nina_park_mount", {"x": 1})]
    sent = api.calls[0]
    assert sent["model"] == "claude-test" and sent["system"] == "system text"
    assert sent["thinking"] == {"type": "disabled"} and sent["cache_control"] == {"type": "ephemeral"}
    assert sent["messages"] == [{"role": "user", "content": "Park the mount."}] and sent["max_tokens"] > 0


def test_tool_results_go_back_in_one_user_message_after_the_whole_assistant_turn(chat):
    chat, api = chat
    content = [tool_use("a", "nina_park_mount", {}), tool_use("b", "nina_park_mount", {})]
    api.replies = [reply(content, stop="tool_use"), reply([text("Done.")])]
    chat.step()
    chat.add_tool_results([("a", "ok", False), ("b", "boom", True)])
    turn = chat.step()
    assert turn.text == "Done." and turn.tool_calls == []
    history = api.calls[1]["messages"]
    assert [m["role"] for m in history] == ["user", "assistant", "user"]
    assert history[1]["content"] is content  # the whole content goes back unchanged (thinking blocks would need that)
    assert history[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "a", "content": "ok", "is_error": False},
        {"type": "tool_result", "tool_use_id": "b", "content": "boom", "is_error": True}]


def test_usage_counts_every_input_token_and_names_the_cached_ones_like_openai_does(chat):
    chat, api = chat
    api.replies = [reply([text("x")], input_tokens=50, output_tokens=7, read=900, written=40)]
    turn = chat.step()
    assert turn.prompt_tokens == 990 and turn.completion_tokens == 7
    assert turn.usage["prompt_tokens"] == 990
    assert turn.usage["prompt_tokens_details"] == {"cached_tokens": 900, "cache_write_tokens": 40}


def test_a_reply_with_no_text_has_none(chat):
    chat, api = chat
    api.replies = [reply([tool_use("a", "nina_park_mount", {})], stop="tool_use")]
    assert chat.step().text is None


def test_the_provider_is_registered_and_opens_an_anthropic_chat(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_HAIKU_MODEL", "claude-haiku-5-5")
    p = PROVIDERS["anthropic-haiku"]
    assert p.api == "anthropic" and p.model == "claude-haiku-5-5" and p.request_options == {"thinking": {"type": "disabled"}}
    assert isinstance(open_chat(p, "s", "u", OPENAI_TOOLS), AnthropicChat)


def test_the_claude_models_each_get_the_thinking_setting_they_accept():
    # Haiku: thinking can be disabled. Sonnet 5.5: disabled is a 400, between_tools is the off switch. Opus 5.5: cannot be
    # turned off, so no `thinking` at all (anything but adaptive is a 400) and low effort.
    assert PROVIDERS["anthropic-haiku"].request_options == {"thinking": {"type": "disabled"}}
    assert PROVIDERS["anthropic-sonnet"].request_options == {"thinking": {"type": "between_tools"}}
    assert PROVIDERS["anthropic-opus"].request_options == {"output_config": {"effort": "low"}}
    assert all(PROVIDERS[n].api == "anthropic" for n in ("anthropic-haiku", "anthropic-sonnet", "anthropic-opus"))


def test_sonnet_and_opus_are_priced_with_cache_reads_and_writes():
    assert cost("claude-sonnet-5-5", 1_000_000, 0, cached_tokens=500_000, cache_write_tokens=500_000) == pytest.approx(0.1 + 1.25)
    assert cost("claude-opus-5-5", 1_000_000, 1_000_000, cached_tokens=1_000_000) == pytest.approx(0.20 + 20)


def test_openai_providers_default_to_the_openai_backend():
    assert all(p.api == "openai" for name, p in PROVIDERS.items() if not name.startswith("anthropic-"))


def test_openai_chat_keeps_the_chat_completions_message_shapes(monkeypatch):
    calls = []

    def create(**kwargs):
        calls.append(json.loads(json.dumps(kwargs["messages"])))
        msg = NS(content=None, tool_calls=[NS(id="c1", function=NS(name="nina_park_mount", arguments="{}"))],
                 model_dump=lambda exclude_none=True: {"role": "assistant", "tool_calls": [{"id": "c1"}]})
        usage = NS(prompt_tokens=20, completion_tokens=3, model_dump=lambda: {"prompt_tokens": 20})
        return NS(choices=[NS(message=msg, finish_reason="tool_calls")], usage=usage)

    monkeypatch.setattr(llm, "OpenAI", lambda **kw: NS(chat=NS(completions=NS(create=create))))
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    chat = OpenAIChat(PROVIDERS["openai"], "system text", "Park the mount.", OPENAI_TOOLS)
    turn = chat.step()
    assert [(c.id, c.name, c.arguments) for c in turn.tool_calls] == [("c1", "nina_park_mount", "{}")]
    assert turn.prompt_tokens == 20 and turn.completion_tokens == 3 and turn.stop_reason == "tool_calls"
    chat.add_tool_results([("c1", "ok", False)])
    chat.step()
    assert calls[1][-1] == {"role": "tool", "tool_call_id": "c1", "content": "ok"}
    assert calls[0] == [{"role": "system", "content": "system text"}, {"role": "user", "content": "Park the mount."}]


# --- the price of the tokens an Anthropic run reports ---

def test_haiku_prices_cache_reads_and_writes_at_their_own_rates():
    # 1M input: 100k plain, 800k read from the cache, 100k written to it; 1M output
    assert cost("claude-haiku-5-5", 1_000_000, 1_000_000, cached_tokens=800_000, cache_write_tokens=100_000) == pytest.approx(
        0.1 * 0.10 + 0.8 * 0.01 + 0.1 * 0.125 + 0.50)


def test_a_model_with_no_write_rate_prices_written_tokens_as_input():
    assert cost("gpt-4.1", 1_000_000, 0, cache_write_tokens=1_000_000) == pytest.approx(2.0)


def test_load_run_reads_the_cache_writes_from_the_run_log(tmp_path):
    events = [
        {"kind": "start", "task": "t", "tier": 1, "provider": "anthropic-haiku", "model": "claude-haiku-5-5", "schema": "flat"},
        {"kind": "model", "usage": {"prompt_tokens": 1_000_000,
                                    "prompt_tokens_details": {"cached_tokens": 800_000, "cache_write_tokens": 100_000}}},
        {"kind": "end", "passed": True, "finished": True, "seconds": 1, "unsafe_calls": [], "device_drops": [], "failures": [],
         "totals": {"tool_calls": 1, "invalid_calls": 0, "prompt_tokens": 1_000_000, "completion_tokens": 0}},
    ]
    path = tmp_path / "a.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events))
    assert load_run(path)["cost"] == pytest.approx(0.1 * 0.10 + 0.8 * 0.01 + 0.1 * 0.125)
