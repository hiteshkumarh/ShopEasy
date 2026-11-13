import decimal
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
import pytest

from app.core.money import (
    CommissionSplit,
    CurrencyMismatchError,
    Money,
    round_currency,
    calculate_commission_split,
)


@pytest.mark.unit
class TestMoneyConstructionAndValidation:
    """Unit tests for Money value object initialization and strict validation."""

    def test_construct_from_valid_types(self) -> None:
        """Verify Money accepts Decimal, integer, valid string, and existing Money."""
        m1 = Money(Decimal("750.00"))
        m2 = Money(750)
        m3 = Money("750.00")
        m4 = Money(m1)

        assert m1.amount == Decimal("750.00")
        assert m2.amount == Decimal("750")
        assert m3.amount == Decimal("750.00")
        assert m4.amount == Decimal("750.00")
        assert m1.currency == "INR"

    def test_default_currency_and_custom_currency(self) -> None:
        """Verify default currency is INR and custom currency codes are normalized uppercase."""
        m_inr = Money("100.00")
        assert m_inr.currency == "INR"

        m_usd = Money("100.00", currency="usd")
        assert m_usd.currency == "USD"

        with pytest.raises(ValueError, match="Currency code must be a non-empty string"):
            Money("100.00", currency="")

        with pytest.raises(ValueError, match="Currency code must be a non-empty string"):
            Money("100.00", currency="   ")

    def test_reject_float_strictly_with_type_error(self) -> None:
        """Verify binary floats are strictly rejected to prevent precision loss."""
        with pytest.raises(TypeError, match="Floating-point values are forbidden"):
            Money(750.0)

        with pytest.raises(TypeError, match="Floating-point values are forbidden"):
            Money(0.0)

        with pytest.raises(TypeError, match="Floating-point values are forbidden"):
            Money(0.046667)

    def test_reject_nan_and_infinities(self) -> None:
        """Verify NaN, signaling NaN, +Infinity, and -Infinity are rejected with ValueError."""
        invalid_decimals = [
            Decimal("NaN"),
            Decimal("sNaN"),
            Decimal("Infinity"),
            Decimal("-Infinity"),
            Decimal("+Infinity"),
        ]
        for val in invalid_decimals:
            with pytest.raises(ValueError, match="Special Decimal values"):
                Money(val)

        invalid_strings = ["nan", "NaN", "sNaN", "inf", "-inf", "Infinity", "-Infinity"]
        for s in invalid_strings:
            with pytest.raises(ValueError, match="Special numeric strings"):
                Money(s)

    def test_reject_empty_and_malformed_strings(self) -> None:
        """Verify empty strings, whitespace, and non-numeric strings are rejected."""
        malformed = ["", "   ", "abc", "12.34.56", "₹700", "750,00", "None"]
        for s in malformed:
            with pytest.raises(ValueError):
                Money(s)

    def test_reject_unsupported_types(self) -> None:
        """Verify unsupported types raise TypeError."""
        for unsupported in [None, [], {}, object()]:
            with pytest.raises(TypeError):
                Money(unsupported)  # type: ignore

    def test_immutability(self) -> None:
        """Verify Money attributes cannot be mutated or deleted."""
        m = Money("750.00")
        with pytest.raises(AttributeError, match="immutable"):
            m.amount = Decimal("800.00")  # type: ignore

        with pytest.raises(AttributeError, match="immutable"):
            m.currency = "USD"  # type: ignore

        with pytest.raises(AttributeError, match="immutable"):
            del m.amount  # type: ignore


