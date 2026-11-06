"""Money helpers.

Rules of the house:
* every amount is an ``int`` number of cents;
* every rate is an ``int`` number of basis points (12% == 1200);
* parsing goes through ``Decimal`` and never through ``float``.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_BRL_CLEAN = re.compile(r"[R$\s ]")


class MoneyParseError(ValueError):
    pass


def _decimal_to_cents(value: Decimal, raw: str) -> int:
    cents = value * 100
    if cents != cents.to_integral_value():
        raise MoneyParseError(f"more than two decimal places: {raw!r}")
    return int(cents)


def parse_dot_decimal(text: str | None) -> int | None:
    """Parse '1234.56' (data warehouse export) into cents."""
    if text is None:
        return None
    raw = str(text).strip()
    if raw == "" or raw.lower() in {"nan", "none", "null"}:
        return None
    try:
        return _decimal_to_cents(Decimal(raw), raw)
    except InvalidOperation as exc:
        raise MoneyParseError(f"invalid amount: {raw!r}") from exc


def parse_brl(text: str | None) -> int | None:
    """Parse Brazilian formatted amounts: '1.234,56', '-1.234,56', 'R$ 12,30', '(5,00)'."""
    if text is None:
        return None
    raw = str(text).strip()
    if raw == "" or raw.lower() in {"nan", "none", "null"}:
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = _BRL_CLEAN.sub("", raw.strip("()"))
    if cleaned.endswith("-"):  # some banks print '1.234,56-'
        negative, cleaned = True, cleaned[:-1]
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        cents = _decimal_to_cents(Decimal(cleaned), raw)
    except InvalidOperation as exc:
        raise MoneyParseError(f"invalid amount: {raw!r}") from exc
    return -cents if negative else cents


def rate_from_fraction(value: float | str | Decimal) -> int:
    """Convert a spreadsheet percentage (0.0319) into basis points (319).

    Spreadsheet cells come as binary floats, so the conversion rounds to the
    nearest basis point and refuses values that are not close to one.
    """
    dec = Decimal(str(value)) * Decimal(10000)
    bps = dec.to_integral_value(rounding=ROUND_HALF_UP)
    if abs(dec - bps) > Decimal("0.0001"):
        raise MoneyParseError(f"rate is not a whole basis point: {value!r}")
    return int(bps)


def apply_rate(amount_cents: int, bps: int) -> int:
    """amount x rate, rounded half up to the cent. Exact integer arithmetic."""
    if amount_cents < 0:
        return -apply_rate(-amount_cents, bps)
    return (amount_cents * bps + 5000) // 10000


def apply_rate_truncated(amount_cents: int, bps: int) -> int:
    """Same product, truncated. Used only to plant rounding traps."""
    if amount_cents < 0:
        return -apply_rate_truncated(-amount_cents, bps)
    return (amount_cents * bps) // 10000


def format_brl(cents: int, signed: bool = False) -> str:
    """12345 -> 'R$ 123,45'; with signed=True negative values get a leading minus."""
    negative = cents < 0
    whole, frac = divmod(abs(int(cents)), 100)
    body = f"{whole:,}".replace(",", ".") + f",{frac:02d}"
    text = f"R$ {body}"
    if negative and signed:
        return f"-{text}"
    return text


def format_number_br(cents: int) -> str:
    """12345 -> '123,45' (no currency sign, Brazilian separators, minus kept)."""
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(int(cents)), 100)
    return sign + f"{whole:,}".replace(",", ".") + f",{frac:02d}"


def format_pct(bps: int) -> str:
    """1200 -> '12%', 319 -> '3,19%'."""
    whole, frac = divmod(int(bps), 100)
    if frac == 0:
        return f"{whole}%"
    return f"{whole},{frac:02d}".rstrip("0") + "%"
