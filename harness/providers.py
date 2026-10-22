"""LLM providers. All but Anthropic speak the OpenAI chat-completions API; harness/llm.py hides the difference."""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str | None
    key_env: str | None  # None for a local runner that needs no key
    model_env: str
    request_options: dict = field(default_factory=dict)  # extra arguments for every call to the model
    api: str = "openai"  # "openai": chat completions (OpenAI, DeepSeek, Ollama); "anthropic": the Messages API (harness/llm.py)

    @property
    def api_key(self) -> str:
        if self.key_env is None:
            return "not-needed"  # the OpenAI client insists on a value
        key = os.environ.get(self.key_env, "")
        if not key:
            raise SystemExit(f"{self.key_env} is not set (see .env.example)")
        return key

    @property
    def model(self) -> str:
        model = os.environ.get(self.model_env, "")
        if not model:
            raise SystemExit(f"{self.model_env} is not set (see .env.example)")
        return model


PROVIDERS = {
    "openai": Provider("openai", None, "OPENAI_API_KEY", "OPENAI_MODEL"),
    # A second OpenAI model, kept apart from gpt-4.1 so each has its own logs. gpt-6-sol takes function tools on chat
    # completions only with reasoning off, so it is compared without reasoning, like the other models here.
    "openai-sol": Provider("openai-sol", None, "OPENAI_API_KEY", "OPENAI_SOL_MODEL",
                           request_options={"reasoning_effort": "none"}),
    "deepseek": Provider("deepseek", "https://api.deepseek.com", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL"),
    # DeepSeek V4 Pro, same API and key. Thinking is on by default there; it is switched off so the model is compared
    # like the others here. (Thinking on needs reasoning_content passed back on every turn when tools are present.)
    "deepseek-pro": Provider("deepseek-pro", "https://api.deepseek.com", "DEEPSEEK_API_KEY", "DEEPSEEK_PRO_MODEL",
                             request_options={"extra_body": {"thinking": {"type": "disabled"}}}),
    # Claude Haiku 5.5 through the native Messages API. Thinking is on by default there; it is switched off, like the
    # other models here. If Haiku then writes a tool call into its text instead of calling the tool (a known failure
    # with thinking off on the Opus line), the run ends with no tool calls: check the first runs for that.
    "anthropic-haiku": Provider("anthropic-haiku", None, "ANTHROPIC_API_KEY", "ANTHROPIC_HAIKU_MODEL", api="anthropic",
                                request_options={"thinking": {"type": "disabled"}}),
    # Claude Sonnet 5.5: `thinking: disabled` is a 400 on it; `between_tools` is its way of turning thinking off.
    "anthropic-sonnet": Provider("anthropic-sonnet", None, "ANTHROPIC_API_KEY", "ANTHROPIC_SONNET_MODEL", api="anthropic",
                                 request_options={"thinking": {"type": "between_tools"}}),
    # Claude Opus 5.5: thinking cannot be turned off (any `thinking` other than adaptive is a 400), so effort is the only
    # control. `low` is the closest thing to "off", and is a different setting from the other models here: say so with
    # the results.
    "anthropic-opus": Provider("anthropic-opus", None, "ANTHROPIC_API_KEY", "ANTHROPIC_OPUS_MODEL", api="anthropic",
                               request_options={"output_config": {"effort": "low"}}),
    # Local models through Ollama's OpenAI-compatible endpoint. Needs `ollama serve` running with a
    # context window big enough for the tool list (OLLAMA_CONTEXT_LENGTH), or long prompts are truncated.
    "ollama": Provider("ollama", os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"), None, "OLLAMA_MODEL",
                       # Qwen3 "thinks" for hundreds of tokens before every reply, which on this Mac is minutes
                       # per step. "none" turns that off; models that do not think ignore it.
                       request_options={"reasoning_effort": "none"}),
}