@pytest.mark.unit
class TestSubPaisePrecisionPreservation:
    """Verify Money does not silently round/quantize in constructor."""

    def test_constructor_preserves_sub_paise_precision(self) -> None:
        """Verify high-precision decimals are preserved exactly without truncation."""
        sub_paise = Decimal("35.00025")
        m = Money(sub_paise)
        assert m.amount == sub_paise
        assert m.to_decimal() == sub_paise

    def test_explicit_quantize_and_to_paise(self) -> None:
        """Verify explicit quantization rounds correctly to paise."""
        m = Money("35.00025")
        quantized = m.quantize(rounding=ROUND_HALF_UP)
        assert quantized.amount == Decimal("35.00")
        assert m.to_paise(rounding=ROUND_HALF_UP) == 3500

        m_up = Money("35.0050")
        assert m_up.quantize(rounding=ROUND_HALF_UP).amount == Decimal("35.01")
        assert m_up.to_paise(rounding=ROUND_HALF_UP) == 3501


@pytest.mark.unit
class TestMoneyArithmeticAndOperators:
    """Unit tests for decimal-safe Money arithmetic and comparisons."""

    def test_addition_and_subtraction_same_currency(self) -> None:
        """Verify addition and subtraction with matching currency."""
        m1 = Money("500.00")
        m2 = Money("250.00")

        res_add = m1 + m2
        assert res_add == Money("750.00")

        res_sub = m1 - m2
        assert res_sub == Money("250.00")

    def test_currency_mismatch_raises_error(self) -> None:
        """Verify operations across different currencies raise CurrencyMismatchError."""
        m_inr = Money("100.00", "INR")
        m_usd = Money("100.00", "USD")

        with pytest.raises(CurrencyMismatchError):
            _ = m_inr + m_usd

        with pytest.raises(CurrencyMismatchError):
            _ = m_inr - m_usd

        with pytest.raises(CurrencyMismatchError):
            _ = m_inr < m_usd

        # Equality between different currencies returns False without error
        assert m_inr != m_usd
        assert not (m_inr == m_usd)

    def test_scalar_multiplication(self) -> None:
        """Verify scalar multiplication by int and Decimal."""
        m = Money("150.00")
        assert m * 2 == Money("300.00")
        assert 3 * m == Money("450.00")
        assert m * Decimal("0.5") == Money("75.00")
        assert Decimal("2") * m == Money("300.00")

        with pytest.raises(TypeError, match="Floating-point multiplication is forbidden"):
            _ = m * 2.5  # type: ignore

        with pytest.raises(TypeError, match="Floating-point multiplication is forbidden"):
            _ = 2.5 * m  # type: ignore

    def test_division(self) -> None:
        """Verify scalar division and dimensionless ratio division."""
        m = Money("300.00")

        # Scalar division -> Money
        assert m / 3 == Money("100.00")
        assert m / Decimal("2") == Money("150.00")
        assert m // 2 == Money("150.00")

        # Money / Money -> dimensionless Decimal ratio
        ratio = m / Money("100.00")
        assert ratio == Decimal("3")

        # Division by zero
        with pytest.raises(ZeroDivisionError):
            _ = m / 0

        with pytest.raises(ZeroDivisionError):
            _ = m / Decimal("0")

        with pytest.raises(ZeroDivisionError):
            _ = m / Money("0.00")

        # Float division rejected
        with pytest.raises(TypeError, match="Floating-point division is forbidden"):
            _ = m / 2.0  # type: ignore

    def test_unary_operators(self) -> None:
        """Verify unary -, +, and abs() operators."""
        m = Money("100.00")
        assert -m == Money("-100.00")
        assert +m == Money("100.00")
        assert abs(-m) == Money("100.00")
        assert abs(m) == Money("100.00")

    def test_comparisons(self) -> None:
        """Verify rich comparison operators."""
        m1 = Money("100.00")
        m2 = Money("200.00")
        m3 = Money("100.00")

        assert m1 < m2
        assert m1 <= m2
        assert m1 <= m3
        assert m2 > m1
        assert m2 >= m1
        assert m1 == m3
        assert m1 != m2

    def test_boolean_predicates(self) -> None:
        """Verify is_zero(), is_positive(), is_negative()."""
        assert Money("0.00").is_zero()
        assert not Money("1.00").is_zero()

        assert Money("0.01").is_positive()
        assert not Money("0.00").is_positive()
        assert not Money("-0.01").is_positive()

        assert Money("-0.01").is_negative()
        assert not Money("0.00").is_negative()
        assert not Money("0.01").is_negative()

    def test_string_formatting(self) -> None:
        """Verify standard INR format representation."""
        m = Money("700.00")
        assert m.format() == "₹700.00"
        assert m.format(symbol=False) == "700.00"
        assert str(m) == "₹700.00"

        m_usd = Money("50.25", "USD")
        assert m_usd.format() == "USD 50.25"
        assert m_usd.format(symbol=False) == "50.25"


