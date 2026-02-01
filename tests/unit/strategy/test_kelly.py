"""
Unit tests for Kelly Criterion position sizing.
"""

import pytest
from strategy.kelly import KellyCriterion, kelly_size, expected_growth_rate


class TestKellyCriterion:
    """Tests for KellyCriterion calculator."""

    @pytest.fixture
    def kelly(self):
        return KellyCriterion(
            kelly_fraction=0.25,
            max_position_pct=0.30,
            max_position_size=3.0,
            min_bet_size=0.10,
        )

    def test_positive_ev_bet(self, kelly):
        """Test sizing for a positive EV opportunity."""
        result = kelly.calculate(
            probability=0.60,
            odds=1.0,  # Even odds
            bankroll=10.0,
            confidence=1.0,
        )

        assert result.positive_ev
        assert result.full_kelly > 0
        assert result.recommended_bet > 0
        assert result.recommended_bet <= 3.0  # Max position cap

    def test_negative_ev_bet(self, kelly):
        """Test that negative EV bets return zero."""
        result = kelly.calculate(
            probability=0.40,
            odds=1.0,  # Even odds
            bankroll=10.0,
        )

        assert not result.positive_ev
        assert result.recommended_bet == 0
        assert result.full_kelly < 0

    def test_kelly_fraction_applied(self, kelly):
        """Test that quarter-Kelly is applied."""
        result = kelly.calculate(
            probability=0.70,
            odds=1.0,
            bankroll=100.0,
        )

        # Full Kelly would be (0.7 * 1 - 0.3) / 1 = 0.4
        expected_full = 0.40
        assert abs(result.full_kelly - expected_full) < 0.01

        # Quarter Kelly = 0.4 * 0.25 = 0.10
        assert result.fractional_kelly < result.full_kelly

    def test_confidence_adjustment(self, kelly):
        """Test confidence scaling."""
        high_conf = kelly.calculate(
            probability=0.70,
            odds=1.0,
            bankroll=10.0,
            confidence=1.0,
        )

        low_conf = kelly.calculate(
            probability=0.70,
            odds=1.0,
            bankroll=10.0,
            confidence=0.5,
        )

        assert low_conf.recommended_bet < high_conf.recommended_bet

    def test_max_position_cap(self, kelly):
        """Test position size capping."""
        result = kelly.calculate(
            probability=0.90,
            odds=2.0,
            bankroll=100.0,
            confidence=1.0,
        )

        assert result.capped
        assert result.recommended_bet <= 3.0

    def test_min_bet_threshold(self, kelly):
        """Test minimum bet size filter."""
        result = kelly.calculate(
            probability=0.51,
            odds=1.0,
            bankroll=1.0,
            confidence=0.5,
        )

        # Very small bets should be zeroed out
        assert result.recommended_bet == 0 or result.recommended_bet >= 0.10

    def test_size_trade_buy_yes(self, kelly):
        """Test convenience method for YES trades."""
        result = kelly.size_trade(
            estimated_prob=0.70,
            market_price=0.50,
            bankroll=10.0,
            confidence=0.8,
            buying_yes=True,
        )

        assert result.positive_ev
        assert result.recommended_bet > 0

    def test_size_trade_buy_no(self, kelly):
        """Test convenience method for NO trades."""
        result = kelly.size_trade(
            estimated_prob=0.30,  # Low YES probability = high NO probability
            market_price=0.50,
            bankroll=10.0,
            confidence=0.8,
            buying_yes=False,
        )

        assert result.positive_ev
        assert result.recommended_bet > 0

    def test_edge_cases(self, kelly):
        """Test edge cases don't cause errors."""
        # Probability at boundaries
        kelly.calculate(probability=0.01, odds=1.0, bankroll=10.0)
        kelly.calculate(probability=0.99, odds=1.0, bankroll=10.0)

        # Zero bankroll
        result = kelly.calculate(probability=0.70, odds=1.0, bankroll=0.0)
        assert result.recommended_bet == 0

        # Very low odds
        kelly.calculate(probability=0.70, odds=0.01, bankroll=10.0)


class TestKellySizeUtility:
    """Tests for kelly_size utility function."""

    def test_quick_sizing(self):
        size = kelly_size(
            probability=0.65,
            market_price=0.50,
            bankroll=10.0,
            confidence=0.8,
        )
        assert size >= 0

    def test_returns_zero_for_no_edge(self):
        size = kelly_size(
            probability=0.50,
            market_price=0.50,
            bankroll=10.0,
        )
        assert size == 0


class TestExpectedGrowthRate:
    """Tests for expected growth rate calculation."""

    def test_optimal_at_kelly(self):
        """Growth rate should be maximized at Kelly fraction."""
        probability = 0.60
        odds = 1.0
        kelly_f = (probability * odds - (1 - probability)) / odds

        # Calculate growth at Kelly
        growth_at_kelly = expected_growth_rate(probability, odds, kelly_f)

        # Compare to half-Kelly
        growth_at_half = expected_growth_rate(probability, odds, kelly_f / 2)

        # Kelly should give higher (or equal) growth
        assert growth_at_kelly >= growth_at_half - 0.001

    def test_zero_fraction_zero_growth(self):
        """Zero bet should give zero growth."""
        growth = expected_growth_rate(0.60, 1.0, 0.001)
        assert abs(growth) < 0.01

    def test_over_kelly_reduces_growth(self):
        """Betting more than Kelly should reduce growth."""
        probability = 0.60
        odds = 1.0
        kelly_f = (probability * odds - (1 - probability)) / odds

        growth_at_kelly = expected_growth_rate(probability, odds, kelly_f)
        growth_over_kelly = expected_growth_rate(probability, odds, kelly_f * 1.5)

        assert growth_at_kelly > growth_over_kelly


class TestKellyEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_very_high_probability(self):
        kelly = KellyCriterion()
        result = kelly.calculate(
            probability=0.95,
            odds=0.1,  # Low payout for high probability
            bankroll=10.0,
        )
        # Should still work without errors
        assert isinstance(result.recommended_bet, float)

    def test_very_low_probability(self):
        kelly = KellyCriterion()
        result = kelly.calculate(
            probability=0.05,
            odds=20.0,  # High payout for low probability
            bankroll=10.0,
        )
        assert isinstance(result.recommended_bet, float)

    def test_expected_value_calculation(self):
        kelly = KellyCriterion()
        result = kelly.calculate(
            probability=0.60,
            odds=1.5,
            bankroll=10.0,
        )

        if result.positive_ev:
            # EV should be positive when we have edge
            assert result.expected_value >= 0
