"""Tiered parts markup.

Default table matches Josh's posted matrix:
  $0.00 - $2.50     x4.00
  $2.51 - $5.00     x3.75
  $5.01 - $10.00    x3.00
  $10.01 - $50.00   x2.75
  $50.01 - $100.00  x2.50
  $100.01 - $150.00 x2.20
  $150.01 - $200.00 x2.00
  $200.01 - $500.00 x1.85
  $500.01 and up    x1.70
"""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP


DEFAULT_TIERS = [
    (Decimal("2.50"),  Decimal("4.00")),
    (Decimal("5.00"),  Decimal("3.75")),
    (Decimal("10.00"), Decimal("3.00")),
    (Decimal("50.00"), Decimal("2.75")),
    (Decimal("100.00"),Decimal("2.50")),
    (Decimal("150.00"),Decimal("2.20")),
    (Decimal("200.00"),Decimal("2.00")),
    (Decimal("500.00"),Decimal("1.85")),
    (None,             Decimal("1.70")),
]


def quantize(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def multiplier_for_cost(cost: Decimal, tiers=DEFAULT_TIERS) -> Decimal:
    for upper, mult in tiers:
        if upper is None or cost <= upper:
            return mult
    return tiers[-1][1]


def marked_up_price(cost: Decimal, tiers=DEFAULT_TIERS) -> Decimal:
    return quantize(cost * multiplier_for_cost(cost, tiers))


def profit_on_part(cost: Decimal, tiers=DEFAULT_TIERS) -> Decimal:
    return quantize(marked_up_price(cost, tiers) - cost)
