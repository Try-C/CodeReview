"""LLM cost and usage models per spec §12.5.

All cost calculations use Decimal (never binary floats).  Every model call
captures a PricingSnapshot so historical costs are immune to price changes.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel


class PricingSnapshot(BaseModel):
    """A point-in-time price snapshot saved with every model call.

    Immutable; changes in supplier pricing cannot alter historical costs.
    """

    model: str
    input_price_per_million: Decimal
    output_price_per_million: Decimal
    currency: str = "USD"
    version: str


class LLMCallResult(BaseModel):
    """The complete result of one LLM invocation including usage and cost."""

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_status: Literal["available", "unavailable"]
    estimated_cost: Decimal | None
    latency_ms: int
    pricing: PricingSnapshot


def calculate_estimated_cost(
    input_tokens: int,
    output_tokens: int,
    pricing: PricingSnapshot,
) -> Decimal:
    """Compute cost from token counts and a pricing snapshot — §12.5.

    Cost = (input_tokens * input_price + output_tokens * output_price) / 1e6,
    rounded to 6 decimal places via ROUND_HALF_UP.
    """
    million = Decimal("1000000")
    cost = (
        Decimal(input_tokens) * pricing.input_price_per_million
        + Decimal(output_tokens) * pricing.output_price_per_million
    ) / million
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
