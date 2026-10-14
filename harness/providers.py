"""LLM providers. All speak the OpenAI chat-completions API, so one client serves them all."""
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
    request_options: dict = field(default_factory=dict)  # extra chat-completions arguments for every call

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
    "deepseek": Provider("deepseek", "https://api.deepseek.com", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL"),
    # Local models through Ollama's OpenAI-compatible endpoint. Needs `ollama serve` running with a
    # context window big enough for the tool list (OLLAMA_CONTEXT_LENGTH), or long prompts are truncated.
    "ollama": Provider("ollama", os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"), None, "OLLAMA_MODEL",
                       # Qwen3 "thinks" for hundreds of tokens before every reply, which on this Mac is minutes
                       # per step. "none" turns that off; models that do not think ignore it.
                       request_options={"reasoning_effort": "none"}),
}
