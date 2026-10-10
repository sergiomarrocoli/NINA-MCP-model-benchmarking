"""List prices in US dollars per million tokens, used for the cost-per-run metric.

Costs are upper bounds: every input token is priced as uncached, because the logs do not
separate cached tokens. Check these against the provider's pricing page before publishing.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input_per_m: float
    output_per_m: float
    estimated: bool = False  # True when the rate is a stand-in, not the model's listed price
    note: str = ""


PRICES = {
    # https://developers.openai.com/api/docs/pricing (standard tier), checked 2026-10-10.
    "gpt-4.1": Price(2.00, 8.00),
    # `deepseek-chat` is not on DeepSeek's current pricing page. Priced as DeepSeek-V4.1-Flash at the
    # peak (higher) rate, https://api-docs.deepseek.com/quick_start/pricing, checked 2026-10-10.
    "deepseek-chat": Price(0.30, 1.20, estimated=True, note="DeepSeek-V4.1-Flash peak rate"),
    # Local models cost nothing per token (electricity and the machine are not counted).
    "qwen3:8b": Price(0.0, 0.0, note="runs locally"),
}


def cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Dollar cost of a run, or None if the model has no price."""
    price = PRICES.get(model)
    if price is None:
        return None
    return (prompt_tokens * price.input_per_m + completion_tokens * price.output_per_m) / 1_000_000


def is_estimated(model: str) -> bool:
    price = PRICES.get(model)
    return price is not None and price.estimated
