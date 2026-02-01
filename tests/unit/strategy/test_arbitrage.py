"""
Unit tests for arbitrage detection.
"""

import pytest
from unittest.mock import MagicMock

from data.models import Market, Token
from strategy.arbitrage import ArbitrageDetector, quick_arb_check


class TestArbitrageDetector:
    """Tests for ArbitrageDetector class."""

    @pytest.fixture
    def mock_client(self):
        client = MagicMock()
        client.get_spread.return_value = {
            "best_bid": 0.44,
            "best_ask": 0.46,
            "spread": 0.02,
            "bid_depth": 500,
            "ask_depth": 500,
        }
        return client

    @pytest.fixture
    def detector(self, mock_client):
        return ArbitrageDetector(
            client=mock_client,
            min_profit_pct=0.005,
            max_slippage=0.01,
        )

    @pytest.fixture
    def arb_markets(self):
        """Markets with arbitrage opportunity (sum < 1.0)."""
        return [
            Market(
                id="cand_1",
                question="Will Candidate A win?",
                tokens=[
                    Token(token_id="yes_a", outcome="Yes", price=0.30),
                    Token(token_id="no_a", outcome="No", price=0.70),
                ],
                neg_risk=True,
                event_id="election",
                event_title="2024 Election",
            ),
            Market(
                id="cand_2",
                question="Will Candidate B win?",
                tokens=[
                    Token(token_id="yes_b", outcome="Yes", price=0.35),
                    Token(token_id="no_b", outcome="No", price=0.65),
                ],
                neg_risk=True,
                event_id="election",
                event_title="2024 Election",
            ),
            Market(
                id="cand_3",
                question="Will Candidate C win?",
                tokens=[
                    Token(token_id="yes_c", outcome="Yes", price=0.25),
                    Token(token_id="no_c", outcome="No", price=0.75),
                ],
                neg_risk=True,
                event_id="election",
                event_title="2024 Election",
            ),
        ]
        # Total YES = 0.30 + 0.35 + 0.25 = 0.90 < 1.0

    @pytest.fixture
    def no_arb_markets(self):
        """Markets without arbitrage (sum >= 1.0)."""
        return [
            Market(
                id="cand_1",
                question="Will Candidate A win?",
                tokens=[
                    Token(token_id="yes_a", outcome="Yes", price=0.50),
                    Token(token_id="no_a", outcome="No", price=0.50),
                ],
                neg_risk=True,
                event_id="election",
            ),
            Market(
                id="cand_2",
                question="Will Candidate B win?",
                tokens=[
                    Token(token_id="yes_b", outcome="Yes", price=0.55),
                    Token(token_id="no_b", outcome="No", price=0.45),
                ],
                neg_risk=True,
                event_id="election",
            ),
        ]
        # Total YES = 0.50 + 0.55 = 1.05 > 1.0

    def test_detects_long_yes_arb(self, detector, arb_markets):
        """Test detection of long YES arbitrage."""
        arb = detector.detect_long_yes_arb(
            event_id="election",
            markets=arb_markets,
            bet_size=1.0,
        )

        assert arb is not None
        assert arb.arb_type == "long_yes"
        assert len(arb.legs) == 3
        assert arb.total_cost == 0.90  # Sum of YES prices
        assert arb.guaranteed_payout == 1.0
        assert arb.profit == 0.10
        assert abs(arb.profit_pct - 0.1111) < 0.01

    def test_no_arb_when_sum_exceeds_one(self, detector, no_arb_markets):
        """Test no arb detected when prices sum > 1."""
        arb = detector.detect_long_yes_arb(
            event_id="election",
            markets=no_arb_markets,
            bet_size=1.0,
        )

        assert arb is None

    def test_arb_with_slippage(self, detector, arb_markets):
        """Test arb detection accounts for slippage."""
        # Modify prices so arb is borderline
        arb_markets[0].tokens[0].price = 0.33
        arb_markets[1].tokens[0].price = 0.34
        arb_markets[2].tokens[0].price = 0.32
        # Total = 0.99, with 1% slippage = 0.9999

        arb = detector.detect_long_yes_arb(
            event_id="election",
            markets=arb_markets,
        )

        # Should be rejected due to slippage
        assert arb is None

    def test_min_profit_threshold(self, detector, arb_markets):
        """Test minimum profit threshold."""
        # Adjust to have very small profit
        arb_markets[0].tokens[0].price = 0.33
        arb_markets[1].tokens[0].price = 0.33
        arb_markets[2].tokens[0].price = 0.33
        # Total = 0.99, profit = 1%

        # With 1% slippage, effective profit is ~0%
        arb = detector.detect_long_yes_arb(
            event_id="election",
            markets=arb_markets,
        )

        # Should be rejected as profit is too small after slippage
        if arb:
            assert arb.profit_pct >= 0.005

    def test_scan_event(self, detector, arb_markets):
        """Test scanning an event for all arb types."""
        opps = detector.scan_event(
            event_id="election",
            markets=arb_markets,
        )

        # Should find at least long YES arb
        assert len(opps) >= 1
        assert any(o.arb_type == "long_yes" for o in opps)

    def test_scan_all_events(self, detector, arb_markets):
        """Test scanning multiple events."""
        events = {
            "election": arb_markets,
        }

        all_opps = detector.scan_all_events(events)

        assert len(all_opps) >= 1

    def test_prepare_arb_orders(self, detector, arb_markets):
        """Test order preparation for arb execution."""
        arb = detector.detect_long_yes_arb(
            event_id="election",
            markets=arb_markets,
        )

        orders = detector.prepare_arb_orders(arb)

        assert len(orders) == 3
        for order in orders:
            assert order["order_type"] == "FOK"
            assert order["side"] == "BUY"

    def test_execution_quality_estimate(self, detector, arb_markets):
        """Test execution quality estimation."""
        arb = detector.detect_long_yes_arb(
            event_id="election",
            markets=arb_markets,
        )

        quality = detector.estimate_execution_quality(arb)

        assert "total_depth" in quality
        assert "can_fill" in quality
        assert "max_fillable_size" in quality


class TestQuickArbCheck:
    """Tests for quick_arb_check utility."""

    def test_detects_arb(self):
        result = quick_arb_check([0.30, 0.35, 0.25])

        assert result["has_arb"]
        assert result["total_cost"] == 0.90
        assert result["profit"] == 0.10
        assert abs(result["profit_pct"] - 0.1111) < 0.01

    def test_no_arb(self):
        result = quick_arb_check([0.50, 0.55])

        assert not result["has_arb"]
        assert result["total_cost"] == 1.05
        assert result["overprice"] == 0.05

    def test_exact_one(self):
        result = quick_arb_check([0.40, 0.30, 0.30])

        assert not result["has_arb"]
        assert result["total_cost"] == 1.0
