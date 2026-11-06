"""Reference implementation of the payout rule for a single order.

The reconciliation engine computes the same thing in SQL
(``sql/03_expected_order_lines.sql``). The generator uses this module to
produce correct statements, and the test suite checks that both agree.

    payout = items - commission - payment fee - coupon funded by the restaurant
             + delivery fee (only when the restaurant delivers itself)

* commission: plan rate over the items value, before any coupon;
* payment fee: rate of the payment method over what the customer paid;
* coupons funded by the platform are never charged to the restaurant.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .money import apply_rate

PAYMENT_METHODS = ("pix", "credito", "debito", "vale_refeicao")


@dataclass(frozen=True)
class PlanVersion:
    plan_id: str
    name: str
    version: int
    valid_from: date
    valid_to: date | None
    commission_bps: int
    delivery: str  # "propria" (restaurant delivers) or "plataforma"
    fee_bps: dict  # payment method -> basis points

    def covers(self, day: date) -> bool:
        return self.valid_from <= day and (self.valid_to is None or day <= self.valid_to)


PLAN_VERSIONS: list[PlanVersion] = [
    PlanVersion("ESS", "Essencial", 1, date(2026, 1, 1), date(2026, 10, 14), 1200, "propria",
                {"pix": 99, "debito": 159, "credito": 319, "vale_refeicao": 490}),
    PlanVersion("ESS", "Essencial", 2, date(2026, 10, 15), None, 1200, "propria",
                {"pix": 99, "debito": 159, "credito": 299, "vale_refeicao": 490}),
    PlanVersion("COM", "Completo", 1, date(2026, 1, 1), None, 2300, "plataforma",
                {"pix": 99, "debito": 159, "credito": 319, "vale_refeicao": 490}),
    PlanVersion("PLUS", "Parceiro Plus", 1, date(2026, 1, 1), None, 2000, "plataforma",
                {"pix": 79, "debito": 129, "credito": 279, "vale_refeicao": 450}),
]


def plan_version(plan_id: str, day: date, versions: list[PlanVersion] | None = None) -> PlanVersion:
    for pv in versions or PLAN_VERSIONS:
        if pv.plan_id == plan_id and pv.covers(day):
            return pv
    raise LookupError(f"no version of plan {plan_id} on {day}")


@dataclass(frozen=True)
class OrderPayout:
    items: int
    delivery_to_restaurant: int
    coupon_restaurant: int
    commission: int
    payment_fee: int

    @property
    def net(self) -> int:
        return (self.items + self.delivery_to_restaurant - self.coupon_restaurant
                - self.commission - self.payment_fee)


def order_payout(items: int, delivery_fee: int, coupon_value: int, coupon_funder: str | None,
                 payment_method: str, pv: PlanVersion,
                 commission_bps: int | None = None, fee_bps: int | None = None,
                 rate_fn=apply_rate) -> OrderPayout:
    """Compute the payout of one delivered order under plan version ``pv``.

    ``commission_bps``, ``fee_bps`` and ``rate_fn`` exist only so the data
    generator can plant controlled mistakes; the engine never overrides them.
    """
    total_paid = items + delivery_fee - coupon_value
    c_bps = pv.commission_bps if commission_bps is None else commission_bps
    f_bps = pv.fee_bps[payment_method] if fee_bps is None else fee_bps
    return OrderPayout(
        items=items,
        delivery_to_restaurant=delivery_fee if pv.delivery == "propria" else 0,
        coupon_restaurant=coupon_value if coupon_funder == "restaurante" else 0,
        commission=rate_fn(items, c_bps),
        payment_fee=rate_fn(total_paid, f_bps),
    )
