"""
Edge detection: Compare AI probability estimates to market prices.
"""

from dataclasses import dataclass
from typing import Optional

from config import settings
from data.models import Market, ProbabilityEstimate, Side
from utils.logger import get_logger

logger = get_logger("polymarket.edge")


@dataclass
class EdgeOpportunity:
    """Represents a detected trading edge."""
    market: Market
    estimate: ProbabilityEstimate

    # Edge details
    edge: float  # Probability - market price (positive = buy YES)
    edge_abs: float  # Absolute edge
    edge_pct: float  # Edge as percentage of market price

    # Trade direction
    side: Side  # BUY for positive edge, SELL for negative
    outcome: str  # "Yes" or "No"
    token_id: str

    # Entry price
    entry_price: float

    # Confidence-adjusted edge
    confidence_adjusted_edge: float

    # Whether this passes minimum threshold
    tradeable: bool


class EdgeDetector:
    """
    Detects trading edges by comparing AI estimates to market prices.
    """

    def __init__(
        self,
        min_edge: float = None,
        min_confidence: float = 0.3,
    ):
        self.min_edge = min_edge or settings.risk.min_edge_threshold
        self.min_confidence = min_confidence

    def calculate_edge(
        self,
        market: Market,
        estimate: ProbabilityEstimate,
    ) -> EdgeOpportunity:
        """
        Calculate edge for a market given an AI probability estimate.

        Edge = Our probability - Market probability

        If edge > 0: We think YES is more likely than market -> BUY YES
        If edge < 0: We think NO is more likely than market -> BUY NO

        Returns:
            EdgeOpportunity with all calculated fields
        """
        market_price = estimate.market_price  # YES price
        our_prob = estimate.probability

        # Raw edge (from YES perspective)
        edge = our_prob - market_price

        # Determine trade direction
        if edge > 0:
            # We think YES is underpriced -> BUY YES
            side = Side.BUY
            outcome = "Yes"
            entry_price = market_price
            token_id = self._get_token_id(market, "yes")
        else:
            # We think NO is underpriced -> BUY NO
            side = Side.BUY
            outcome = "No"
            # NO price is approximately 1 - YES price
            entry_price = 1 - market_price
            token_id = self._get_token_id(market, "no")
            # Flip edge to be positive for NO trade
            edge = abs(edge)

        edge_abs = abs(edge)
        edge_pct = edge_abs / max(entry_price, 0.01)  # Avoid division by zero

        # Confidence-adjusted edge
        confidence = estimate.confidence
        confidence_adjusted_edge = edge_abs * confidence

        # Check if tradeable
        tradeable = (
            edge_abs >= self.min_edge
            and confidence >= self.min_confidence
        )

        return EdgeOpportunity(
            market=market,
            estimate=estimate,
            edge=edge,
            edge_abs=edge_abs,
            edge_pct=edge_pct,
            side=side,
            outcome=outcome,
            token_id=token_id,
            entry_price=entry_price,
            confidence_adjusted_edge=confidence_adjusted_edge,
            tradeable=tradeable,
        )

    def _get_token_id(self, market: Market, outcome: str) -> str:
        """Get token ID for specified outcome."""
        for token in market.tokens:
            if token.outcome.lower() == outcome.lower():
                return token.token_id
        return ""

    def find_edges(
        self,
        markets_with_estimates: list[tuple[Market, ProbabilityEstimate]],
    ) -> list[EdgeOpportunity]:
        """
        Find all tradeable edges from a list of analyzed markets.

        Returns list of EdgeOpportunity sorted by edge size (descending).
        """
        edges = []

        for market, estimate in markets_with_estimates:
            edge_opp = self.calculate_edge(market, estimate)
            if edge_opp.tradeable:
                edges.append(edge_opp)

        # Sort by confidence-adjusted edge (best opportunities first)
        edges.sort(key=lambda e: e.confidence_adjusted_edge, reverse=True)

        logger.info(f"Found {len(edges)} tradeable edges")
        return edges

    def rank_opportunities(
        self,
        opportunities: list[EdgeOpportunity],
        consider_liquidity: bool = True,
    ) -> list[EdgeOpportunity]:
        """
        Rank opportunities by attractiveness.

        Factors:
        1. Confidence-adjusted edge (higher is better)
        2. Market liquidity (higher is better for execution)
        3. Time to resolution (shorter can be better for capital efficiency)
        """
        def score(opp: EdgeOpportunity) -> float:
            base_score = opp.confidence_adjusted_edge * 100

            # Liquidity bonus (log scale)
            if consider_liquidity and opp.market.liquidity > 0:
                import math
                base_score += math.log10(opp.market.liquidity + 1) * 2

            # Time bonus for near-term resolution
            hours = opp.market.hours_to_resolution
            if hours and hours < 24 * 14:  # Within 2 weeks
                base_score += (14 - hours / 24) * 0.5

            return base_score

        return sorted(opportunities, key=score, reverse=True)

    def summarize_opportunity(self, opp: EdgeOpportunity) -> str:
        """Generate a human-readable summary of an opportunity."""
        return (
            f"{opp.outcome} on '{opp.market.question[:50]}...'\n"
            f"  Edge: {opp.edge_abs:.1%} (conf-adj: {opp.confidence_adjusted_edge:.1%})\n"
            f"  Our P({opp.outcome}): {opp.estimate.probability:.1%}\n"
            f"  Market: {opp.entry_price:.1%}\n"
            f"  Confidence: {opp.estimate.confidence:.1%}\n"
            f"  Liquidity: ${opp.market.liquidity:,.0f}"
        )


def quick_edge_check(
    our_probability: float,
    market_price: float,
    min_edge: float = 0.05,
) -> dict:
    """
    Quick utility function to check for edge.

    Args:
        our_probability: Our estimated probability for YES
        market_price: Current market price for YES
        min_edge: Minimum edge threshold

    Returns:
        Dict with edge info and trade recommendation
    """
    edge = our_probability - market_price

    if abs(edge) < min_edge:
        return {
            "has_edge": False,
            "edge": edge,
            "recommendation": "NO_TRADE",
            "reason": f"Edge {abs(edge):.1%} below threshold {min_edge:.1%}",
        }

    if edge > 0:
        return {
            "has_edge": True,
            "edge": edge,
            "direction": "YES",
            "recommendation": "BUY_YES",
            "reason": f"YES underpriced by {edge:.1%}",
        }
    else:
        return {
            "has_edge": True,
            "edge": abs(edge),
            "direction": "NO",
            "recommendation": "BUY_NO",
            "reason": f"NO underpriced by {abs(edge):.1%}",
        }
