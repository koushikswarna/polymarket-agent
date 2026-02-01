"""
Unit tests for edge detection.
"""

import pytest
from data.models import Market, Token, ProbabilityEstimate, Side
from strategy.edge_detector import EdgeDetector, quick_edge_check, EdgeOpportunity


class TestEdgeDetector:
    """Tests for EdgeDetector class."""

    @pytest.fixture
    def detector(self):
        return EdgeDetector(min_edge=0.05, min_confidence=0.3)

    @pytest.fixture
    def bullish_market(self):
        """Market where we think YES is underpriced."""
        return Market(
            id="bull_market",
            question="Test bullish?",
            tokens=[
                Token(token_id="yes_1", outcome="Yes", price=0.45),
                Token(token_id="no_1", outcome="No", price=0.55),
            ],
        )

    @pytest.fixture
    def bullish_estimate(self):
        """Estimate suggesting YES is underpriced."""
        return ProbabilityEstimate(
            market_id="bull_market",
            probability=0.60,  # We think 60%, market says 45%
            confidence=0.75,
            model="claude",
            market_price=0.45,
            edge=0.15,
        )

    @pytest.fixture
    def bearish_estimate(self):
        """Estimate suggesting NO is underpriced."""
        return ProbabilityEstimate(
            market_id="bear_market",
            probability=0.35,  # We think 35%, market says 55%
            confidence=0.70,
            model="claude",
            market_price=0.55,
            edge=-0.20,
        )

    def test_positive_edge_detected(self, detector, bullish_market, bullish_estimate):
        """Test detection of positive edge (buy YES)."""
        edge_opp = detector.calculate_edge(bullish_market, bullish_estimate)

        assert edge_opp.edge > 0
        assert edge_opp.side == Side.BUY
        assert edge_opp.outcome == "Yes"
        assert edge_opp.tradeable

    def test_negative_edge_detected(self, detector, bullish_market, bearish_estimate):
        """Test detection of negative edge (buy NO)."""
        market = Market(
            id="bear_market",
            question="Test bearish?",
            tokens=[
                Token(token_id="yes_2", outcome="Yes", price=0.55),
                Token(token_id="no_2", outcome="No", price=0.45),
            ],
        )

        edge_opp = detector.calculate_edge(market, bearish_estimate)

        assert edge_opp.outcome == "No"
        assert edge_opp.side == Side.BUY
        assert edge_opp.tradeable

    def test_no_edge_below_threshold(self, detector, bullish_market):
        """Test that small edges are not tradeable."""
        small_edge_estimate = ProbabilityEstimate(
            market_id="bull_market",
            probability=0.47,  # Only 2% edge
            confidence=0.75,
            market_price=0.45,
            edge=0.02,
        )

        edge_opp = detector.calculate_edge(bullish_market, small_edge_estimate)

        assert not edge_opp.tradeable
        assert edge_opp.edge_abs < 0.05

    def test_low_confidence_not_tradeable(self, detector, bullish_market):
        """Test that low confidence estimates are not tradeable."""
        low_conf_estimate = ProbabilityEstimate(
            market_id="bull_market",
            probability=0.60,
            confidence=0.20,  # Below threshold
            market_price=0.45,
            edge=0.15,
        )

        edge_opp = detector.calculate_edge(bullish_market, low_conf_estimate)

        assert not edge_opp.tradeable

    def test_confidence_adjusted_edge(self, detector, bullish_market, bullish_estimate):
        """Test confidence adjustment calculation."""
        edge_opp = detector.calculate_edge(bullish_market, bullish_estimate)

        expected_adj = edge_opp.edge_abs * bullish_estimate.confidence
        assert abs(edge_opp.confidence_adjusted_edge - expected_adj) < 0.01

    def test_find_edges_filters_correctly(self, detector, bullish_market, bullish_estimate):
        """Test batch edge finding."""
        # Mix of good and bad estimates
        no_edge_estimate = ProbabilityEstimate(
            market_id="no_edge",
            probability=0.46,
            confidence=0.75,
            market_price=0.45,
            edge=0.01,
        )

        no_edge_market = Market(
            id="no_edge",
            question="No edge?",
            tokens=[
                Token(token_id="y", outcome="Yes", price=0.45),
                Token(token_id="n", outcome="No", price=0.55),
            ],
        )

        pairs = [
            (bullish_market, bullish_estimate),
            (no_edge_market, no_edge_estimate),
        ]

        edges = detector.find_edges(pairs)

        assert len(edges) == 1
        assert edges[0].market.id == "bull_market"

    def test_rank_opportunities(self, detector):
        """Test opportunity ranking."""
        opp1 = EdgeOpportunity(
            market=Market(id="m1", question="Q1", tokens=[], liquidity=1000),
            estimate=ProbabilityEstimate(
                market_id="m1", probability=0.6, confidence=0.7
            ),
            edge=0.10,
            edge_abs=0.10,
            edge_pct=0.20,
            side=Side.BUY,
            outcome="Yes",
            token_id="t1",
            entry_price=0.50,
            confidence_adjusted_edge=0.07,
            tradeable=True,
        )

        opp2 = EdgeOpportunity(
            market=Market(id="m2", question="Q2", tokens=[], liquidity=5000),
            estimate=ProbabilityEstimate(
                market_id="m2", probability=0.7, confidence=0.8
            ),
            edge=0.15,
            edge_abs=0.15,
            edge_pct=0.25,
            side=Side.BUY,
            outcome="Yes",
            token_id="t2",
            entry_price=0.55,
            confidence_adjusted_edge=0.12,
            tradeable=True,
        )

        ranked = detector.rank_opportunities([opp1, opp2])

        # Higher edge should rank first
        assert ranked[0].confidence_adjusted_edge >= ranked[1].confidence_adjusted_edge


class TestQuickEdgeCheck:
    """Tests for quick_edge_check utility."""

    def test_detects_yes_edge(self):
        result = quick_edge_check(
            our_probability=0.70,
            market_price=0.50,
            min_edge=0.05,
        )

        assert result["has_edge"]
        assert result["direction"] == "YES"
        assert result["recommendation"] == "BUY_YES"

    def test_detects_no_edge(self):
        result = quick_edge_check(
            our_probability=0.30,
            market_price=0.50,
            min_edge=0.05,
        )

        assert result["has_edge"]
        assert result["direction"] == "NO"
        assert result["recommendation"] == "BUY_NO"

    def test_no_edge_below_threshold(self):
        result = quick_edge_check(
            our_probability=0.52,
            market_price=0.50,
            min_edge=0.05,
        )

        assert not result["has_edge"]
        assert result["recommendation"] == "NO_TRADE"

    def test_edge_calculation(self):
        result = quick_edge_check(
            our_probability=0.65,
            market_price=0.50,
        )

        assert result["edge"] == 0.15

    def test_exact_threshold(self):
        result = quick_edge_check(
            our_probability=0.55,
            market_price=0.50,
            min_edge=0.05,
        )

        assert result["has_edge"]
