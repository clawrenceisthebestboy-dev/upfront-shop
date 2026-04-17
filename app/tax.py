"""Maine sales tax.

Maine 2026: general sales tax is 5.5% on tangible personal property (parts).
Auto repair LABOR is NOT subject to sales tax.
The tax rate is user-editable in Settings for future-proofing.
"""
from __future__ import annotations
from decimal import Decimal
from .markup import quantize

DEFAULT_RATE = Decimal("0.055")  # 5.5%


def tax_on(taxable_subtotal: Decimal, rate: Decimal = DEFAULT_RATE) -> Decimal:
    return quantize(taxable_subtotal * rate)
