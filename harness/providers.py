"""LLM providers. All speak the OpenAI chat-completions API, so one client serves them all."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str | None
    key_env: str
    model_env: str

    @property
    def api_key(self) -> str:
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
}
