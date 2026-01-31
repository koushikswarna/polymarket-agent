"""
Kelly Criterion position sizing for optimal bet sizing.
"""

from dataclasses import dataclass
from typing import Optional

from config import settings
from utils.logger import get_logger

logger = get_logger("polymarket.kelly")


@dataclass
class KellyResult:
    """Result of Kelly sizing calculation."""
    # Raw Kelly fraction
    full_kelly: float

    # Fractional Kelly (typically 1/4 for safety)
    fractional_kelly: float
    kelly_fraction: float

    # Dollar amounts
    optimal_bet: float
    max_bet: float
    recommended_bet: float

    # Risk metrics
    expected_value: float
    expected_return_pct: float

    # Inputs
    probability: float
    odds: float
    bankroll: float

    # Flags
    positive_ev: bool
    capped: bool
    cap_reason: str


class KellyCriterion:
    """
    Kelly Criterion calculator for position sizing.

    Uses fractional Kelly (typically 1/4) for more conservative sizing
    that accounts for:
    - Estimation errors in probability
    - Model uncertainty
    - Avoiding over-concentration
    """

    def __init__(
        self,
        kelly_fraction: float = 0.25,  # Quarter-Kelly
        max_position_pct: float = None,
        max_position_size: float = None,
        min_bet_size: float = 0.10,  # $0.10 minimum
    ):
        self.kelly_fraction = kelly_fraction
        self.max_position_pct = max_position_pct or 0.30  # Max 30% of bankroll
        self.max_position_size = max_position_size or settings.trading.max_position_size
        self.min_bet_size = min_bet_size

    def calculate(
        self,
        probability: float,
        odds: float,
        bankroll: float,
        confidence: float = 1.0,
    ) -> KellyResult:
        """
        Calculate optimal bet size using Kelly Criterion.

        The Kelly formula for binary bets:
        f* = (p * b - q) / b

        Where:
        - f* = fraction of bankroll to bet
        - p = probability of winning
        - q = probability of losing (1 - p)
        - b = odds (net payout per dollar wagered)

        For Polymarket:
        - If we buy YES at price p, odds = (1 - p) / p
        - If we buy NO at price p, odds = (1 - p) / p

        Args:
            probability: Our estimated probability of winning
            odds: Net odds (profit per dollar if win)
            bankroll: Available capital
            confidence: Confidence in probability estimate (0-1)

        Returns:
            KellyResult with sizing recommendations
        """
        # Validate inputs
        probability = max(0.01, min(0.99, probability))
        odds = max(0.01, odds)
        bankroll = max(0, bankroll)

        q = 1 - probability

        # Full Kelly formula
        full_kelly = (probability * odds - q) / odds

        # Check for positive expected value
        positive_ev = full_kelly > 0

        if not positive_ev:
            # No bet recommended
            return KellyResult(
                full_kelly=full_kelly,
                fractional_kelly=0,
                kelly_fraction=self.kelly_fraction,
                optimal_bet=0,
                max_bet=0,
                recommended_bet=0,
                expected_value=0,
                expected_return_pct=0,
                probability=probability,
                odds=odds,
                bankroll=bankroll,
                positive_ev=False,
                capped=False,
                cap_reason="Negative EV",
            )

        # Apply fractional Kelly
        fractional_kelly = full_kelly * self.kelly_fraction

        # Apply confidence adjustment
        # Lower confidence -> smaller position
        confidence_adjusted = fractional_kelly * confidence

        # Calculate dollar amounts
        optimal_bet = bankroll * confidence_adjusted

        # Apply caps
        capped = False
        cap_reason = ""

        # Cap at max percentage of bankroll
        max_pct_bet = bankroll * self.max_position_pct
        if optimal_bet > max_pct_bet:
            optimal_bet = max_pct_bet
            capped = True
            cap_reason = f"Capped at {self.max_position_pct:.0%} of bankroll"

        # Cap at absolute max position size
        if optimal_bet > self.max_position_size:
            optimal_bet = self.max_position_size
            capped = True
            cap_reason = f"Capped at ${self.max_position_size} max position"

        # Ensure minimum bet size
        if 0 < optimal_bet < self.min_bet_size:
            optimal_bet = 0  # Too small to bother
            cap_reason = "Below minimum bet size"

        # Calculate expected value
        # EV = p * (win amount) - q * (loss amount)
        # For a $1 bet at odds b: EV = p * b - q * 1 = p * b - q
        ev_per_dollar = probability * odds - q
        expected_value = optimal_bet * ev_per_dollar
        expected_return_pct = ev_per_dollar * 100

        return KellyResult(
            full_kelly=full_kelly,
            fractional_kelly=confidence_adjusted,
            kelly_fraction=self.kelly_fraction,
            optimal_bet=optimal_bet,
            max_bet=min(max_pct_bet, self.max_position_size),
            recommended_bet=optimal_bet,
            expected_value=expected_value,
            expected_return_pct=expected_return_pct,
            probability=probability,
            odds=odds,
            bankroll=bankroll,
            positive_ev=True,
            capped=capped,
            cap_reason=cap_reason,
        )

    def size_trade(
        self,
        estimated_prob: float,
        market_price: float,
        bankroll: float,
        confidence: float = 1.0,
        buying_yes: bool = True,
    ) -> KellyResult:
        """
        Convenience method to size a trade given market price.

        Args:
            estimated_prob: Our probability estimate for YES outcome
            market_price: Current market price for the token we're buying
            bankroll: Available capital
            confidence: Confidence in estimate
            buying_yes: True if buying YES, False if buying NO

        Returns:
            KellyResult with sizing
        """
        if buying_yes:
            # Probability of winning is our YES estimate
            win_prob = estimated_prob
            # Odds if we buy YES at market_price
            # If we pay $0.40 and win, we get $1.00, profit = $0.60
            # Odds = 0.60 / 0.40 = 1.5
            odds = (1 - market_price) / market_price
        else:
            # Buying NO
            # Probability of winning is 1 - our YES estimate
            win_prob = 1 - estimated_prob
            # Odds for NO token
            no_price = 1 - market_price  # Approximate
            odds = (1 - no_price) / no_price if no_price > 0 else 0

        return self.calculate(win_prob, odds, bankroll, confidence)