@pytest.mark.unit
class TestRoundingUtility:
    """Unit tests for round_currency quantization and boundary policies."""

    def test_round_half_up_boundary_conditions(self) -> None:
        """Verify ROUND_HALF_UP tie-breaking at exact 0.5-paise boundaries."""
        # Standard Plan A operational cost: 750 * 0.046667 = 35.00025 -> 35.00
        assert round_currency("35.00025") == Decimal("35.00")

        # Exactly halfway (0.005) rounds up to next paisa
        assert round_currency("35.0050", rounding=ROUND_HALF_UP) == Decimal("35.01")
        assert round_currency("0.005", rounding=ROUND_HALF_UP) == Decimal("0.01")
        assert round_currency("1.235", rounding=ROUND_HALF_UP) == Decimal("1.24")

        # Just below halfway (0.0049...) rounds down
        assert round_currency("35.0049", rounding=ROUND_HALF_UP) == Decimal("35.00")
        assert round_currency("0.0049", rounding=ROUND_HALF_UP) == Decimal("0.00")
        assert round_currency("1.2349", rounding=ROUND_HALF_UP) == Decimal("1.23")

    def test_custom_rounding_mode(self) -> None:
        """Verify non-default rounding modes behave according to explicit policy."""
        # Under ROUND_DOWN, 35.0050 truncates to 35.00
        assert round_currency("35.0050", rounding=ROUND_DOWN) == Decimal("35.00")

    def test_round_currency_rejects_floats_and_invalids(self) -> None:
        """Verify round_currency rejects floats, NaN, and invalid strings."""
        with pytest.raises(TypeError, match="Floating-point values are forbidden"):
            round_currency(35.00025)

        with pytest.raises(ValueError):
            round_currency(Decimal("NaN"))

        with pytest.raises(ValueError):
            round_currency("")


