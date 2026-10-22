"""List prices in US dollars per million tokens, used for the cost-per-run metric.

Input tokens the provider served from its cache (`usage.prompt_tokens_details.cached_tokens`, in the run log) are
priced at the model's cached rate. Where that rate is not known, they are priced as uncached, which makes the cost an
upper bound. Check these against the provider's pricing page before publishing.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input_per_m: float
    output_per_m: float
    cached_input_per_m: float | None = None  # None: cached tokens are priced as uncached (an upper bound)
    estimated: bool = False  # True when the rate is a stand-in, not the model's listed price
    note: str = ""


PRICES = {
    # https://developers.openai.com/api/docs/pricing (standard tier), checked 2026-10-10.
    "gpt-4.1": Price(2.00, 8.00, cached_input_per_m=0.50),
    # Same page, checked 2026-10-22.
    "gpt-6-sol": Price(2.00, 10.00, cached_input_per_m=0.20),
    # `deepseek-chat` is not on DeepSeek's pricing page, which lists `deepseek-flash` (DeepSeek-V4.1-Flash-1017) and says
    # the legacy names are served by it. Priced at its peak (higher) rate, https://api-docs.deepseek.com/quick_start/pricing,
    # checked 2026-10-22: $0.30 cache miss, $0.006 cache hit, $1.20 output. Off-peak is half of each.
    "deepseek-chat": Price(0.30, 1.20, cached_input_per_m=0.006, estimated=True, note="DeepSeek-V4.1-Flash peak rate"),
    # DeepSeek V4 Pro at the peak rate (off-peak is half), same page, checked 2026-10-22.
    "deepseek-v4-pro": Price(1.32, 3.96, cached_input_per_m=0.044),
    # Local models cost nothing per token (electricity and the machine are not counted).
    "qwen3:8b": Price(0.0, 0.0, note="runs locally"),
}


def cost(model: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0) -> float | None:
    """Dollar cost of a run, or None if the model has no price. `prompt_tokens` includes the cached ones."""
    price = PRICES.get(model)
    if price is None:
        return None
    cached_rate = price.input_per_m if price.cached_input_per_m is None else price.cached_input_per_m
    uncached = prompt_tokens - cached_tokens
    return (uncached * price.input_per_m + cached_tokens * cached_rate + completion_tokens * price.output_per_m) / 1_000_000


def is_estimated(model: str) -> bool:
    price = PRICES.get(model)
    return price is not None and price.estimated
