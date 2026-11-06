from decimal import Decimal

import pytest

from src.money import (MoneyParseError, apply_rate, apply_rate_truncated, format_brl, format_pct, parse_brl,
                       parse_dot_decimal, rate_from_fraction)


def test_parse_brazilian_amounts():
    assert parse_brl("1.234,56") == 123456
    assert parse_brl("-1.234,56") == -123456
    assert parse_brl("R$ 12,30") == 1230
    assert parse_brl("(5,00)") == -500
    assert parse_brl("") is None


def test_parse_dot_decimal_refuses_fractions_of_cent():
    assert parse_dot_decimal("45.90") == 4590
    with pytest.raises(MoneyParseError):
        parse_dot_decimal("45.905")


def test_rate_is_half_up_and_exact():
    assert apply_rate(4590, 1200) == 551          # 550.8 -> 551
    assert apply_rate(1250, 1200) == 150
    assert apply_rate(4185, 1200) == 502          # 502.2 -> 502
    assert apply_rate(125, 4000) == 50            # 50.0
    assert apply_rate(4_1625, 100) == 416         # 416.25 -> 416
    assert apply_rate(4_1650, 100) == 417         # 416.5 -> 417 (half up)
    assert apply_rate_truncated(4_1650, 100) == 416


def test_spreadsheet_rates_become_whole_basis_points():
    assert rate_from_fraction(0.0319) == 319
    assert rate_from_fraction(0.12) == 1200
    with pytest.raises(MoneyParseError):
        rate_from_fraction(0.031955)


def test_formatting():
    assert format_brl(123456) == "R$ 1.234,56"
    assert format_brl(-5, signed=True) == "-R$ 0,05"
    assert format_pct(319) == "3,19%"
    assert format_pct(1200) == "12%"
    assert format_pct(1250) == "12,5%"