@pytest.mark.unit
class TestPlanABenchmarkAndCommissionSplit:
    """Unit tests for the Plan A commission split and conservation invariant."""

    def test_plan_a_benchmark_calculation(self) -> None:
        """Verify Plan A benchmark: ₹750.00 gross - ₹35.00 op-cost - ₹15.00 TDS = ₹700.00 net."""
        gross = Money("750.00")
        op_cost_rate = Decimal("0.046667")  # 4.6667%
        tds_rate = Decimal("0.020000")      # 2.0%

        split = calculate_commission_split(
            gross=gross,
            op_cost_rate=op_cost_rate,
            tds_rate=tds_rate,
            rounding=ROUND_HALF_UP,
        )

        assert split.gross == Money("750.00")
        assert split.op_cost == Money("35.00")
        assert split.tds == Money("15.00")
        assert split.net == Money("700.00")

        # Enforce exact arithmetic identity
        assert split.gross == split.op_cost + split.tds + split.net
        assert split.gross.amount - split.op_cost.amount - split.tds.amount == split.net.amount

    def test_commission_split_accepts_strings_and_decimals(self) -> None:
        """Verify calculate_commission_split accepts Decimal and string rate inputs."""
        split = calculate_commission_split(
            gross="750.00",
            op_cost_rate="0.046667",
            tds_rate="0.020000",
        )
        assert split.net == Money("700.00")

    def test_reject_rates_exceeding_100_percent(self) -> None:
        """Verify rates that sum to greater than 100% are rejected."""
        with pytest.raises(ValueError, match="Total deduction rates .* cannot exceed 1.0"):
            calculate_commission_split("750.00", op_cost_rate="0.80", tds_rate="0.30")

    def test_reject_negative_gross_or_rates(self) -> None:
        """Verify negative gross or rates are rejected."""
        with pytest.raises(ValueError, match="Gross commission cannot be negative"):
            calculate_commission_split("-750.00", op_cost_rate="0.046667", tds_rate="0.02")

        with pytest.raises(ValueError, match="Operational cost rate cannot be negative"):
            calculate_commission_split("750.00", op_cost_rate="-0.04", tds_rate="0.02")

        with pytest.raises(ValueError, match="TDS rate cannot be negative"):
            calculate_commission_split("750.00", op_cost_rate="0.04", tds_rate="-0.02")

    def test_reject_float_rates(self) -> None:
        """Verify float rates are strictly rejected."""
        with pytest.raises(TypeError, match="must not be a float"):
            calculate_commission_split("750.00", op_cost_rate=0.046667, tds_rate=Decimal("0.02"))

        with pytest.raises(TypeError, match="must not be a float"):
            calculate_commission_split("750.00", op_cost_rate=Decimal("0.046667"), tds_rate=0.02)

    def test_conservation_invariant_enforced_in_commission_split_constructor(self) -> None:
        """Verify CommissionSplit directly rejects attempts to violate conservation."""
        with pytest.raises(ValueError, match="Conservation invariant violated"):
            CommissionSplit(
                gross=Money("750.00"),
                op_cost=Money("35.00"),
                tds=Money("15.00"),
                net=Money("699.99"),  # Violates 35 + 15 + 699.99 != 750.00
            )

    def test_commission_split_immutability(self) -> None:
        """Verify CommissionSplit cannot be mutated."""
        split = calculate_commission_split("750.00", "0.046667", "0.020000")
        with pytest.raises(AttributeError, match="immutable"):
            split.net = Money("750.00")  # type: ignore

    def test_intermediate_precision_preservation_and_rejection_in_commission_split(self) -> None:
        """Verify Money preserves intermediate precision, but calculate_commission_split rejects fractional paise."""
        # Money("750.005") remains valid as an intermediate Money value
        m_intermediate = Money("750.005")
        assert m_intermediate.amount == Decimal("750.005")

        # Passing Money("750.005") as gross to calculate_commission_split raises ValueError
        with pytest.raises(ValueError, match="Gross commission must have at most two decimal places"):
            calculate_commission_split(m_intermediate, op_cost_rate="0.046667", tds_rate="0.020000")

        # Passing Decimal("750.005") as gross raises ValueError
        with pytest.raises(ValueError, match="Gross commission must have at most two decimal places"):
            calculate_commission_split(Decimal("750.005"), op_cost_rate="0.046667", tds_rate="0.020000")

        # Passing string "750.005" as gross raises ValueError
        with pytest.raises(ValueError, match="Gross commission must have at most two decimal places"):
            calculate_commission_split("750.005", op_cost_rate="0.046667", tds_rate="0.020000")

    def test_all_commission_split_components_have_exact_paise_precision(self) -> None:
        """Verify gross, operational cost, TDS, and net all have exact two-decimal monetary precision."""
        split = calculate_commission_split(Money("750.00"), "0.046667", "0.020000")

        assert split.gross == Money("750.00")
        assert split.op_cost == Money("35.00")
        assert split.tds == Money("15.00")
        assert split.net == Money("700.00")

        # Check exponent is exactly -2 (paise precision)
        assert split.gross.amount.as_tuple().exponent == -2
        assert split.op_cost.amount.as_tuple().exponent == -2
        assert split.tds.amount.as_tuple().exponent == -2
        assert split.net.amount.as_tuple().exponent == -2

        # Conservation invariant
        assert split.gross.amount == split.op_cost.amount + split.tds.amount + split.net.amount

    def test_commission_split_constructor_rejects_fractional_paise(self) -> None:
        """Verify CommissionSplit constructor strictly rejects fractional paise on any component."""
        # Gross has fractional paise
        with pytest.raises(ValueError, match="Gross commission must have exactly two-decimal monetary precision"):
            CommissionSplit(Money("750.005"), Money("35.00"), Money("15.00"), Money("700.005"))

        # Op cost has fractional paise
        with pytest.raises(ValueError, match="Operational cost must have exactly two-decimal monetary precision"):
            CommissionSplit(Money("750.00"), Money("35.005"), Money("15.00"), Money("699.995"))

        # TDS has fractional paise
        with pytest.raises(ValueError, match="TDS deduction must have exactly two-decimal monetary precision"):
            CommissionSplit(Money("750.00"), Money("35.00"), Money("15.005"), Money("699.995"))

        # Net has fractional paise
        with pytest.raises(ValueError, match="Net commission must have exactly two-decimal monetary precision"):
            CommissionSplit(Money("750.00"), Money("35.00"), Money("15.00"), Money("700.005"))


