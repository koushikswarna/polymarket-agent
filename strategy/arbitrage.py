"""
NegRisk arbitrage detection for multi-outcome markets.

In NegRisk markets, outcomes are mutually exclusive. If the sum of
all YES prices < 1.0 (minus fees), there's an arbitrage opportunity
to buy YES on all outcomes and guarantee profit.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config import settings
from data.models import Market, ArbitrageOpportunity, Side, OrderType
from core.client import PolymarketClient
from utils.logger import get_logger

logger = get_logger("polymarket.arbitrage")


@dataclass
class ArbLeg:
    """One leg of an arbitrage trade."""
    market_id: str
    token_id: str
    outcome: str
    price: float
    size: float
    side: Side = Side.BUY


@dataclass
class ArbOpportunity:
    """Detected arbitrage opportunity."""
    event_id: str
    event_title: str
    arb_type: str  # "long_yes" (all YES < 1) or "long_no" (all NO < 1)

    legs: list[ArbLeg]

    # Financials
    total_cost: float
    guaranteed_payout: float
    profit: float
    profit_pct: float

    # Risk-adjusted (considering execution risk)
    execution_risk: float  # 0-1, higher = more risk
    risk_adjusted_profit: float

    detected_at: datetime = field(default_factory=datetime.utcnow)


class ArbitrageDetector:
    """
    Detects arbitrage opportunities in NegRisk multi-outcome markets.

    Types of arbitrage:
    1. Long YES arb: Sum of all YES prices < 1.0
       - Buy YES on all outcomes
       - One must win, paying out $1.00 per share
       - Profit = $1.00 - sum(YES prices)

    2. Long NO arb: Sum of all NO prices < 1.0
       - Buy NO on all outcomes
       - N-1 outcomes will pay out (one must lose)
       - More complex profit calculation
    """

    def __init__(
        self,
        client: PolymarketClient,
        min_profit_pct: float = 0.005,  # 0.5% minimum
        max_slippage: float = 0.01,  # 1% max slippage assumption
    ):
        self.client = client
        self.min_profit_pct = min_profit_pct
        self.max_slippage = max_slippage

    def detect_long_yes_arb(
        self,
        event_id: str,
        markets: list[Market],
        bet_size: float = 1.0,
    ) -> Optional[ArbOpportunity]:
        """
        Detect long YES arbitrage in a multi-outcome event.

        If sum(YES prices) < 1.0, we can buy YES on all outcomes
        and guarantee profit.
        """
        if len(markets) < 2:
            return None

        # Collect YES prices and token IDs
        legs = []
        total_yes_cost = 0.0

        for market in markets:
            yes_price = market.yes_price
            if yes_price is None:
                return None  # Can't price this market

            yes_token_id = None
            for token in market.tokens:
                if token.outcome.lower() == "yes":
                    yes_token_id = token.token_id
                    break

            if not yes_token_id:
                return None

            legs.append(ArbLeg(
                market_id=market.id,
                token_id=yes_token_id,
                outcome=f"YES: {market.question[:30]}...",
                price=yes_price,
                size=bet_size,
                side=Side.BUY,
            ))
            total_yes_cost += yes_price

        # Check for arbitrage (including slippage buffer)
        effective_cost = total_yes_cost * (1 + self.max_slippage)

        if effective_cost >= 1.0:
            return None  # No arb

        # Calculate profit
        total_cost = total_yes_cost * bet_size
        guaranteed_payout = 1.0 * bet_size  # One YES will win
        profit = guaranteed_payout - total_cost
        profit_pct = profit / total_cost if total_cost > 0 else 0

        if profit_pct < self.min_profit_pct:
            return None  # Profit too small

        # Estimate execution risk based on number of legs
        execution_risk = min(0.5, len(legs) * 0.05)  # 5% risk per leg, max 50%
        risk_adjusted_profit = profit * (1 - execution_risk)

        event_title = markets[0].event_title or event_id

        logger.info(
            f"Long YES arb detected on '{event_title}': "
            f"cost={total_yes_cost:.3f}, profit={profit_pct:.2%}"
        )

        return ArbOpportunity(
            event_id=event_id,
            event_title=event_title,
            arb_type="long_yes",
            legs=legs,
            total_cost=total_cost,
            guaranteed_payout=guaranteed_payout,
            profit=profit,
            profit_pct=profit_pct,
            execution_risk=execution_risk,
            risk_adjusted_profit=risk_adjusted_profit,
        )

    def detect_long_no_arb(
        self,
        event_id: str,
        markets: list[Market],
        bet_size: float = 1.0,
    ) -> Optional[ArbOpportunity]:
        """
        Detect long NO arbitrage in a multi-outcome event.

        More complex: If we buy NO on all N outcomes, then N-1
        will pay out (the losing outcome's NO tokens win).

        This is rarely profitable due to the math, but we check anyway.
        """
        if len(markets) < 2:
            return None

        legs = []
        total_no_cost = 0.0
        n_outcomes = len(markets)

        for market in markets:
            no_price = market.no_price
            if no_price is None:
                # Estimate from YES price
                yes_price = market.yes_price
                if yes_price is None:
                    return None
                no_price = 1 - yes_price

            no_token_id = None
            for token in market.tokens:
                if token.outcome.lower() == "no":
                    no_token_id = token.token_id
                    break

            if not no_token_id:
                return None

            legs.append(ArbLeg(
                market_id=market.id,
                token_id=no_token_id,
                outcome=f"NO: {market.question[:30]}...",
                price=no_price,
                size=bet_size,
                side=Side.BUY,
            ))
            total_no_cost += no_price

        # For NO arb: We pay for N NO positions, N-1 pay out
        # Profit if: total_no_cost < (N-1)
        total_cost = total_no_cost * bet_size
        guaranteed_payout = (n_outcomes - 1) * bet_size
        profit = guaranteed_payout - total_cost
        profit_pct = profit / total_cost if total_cost > 0 else 0

        if profit_pct < self.min_profit_pct:
            return None

        execution_risk = min(0.5, len(legs) * 0.05)
        risk_adjusted_profit = profit * (1 - execution_risk)

        event_title = markets[0].event_title or event_id

        logger.info(
            f"Long NO arb detected on '{event_title}': "
            f"cost={total_no_cost:.3f}, payout={n_outcomes - 1}, profit={profit_pct:.2%}"
        )

        return ArbOpportunity(
            event_id=event_id,
            event_title=event_title,
            arb_type="long_no",
            legs=legs,
            total_cost=total_cost,
            guaranteed_payout=guaranteed_payout,
            profit=profit,
            profit_pct=profit_pct,
            execution_risk=execution_risk,
            risk_adjusted_profit=risk_adjusted_profit,
        )

    def scan_event(
        self,
        event_id: str,
        markets: list[Market],
        bet_size: float = 1.0,
    ) -> list[ArbOpportunity]:
        """
        Scan an event for all types of arbitrage.

        Returns list of detected opportunities.
        """
        opportunities = []

        # Check long YES arb
        yes_arb = self.detect_long_yes_arb(event_id, markets, bet_size)
        if yes_arb:
            opportunities.append(yes_arb)

        # Check long NO arb
        no_arb = self.detect_long_no_arb(event_id, markets, bet_size)
        if no_arb:
            opportunities.append(no_arb)

        return opportunities

    def scan_all_events(
        self,
        neg_risk_events: dict[str, list[Market]],
        bet_size: float = 1.0,
    ) -> list[ArbOpportunity]:
        """
        Scan all NegRisk events for arbitrage.

        Args:
            neg_risk_events: Dict of event_id -> list of markets
            bet_size: Size per leg

        Returns:
            All detected arbitrage opportunities, sorted by profit %
        """
        all_opportunities = []

        for event_id, markets in neg_risk_events.items():
            opps = self.scan_event(event_id, markets, bet_size)
            all_opportunities.extend(opps)

        # Sort by profit percentage
        all_opportunities.sort(key=lambda x: x.profit_pct, reverse=True)

        logger.info(
            f"Scanned {len(neg_risk_events)} events, "
            f"found {len(all_opportunities)} arbitrage opportunities"
        )

        return all_opportunities

    def prepare_arb_orders(
        self,
        opportunity: ArbOpportunity,
    ) -> list[dict]:
        """
        Prepare FOK orders for arbitrage execution.

        Uses Fill-Or-Kill (FOK) orders for atomic execution.
        All orders must fill or none do.
        """
        orders = []

        for leg in opportunity.legs:
            orders.append({
                "token_id": leg.token_id,
                "side": leg.side.value,
                "price": leg.price,
                "size": leg.size,
                "order_type": OrderType.FOK.value,
                "market_id": leg.market_id,
            })

        return orders

    def estimate_execution_quality(
        self,
        opportunity: ArbOpportunity,
    ) -> dict:
        """
        Estimate execution quality by checking order book depth.
        """
        total_available = 0
        min_depth = float("inf")

        for leg in opportunity.legs:
            spread_info = self.client.get_spread(leg.token_id)
            depth = spread_info.get("ask_depth", 0)
            total_available += depth
            min_depth = min(min_depth, depth)

        return {
            "total_depth": total_available,
            "min_leg_depth": min_depth,
            "can_fill": min_depth >= opportunity.legs[0].size,
            "max_fillable_size": min_depth,
        }


def quick_arb_check(yes_prices: list[float]) -> dict:
    """
    Quick utility to check if YES prices allow arbitrage.

    Args:
        yes_prices: List of YES prices for all outcomes

    Returns:
        Dict with arb info
    """
    total = sum(yes_prices)

    if total < 1.0:
        profit_pct = (1.0 - total) / total
        return {
            "has_arb": True,
            "total_cost": total,
            "profit": 1.0 - total,
            "profit_pct": profit_pct,
        }

    return {
        "has_arb": False,
        "total_cost": total,
        "overprice": total - 1.0,
    }
