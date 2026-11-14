"""Reusable, decimal-safe Money value object and currency rounding utilities.

This module provides high-integrity financial calculations for Arya Global Digital's
dual-programme platform. It strictly prevents floating-point inaccuracies, enforces
explicit INR currency semantics, guarantees the commission conservation invariant
(Gross == Operational Cost + TDS + Net), and provides deterministic quantization.

Design Rules:
  1. Decimal Only: Binary floating-point values (float) are strictly prohibited and raise TypeError.
  2. No Special Numerics: NaN, signaling NaN, +Infinity, and -Infinity are rejected with ValueError.
  3. No Silent Quantization: The Money constructor preserves valid intermediate Decimal precision.
     Quantization to paise (2 decimal places) occurs explicitly via round_currency() or Money.quantize().
  4. Currency Safety: Operations between different currencies raise CurrencyMismatchError.
  5. Conservation Invariant: Gross commission equals the exact sum of rounded deductions and net residual.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional, Tuple, Union


class CurrencyMismatchError(ValueError):
    """Raised when an operation is attempted between different currency types."""
    pass


# Default two-decimal quantization scale (1 paisa = ₹0.01)
PAISE_SCALE = Decimal("0.01")


def _parse_decimal(value: Any) -> Decimal:
    """Safely validate and parse an input value to a finite Decimal.

    Rejects floats, special Decimals (NaN, Infinity), and malformed strings.
    """
    if isinstance(value, float):
        raise TypeError(
            f"Floating-point values are forbidden for monetary amounts to prevent binary "
            f"representation drift. Received float: {value!r}. Use Decimal, str, or int instead."
        )
    if isinstance(value, Money):
        return value.amount
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            raise ValueError(f"Special Decimal values (NaN, Infinity) are rejected for monetary calculations: {value!r}")
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        v = value.strip()
        if not v:
            raise ValueError("Empty or whitespace-only string cannot be converted to monetary value.")
        if v.lower() in ("nan", "-nan", "snan", "-snan", "inf", "-inf", "+inf", "infinity", "-infinity", "+infinity"):
            raise ValueError(f"Special numeric strings (NaN, Infinity) are rejected for monetary calculations: {value!r}")
        try:
            d = Decimal(v)
            if d.is_nan() or d.is_infinite():
                raise ValueError(f"Invalid monetary string resulted in non-finite Decimal: {value!r}")
            return d
        except InvalidOperation as exc:
            raise ValueError(f"Invalid monetary string '{value}': cannot parse as Decimal.") from exc
    raise TypeError(
        f"Unsupported type for monetary value: {type(value).__name__}. "
        f"Expected Decimal, str, or int."
    )


def round_currency(
    value: Union[Decimal, "Money", str, int],
    rounding: str = ROUND_HALF_UP,
) -> Decimal:
    """Quantize a monetary amount explicitly to two decimal places (paise).

    Args:
        value: Monetary amount as Decimal, Money, str, or int.
        rounding: Decimal rounding mode. Defaults to ROUND_HALF_UP.
            (Note: Final business-wide rounding policy requires client confirmation;
            ROUND_HALF_UP is the standard proposed default).

    Returns:
        Decimal quantized strictly to Decimal("0.01").
    """
    dec = _parse_decimal(value)
    return dec.quantize(PAISE_SCALE, rounding=rounding)


class Money:
    """Immutable monetary value object encapsulating an amount and a currency code."""

    __slots__ = ("_amount", "_currency")

    def __init__(
        self,
        amount: Union[Decimal, str, int, "Money"] = Decimal("0"),
        currency: str = "INR",
    ) -> None:
        if not isinstance(currency, str) or not currency.strip():
            raise ValueError("Currency code must be a non-empty string (e.g. 'INR').")

        curr = currency.strip().upper()
        if isinstance(amount, Money):
            if amount.currency != curr:
                raise CurrencyMismatchError(
                    f"Cannot initialize Money({curr}) from Money({amount.currency})."
                )
            dec_amount = amount.amount
        else:
            dec_amount = _parse_decimal(amount)

        # Money is strictly immutable
        object.__setattr__(self, "_amount", dec_amount)
        object.__setattr__(self, "_currency", curr)

    def __setattr__(self, key: str, value: Any) -> None:
        raise AttributeError("Money instances are immutable.")

    def __delattr__(self, key: str) -> None:
        raise AttributeError("Money instances are immutable.")

    @property
    def amount(self) -> Decimal:
        """The underlying Decimal amount, preserving intermediate precision."""
        return self._amount

    @property
    def currency(self) -> str:
        """The standard uppercase 3-character ISO or domestic currency code (e.g. 'INR')."""
        return self._currency

    def to_decimal(self) -> Decimal:
        """Return the underlying Decimal amount."""
        return self._amount

    def to_paise(self, rounding: str = ROUND_HALF_UP) -> int:
        """Convert amount to integer paise, explicitly quantizing if sub-paise amounts exist."""
        quantized = round_currency(self._amount, rounding=rounding)
        return int(quantized * Decimal("100"))

    def quantize(self, rounding: str = ROUND_HALF_UP) -> "Money":
        """Return a new Money instance explicitly quantized to 2 decimal places."""
        return Money(round_currency(self._amount, rounding=rounding), self._currency)

    def format(self, symbol: bool = True) -> str:
        """Format to a standard two-decimal currency string (e.g. '₹700.00')."""
        quantized = round_currency(self._amount, rounding=ROUND_HALF_UP)
        sym = "₹" if self._currency == "INR" else f"{self._currency} "
        formatted_num = f"{quantized:.2f}"
        return f"{sym}{formatted_num}" if symbol else formatted_num

    def is_zero(self) -> bool:
        """Return True if amount equals zero."""
        return self._amount == Decimal("0")

    def is_positive(self) -> bool:
        """Return True if amount is strictly greater than zero."""
        return self._amount > Decimal("0")

    def is_negative(self) -> bool:
        """Return True if amount is strictly less than zero."""
        return self._amount < Decimal("0")

    def _assert_same_currency(self, other: "Money") -> None:
        if not isinstance(other, Money):
            raise TypeError(f"Operand must be Money, not {type(other).__name__}.")
        if self._currency != other._currency:
            raise CurrencyMismatchError(
                f"Currency mismatch: operation attempted between {self._currency} and {other._currency}."
            )

    # -------------------------------------------------------------------------
    # Comparison operators
    # -------------------------------------------------------------------------
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return False
        return self._currency == other._currency and self._amount == other._amount

    def __hash__(self) -> int:
        return hash((self._amount, self._currency))

    def __lt__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self._amount < other._amount

    def __le__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self._amount <= other._amount

    def __gt__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self._amount > other._amount

    def __ge__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self._amount >= other._amount

    # -------------------------------------------------------------------------
    # Arithmetic operators
    # -------------------------------------------------------------------------
    def __add__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(self._amount + other._amount, self._currency)

    def __sub__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(self._amount - other._amount, self._currency)

    def __neg__(self) -> "Money":
        return Money(-self._amount, self._currency)

    def __pos__(self) -> "Money":
        return Money(+self._amount, self._currency)

    def __abs__(self) -> "Money":
        return Money(abs(self._amount), self._currency)

    def __mul__(self, other: Union[Decimal, int]) -> "Money":
        if isinstance(other, float):
            raise TypeError("Floating-point multiplication is forbidden. Use Decimal or int.")
        if not isinstance(other, (Decimal, int)):
            return NotImplemented
        factor = _parse_decimal(other)
        return Money(self._amount * factor, self._currency)

    def __rmul__(self, other: Union[Decimal, int]) -> "Money":
        return self.__mul__(other)

    def __truediv__(self, other: Union["Money", Decimal, int]) -> Union["Money", Decimal]:
        if isinstance(other, float):
            raise TypeError("Floating-point division is forbidden. Use Decimal or int.")
        if isinstance(other, Money):
            self._assert_same_currency(other)
            if other._amount == Decimal("0"):
                raise ZeroDivisionError("Cannot divide Money by zero.")
            return self._amount / other._amount
        if isinstance(other, (Decimal, int)):
            divisor = _parse_decimal(other)
            if divisor == Decimal("0"):
                raise ZeroDivisionError("Cannot divide Money by zero.")
            return Money(self._amount / divisor, self._currency)
        return NotImplemented

    def __floordiv__(self, other: Union[Decimal, int]) -> "Money":
        if isinstance(other, float):
            raise TypeError("Floating-point division is forbidden. Use Decimal or int.")
        if isinstance(other, (Decimal, int)):
            divisor = _parse_decimal(other)
            if divisor == Decimal("0"):
                raise ZeroDivisionError("Cannot divide Money by zero.")
            return Money(self._amount // divisor, self._currency)
        return NotImplemented

    def __repr__(self) -> str:
        return f"Money('{self._amount}', '{self._currency}')"

    def __str__(self) -> str:
        return self.format()


class CommissionSplit:
    """Structure representing a validated gross commission and its itemized deductions.

    Conservation Invariant:
        gross == op_cost + tds + net
    """

    __slots__ = ("_gross", "_op_cost", "_tds", "_net")

    def __init__(self, gross: Money, op_cost: Money, tds: Money, net: Money) -> None:
        if not (isinstance(gross, Money) and isinstance(op_cost, Money) and isinstance(tds, Money) and isinstance(net, Money)):
            raise TypeError("All components of CommissionSplit must be Money instances.")

        curr = gross.currency
        if not (op_cost.currency == curr and tds.currency == curr and net.currency == curr):
            raise CurrencyMismatchError("All components of CommissionSplit must share the same currency.")

        if op_cost.amount < Decimal("0.00"):
            raise ValueError(f"Operational cost cannot be negative: {op_cost.amount}")
        if tds.amount < Decimal("0.00"):
            raise ValueError(f"TDS deduction cannot be negative: {tds.amount}")
        if net.amount < Decimal("0.00"):
            raise ValueError(f"Net commission cannot be negative: {net.amount}")

        # Enforce two-decimal monetary precision on all posting components (no fractional paise)
        for name, m in (
            ("Gross commission", gross),
            ("Operational cost", op_cost),
            ("TDS deduction", tds),
            ("Net commission", net),
        ):
            if (m.amount * Decimal("100")) % Decimal("1") != Decimal("0") or m.amount.as_tuple().exponent < -2:
                raise ValueError(
                    f"{name} must have exactly two-decimal monetary precision (no fractional paise): {m.amount}"
                )

        # Strict conservation invariant check
        if gross.amount != (op_cost.amount + tds.amount + net.amount):
            raise ValueError(
                f"Conservation invariant violated: gross ({gross.amount}) != "
                f"op_cost ({op_cost.amount}) + tds ({tds.amount}) + net ({net.amount})"
            )

        object.__setattr__(self, "_gross", gross)
        object.__setattr__(self, "_op_cost", op_cost)
        object.__setattr__(self, "_tds", tds)
        object.__setattr__(self, "_net", net)

    def __setattr__(self, key: str, value: Any) -> None:
        raise AttributeError("CommissionSplit instances are immutable.")

    def __delattr__(self, key: str) -> None:
        raise AttributeError("CommissionSplit instances are immutable.")

    @property
    def gross(self) -> Money:
        return self._gross

    @property
    def op_cost(self) -> Money:
        return self._op_cost

    @property
    def tds(self) -> Money:
        return self._tds

    @property
    def net(self) -> Money:
        return self._net

    def __repr__(self) -> str:
        return (
            f"CommissionSplit(gross={self._gross!r}, op_cost={self._op_cost!r}, "
            f"tds={self._tds!r}, net={self._net!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CommissionSplit):
            return False
        return (
            self._gross == other.gross
            and self._op_cost == other.op_cost
            and self._tds == other.tds
            and self._net == other.net
        )


def _parse_rate(rate: Any, name: str = "Rate") -> Decimal:
    """Validate and parse a percentage rate operand."""
    if isinstance(rate, float):
        raise TypeError(f"{name} must not be a float. Provide Decimal, int, or string representation.")
    dec = _parse_decimal(rate)
    if dec < Decimal("0.00"):
        raise ValueError(f"{name} cannot be negative: {dec}.")
    return dec


def calculate_commission_split(
    gross: Union[Money, Decimal, str, int],
    op_cost_rate: Union[Decimal, str, int],
    tds_rate: Union[Decimal, str, int],
    rounding: str = ROUND_HALF_UP,
) -> CommissionSplit:
    """Calculate gross, operational cost, TDS, and net commission.

    Benchmark Plan A Example:
        Gross: ₹750.00
        Operational cost rate: 0.046667 (4.6667%)
        TDS rate: 0.020000 (2.0%)
        -> Operational cost: round(750 * 0.046667) = ₹35.00
        -> TDS: round(750 * 0.020000) = ₹15.00
        -> Net: 750.00 - 35.00 - 15.00 = ₹700.00

    Guarantees:
        gross == op_cost + tds + net
        Net is derived as the exact residual after itemized rounded deductions.
    """
    if isinstance(gross, Money):
        gross_money = gross
    else:
        gross_money = Money(gross)

    if gross_money.amount < Decimal("0.00"):
        raise ValueError(f"Gross commission cannot be negative: {gross_money.amount}")

    # Gross commission must have at most two decimal places (no fractional paise).
    # Do not silently round an invalid gross amount with non-zero fractional paise (e.g. 750.005).
    # Quantities with trailing decimal zeros from database NUMERIC(18, 6) (e.g. 750.000000)
    # have zero fractional paise and normalize cleanly to paise scale.
    if (gross_money.amount * Decimal("100")) % Decimal("1") != Decimal("0"):
        raise ValueError(
            f"Gross commission must have at most two decimal places (no fractional paise): {gross_money.amount}"
        )

    # Normalize valid gross to exact two-decimal monetary scale
    gross_money = Money(gross_money.amount.quantize(PAISE_SCALE), gross_money.currency)

    op_rate = _parse_rate(op_cost_rate, "Operational cost rate")
    t_rate = _parse_rate(tds_rate, "TDS rate")

    if (op_rate + t_rate) > Decimal("1.00"):
        raise ValueError(f"Total deduction rates ({op_rate + t_rate}) cannot exceed 1.0 (100%).")

    # Explicitly calculate and round each deduction
    op_cost_dec = round_currency(gross_money.amount * op_rate, rounding=rounding)
    tds_dec = round_currency(gross_money.amount * t_rate, rounding=rounding)

    # Net is derived as the residual to enforce conservation
    net_dec = gross_money.amount - op_cost_dec - tds_dec
    if net_dec < Decimal("0.00"):
        raise ValueError(
            f"Total deductions (₹{op_cost_dec + tds_dec}) exceed gross commission (₹{gross_money.amount})."
        )

    curr = gross_money.currency
    return CommissionSplit(
        gross=gross_money,
        op_cost=Money(op_cost_dec, curr),
        tds=Money(tds_dec, curr),
        net=Money(net_dec, curr),
    )