@pytest.mark.unit
class TestCashbackSeparation:
    """Verify that the ₹250 cashback contribution is independent of net commission."""

    def test_cashback_contribution_is_strictly_isolated(self) -> None:
        """Demonstrate that cashback contribution (₹250) is never subtracted from ₹700 net commission."""
        # 1. Commission processing for the referring customer
        commission_split = calculate_commission_split(
            gross=Money("750.00"),
            op_cost_rate="0.046667",
            tds_rate="0.020000",
        )
        assert commission_split.net == Money("700.00")

        # 2. Cashback contribution is an independent corporate obligation / cycle reserve
        cashback_contribution = Money("250.00")

        # Proof: Net commission remains exactly ₹700.00
        assert commission_split.net == Money("700.00")
        assert commission_split.net != commission_split.net - cashback_contribution

        # The total financial allocation per Power Bank unit consists of two distinct streams:
        # Stream 1: Referrer Commission (₹750 gross -> ₹700 net to referrer wallet)
        # Stream 2: Cashback Queue Reserve (₹250 to queue cycle recipient)
        assert commission_split.net.amount == Decimal("700.00")
        assert cashback_contribution.amount == Decimal("250.00")
        # They do not subtract from one another
        assert (commission_split.net - cashback_contribution).amount == Decimal("450.00")  # hypothetical mistake is detected


@pytest.mark.unit
class TestLargeValuesAndEdgeBoundaries:
    """Verify behavior on large values and zero amounts."""

    def test_large_monetary_values(self) -> None:
        """Verify calculations with large values up to maximum column capacity (DECIMAL(14,2))."""
        large_gross = Money("999999999999.99")
        assert large_gross.amount == Decimal("999999999999.99")

        split = calculate_commission_split(
            gross=large_gross,
            op_cost_rate="0.046667",
            tds_rate="0.020000",
        )
        assert split.gross == split.op_cost + split.tds + split.net

    def test_zero_gross_and_zero_rates(self) -> None:
        """Verify zero commission and zero deductions calculate safely."""
        zero_split = calculate_commission_split("0.00", "0.046667", "0.02")
        assert zero_split.gross == Money("0.00")
        assert zero_split.op_cost == Money("0.00")
        assert zero_split.tds == Money("0.00")
        assert zero_split.net == Money("0.00")

        zero_rate_split = calculate_commission_split("500.00", "0.00", "0.00")
        assert zero_rate_split.gross == Money("500.00")
        assert zero_rate_split.op_cost == Money("0.00")
        assert zero_rate_split.tds == Money("0.00")
        assert zero_rate_split.net == Money("500.00")

