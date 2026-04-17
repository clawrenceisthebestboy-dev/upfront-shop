"""Invoice total calculation.

Line items:
  - type: 'part' or 'labor'
  - description
  - quantity
  - unit_cost        (shop's cost — internal only for parts; for labor = $0 unless reimbursable)
  - unit_price       (customer-facing unit price)
  - taxable          (parts default True, labor default False)

Pricing policy (set April 2026 per Jon):
  Every invoice AUTOMATICALLY adds a 3.5% non-cash adjustment across
  the entire invoice. Customers paying with CASH or CHECK receive a
  matching 3.5% discount (effectively cancelling the adjustment).
  Card customers pay the adjusted price. The adjustment line is always
  shown on the PDF so the sticker price is transparent.

Invoice math:
  parts_subtotal       = sum of parts line totals
  labor_subtotal       = sum of labor line totals
  subtotal             = parts + labor
  tax                  = tax rate * (taxable portion of subtotal)
  pre_payment_total    = subtotal + tax
  non_cash_adjustment  = pre_payment_total * 3.5%    (ALWAYS applied)
  cash_check_discount  = pre_payment_total * 3.5%    (only if payment
                         method is 'cash' or 'check')
  grand_total          = pre_payment_total + non_cash_adjustment
                                            - cash_check_discount
  profit_parts         = sum of (unit_price - unit_cost) * qty on parts
  profit_labor         = labor_subtotal  (treated as profit pre-wage-cost;
                         true labor-cost comes from timeclock feed in P&L)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional
from .markup import quantize
from .tax import DEFAULT_RATE, tax_on

NON_CASH_ADJUSTMENT_RATE = Decimal("0.035")
CASH_CHECK_DISCOUNT_RATE = Decimal("0.035")


@dataclass
class LineItem:
    kind: str                       # 'part' or 'labor'
    description: str
    quantity: Decimal
    unit_cost: Decimal              # internal — shop cost
    unit_price: Decimal             # customer-facing
    taxable: bool = True
    part_id: Optional[int] = None
    id: Optional[int] = None

    @property
    def line_cost(self) -> Decimal:
        return quantize(self.unit_cost * self.quantity)

    @property
    def line_total(self) -> Decimal:
        return quantize(self.unit_price * self.quantity)

    @property
    def line_profit(self) -> Decimal:
        return quantize(self.line_total - self.line_cost)


@dataclass
class InvoiceTotals:
    parts_subtotal: Decimal
    labor_subtotal: Decimal
    taxable_subtotal: Decimal
    subtotal: Decimal
    tax: Decimal
    pre_payment_total: Decimal
    non_cash_adjustment: Decimal      # always > 0 (except empty invoice)
    cash_check_discount: Decimal      # > 0 when payment_method in ('cash','check')
    grand_total: Decimal
    parts_cost: Decimal
    parts_profit: Decimal
    labor_revenue: Decimal

    # -- backwards-compat aliases so older code reading `.card_surcharge`
    #    or `.cash_discount` still works without immediate updates.
    @property
    def card_surcharge(self) -> Decimal:
        return self.non_cash_adjustment

    @property
    def cash_discount(self) -> Decimal:
        return self.cash_check_discount


def compute_totals(
    lines: List[LineItem],
    payment_method: str = "unpaid",  # 'card', 'cash', 'check', 'unpaid'
    tax_rate: Decimal = DEFAULT_RATE,
    non_cash_rate: Decimal = NON_CASH_ADJUSTMENT_RATE,
    cash_discount_rate: Decimal = CASH_CHECK_DISCOUNT_RATE,
) -> InvoiceTotals:
    parts = [l for l in lines if l.kind == "part"]
    labor = [l for l in lines if l.kind == "labor"]

    parts_subtotal = quantize(sum((l.line_total for l in parts), Decimal("0")))
    labor_subtotal = quantize(sum((l.line_total for l in labor), Decimal("0")))
    subtotal = quantize(parts_subtotal + labor_subtotal)

    taxable_subtotal = quantize(sum(
        (l.line_total for l in lines if l.taxable), Decimal("0")
    ))
    tax = tax_on(taxable_subtotal, tax_rate)

    pre_payment_total = quantize(subtotal + tax)

    # Non-cash adjustment ALWAYS applies (it's baked into the customer-facing
    # sticker price). An empty invoice gets 0.
    non_cash_adj = quantize(pre_payment_total * non_cash_rate) if pre_payment_total > 0 else Decimal("0")

    # Cash / check get a matching discount that cancels the adjustment.
    discount = Decimal("0")
    if payment_method in ("cash", "check"):
        discount = quantize(pre_payment_total * cash_discount_rate)

    grand_total = quantize(pre_payment_total + non_cash_adj - discount)

    parts_cost = quantize(sum((l.line_cost for l in parts), Decimal("0")))
    parts_profit = quantize(parts_subtotal - parts_cost)
    labor_revenue = labor_subtotal

    return InvoiceTotals(
        parts_subtotal=parts_subtotal,
        labor_subtotal=labor_subtotal,
        taxable_subtotal=taxable_subtotal,
        subtotal=subtotal,
        tax=tax,
        pre_payment_total=pre_payment_total,
        non_cash_adjustment=non_cash_adj,
        cash_check_discount=discount,
        grand_total=grand_total,
        parts_cost=parts_cost,
        parts_profit=parts_profit,
        labor_revenue=labor_revenue,
    )