def kelly_size(
    probability: float,
    market_price: float,
    bankroll: float,
    confidence: float = 1.0,
    kelly_fraction: float = 0.25,
) -> float:
    """
    Quick utility function for Kelly sizing.

    Args:
        probability: Estimated probability of outcome
        market_price: Price to buy at
        bankroll: Available capital
        confidence: Confidence in estimate
        kelly_fraction: Kelly fraction to use

    Returns:
        Recommended bet size in dollars
    """
    calc = KellyCriterion(kelly_fraction=kelly_fraction)

    # Determine if we're on YES or NO side
    buying_yes = probability > market_price

    result = calc.size_trade(
        estimated_prob=probability,
        market_price=market_price if buying_yes else (1 - market_price),
        bankroll=bankroll,
        confidence=confidence,
        buying_yes=buying_yes,
    )

    return result.recommended_bet


def expected_growth_rate(
    probability: float,
    odds: float,
    fraction: float,
) -> float:
    """
    Calculate expected log growth rate (Kelly's criterion optimizes this).

    G = p * ln(1 + f * b) + q * ln(1 - f)

    Where:
    - p = probability of winning
    - q = 1 - p
    - f = fraction of bankroll to bet
    - b = odds

    Returns:
        Expected log growth rate
    """
    import math

    q = 1 - probability

    if fraction <= 0 or fraction >= 1:
        return float("-inf")

    try:
        growth = (
            probability * math.log(1 + fraction * odds) +
            q * math.log(1 - fraction)
        )
        return growth
    except (ValueError, ZeroDivisionError):
        return float("-inf")
