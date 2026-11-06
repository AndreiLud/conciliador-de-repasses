"""Expected payout of one order, plan by plan."""
from datetime import date

from src.payout import order_payout, plan_version


def test_own_delivery_plan_keeps_delivery_fee():
    pv = plan_version("ESS", date(2026, 10, 1))
    p = order_payout(items=5000, delivery_fee=799, coupon_value=0, coupon_funder=None, payment_method="pix", pv=pv)
    assert p.commission == 600                      # 12% of 50,00
    assert p.payment_fee == apply_fee(5799, 99)     # 0,99% of what the customer paid
    assert p.delivery_to_restaurant == 799
    assert p.net == 5000 + 799 - 600 - p.payment_fee


def test_platform_delivery_plan_does_not_pass_delivery_fee():
    pv = plan_version("COM", date(2026, 10, 1))
    p = order_payout(items=5000, delivery_fee=799, coupon_value=0, coupon_funder=None, payment_method="credito", pv=pv)
    assert p.delivery_to_restaurant == 0
    assert p.commission == 1150                     # 23%
    assert p.payment_fee == apply_fee(5799, 319)


def test_platform_coupon_is_not_charged_to_restaurant():
    pv = plan_version("PLUS", date(2026, 10, 1))
    paid_by_platform = order_payout(4000, 0, 1000, "plataforma", "debito", pv)
    paid_by_restaurant = order_payout(4000, 0, 1000, "restaurante", "debito", pv)
    assert paid_by_platform.coupon_restaurant == 0
    assert paid_by_restaurant.coupon_restaurant == 1000
    assert paid_by_platform.commission == paid_by_restaurant.commission == 800   # commission before coupon
    assert paid_by_platform.net - paid_by_restaurant.net == 1000


def test_plan_version_changes_credit_fee_on_october_15():
    assert plan_version("ESS", date(2026, 10, 14)).fee_bps["credito"] == 319
    assert plan_version("ESS", date(2026, 10, 15)).fee_bps["credito"] == 299


def apply_fee(amount, bps):
    return (amount * bps + 5000) // 10000
