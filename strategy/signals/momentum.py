"""
Momentum-based trading signals.

Momentum strategies identify markets where prices are trending strongly
in one direction. The idea is that trends tend to persist, so we can
profit by riding the wave.

Think of it like this: If a market has moved from 30% to 50% over the
past week, there might be genuine new information causing the move,
and the trend could continue.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from data.models import Market


@dataclass
class MomentumSignal:
    """
    A momentum-based trading signal.

    Attributes:
        market_id: Which market this signal is for
        direction: "bullish" (price going up) or "bearish" (price going down)
        strength: How strong is the momentum (0.0 to 1.0)
        price_change: How much has the price changed (e.g., 0.15 = 15%)
        time_period_hours: Over what time period we measured this
        confidence: Our confidence in this signal
    """
    market_id: str
    direction: str  # "bullish" or "bearish"
    strength: float  # 0.0 to 1.0
    price_change: float  # e.g., 0.15 means price went up 15%
    time_period_hours: float
    confidence: float
    generated_at: datetime = None

    def __post_init__(self):
        if self.generated_at is None:
            self.generated_at = datetime.utcnow()

    @property
    def is_actionable(self) -> bool:
        """
        Is this signal strong enough to act on?

        We want strong momentum (strength > 0.6) with decent confidence.
        """
        return self.strength > 0.6 and self.confidence > 0.5


class MomentumAnalyzer:
    """
    Analyzes price momentum in prediction markets.

    Momentum trading works by identifying markets where prices are moving
    strongly in one direction. Unlike traditional markets, prediction markets
    are bounded between 0 and 1, so we need to be careful near the extremes.

    Example usage:
        analyzer = MomentumAnalyzer()
        signal = analyzer.analyze(market, price_history)
        if signal and signal.is_actionable:
            # Consider trading in the direction of momentum
    """

    def __init__(
        self,
        min_price_change: float = 0.05,  # Need at least 5% move
        lookback_hours: int = 24,  # Look at past 24 hours
        volume_weight: bool = True,  # Weight by trading volume
    ):
        """
        Initialize the momentum analyzer.

        Args:
            min_price_change: Minimum price change to consider significant
            lookback_hours: How far back to look for momentum
            volume_weight: Whether to weight momentum by volume
        """
        self.min_price_change = min_price_change
        self.lookback_hours = lookback_hours
        self.volume_weight = volume_weight

    def analyze(
        self,
        market: Market,
        price_history: list[dict],  # [{timestamp, price, volume}, ...]
    ) -> Optional[MomentumSignal]:
        """
        Analyze a market for momentum signals.

        Args:
            market: The market to analyze
            price_history: Historical price data

        Returns:
            MomentumSignal if momentum detected, None otherwise
        """
        if not price_history or len(price_history) < 2:
            return None

        # Get the relevant time window
        cutoff = datetime.utcnow() - timedelta(hours=self.lookback_hours)
        recent_prices = [
            p for p in price_history
            if p.get("timestamp", datetime.min) > cutoff
        ]

        if len(recent_prices) < 2:
            return None

        # Calculate price change
        start_price = recent_prices[0]["price"]
        end_price = recent_prices[-1]["price"]
        price_change = end_price - start_price

        # Is this change significant?
        if abs(price_change) < self.min_price_change:
            return None

        # Determine direction
        direction = "bullish" if price_change > 0 else "bearish"

        # Calculate momentum strength
        # We look at how consistent the move was (not just start-to-end)
        strength = self._calculate_strength(recent_prices, direction)

        # Calculate confidence based on volume and consistency
        confidence = self._calculate_confidence(recent_prices, strength)

        return MomentumSignal(
            market_id=market.id,
            direction=direction,
            strength=strength,
            price_change=price_change,
            time_period_hours=self.lookback_hours,
            confidence=confidence,
        )

    def _calculate_strength(
        self,
        prices: list[dict],
        direction: str,
    ) -> float:
        """
        Calculate how strong and consistent the momentum is.

        Strong momentum means prices moved consistently in one direction,
        not just bouncing around randomly.
        """
        if len(prices) < 2:
            return 0.0

        # Count how many price moves were in the expected direction
        correct_direction = 0
        total_moves = 0

        for i in range(1, len(prices)):
            prev = prices[i - 1]["price"]
            curr = prices[i]["price"]
            move = curr - prev

            if move != 0:
                total_moves += 1
                if (direction == "bullish" and move > 0) or \
                   (direction == "bearish" and move < 0):
                    correct_direction += 1

        if total_moves == 0:
            return 0.0

        # Strength is the percentage of moves in the right direction
        return correct_direction / total_moves

    def _calculate_confidence(
        self,
        prices: list[dict],
        strength: float,
    ) -> float:
        """
        Calculate our confidence in the momentum signal.

        Higher confidence when:
        - More data points
        - Higher volume
        - Stronger momentum
        """
        # Base confidence from data quantity
        data_confidence = min(1.0, len(prices) / 20)  # More data = more confident

        # Volume factor (if available)
        volume_factor = 1.0
        if self.volume_weight:
            volumes = [p.get("volume", 0) for p in prices]
            if volumes:
                avg_volume = sum(volumes) / len(volumes)
                # Higher volume = more confident (capped at 1.5x)
                volume_factor = min(1.5, 1.0 + avg_volume / 10000)

        # Combine factors
        confidence = data_confidence * strength * volume_factor
        return min(1.0, confidence)  # Cap at 1.0


def detect_momentum_opportunities(
    markets: list[Market],
    price_histories: dict[str, list[dict]],
    min_strength: float = 0.6,
) -> list[MomentumSignal]:
    """
    Scan multiple markets for momentum opportunities.

    This is a convenience function for scanning many markets at once.

    Args:
        markets: List of markets to scan
        price_histories: Dict mapping market_id to price history
        min_strength: Minimum momentum strength to include

    Returns:
        List of actionable momentum signals, sorted by strength
    """
    analyzer = MomentumAnalyzer()
    signals = []

    for market in markets:
        history = price_histories.get(market.id, [])
        signal = analyzer.analyze(market, history)

        if signal and signal.strength >= min_strength:
            signals.append(signal)

    # Sort by strength (strongest first)
    signals.sort(key=lambda s: s.strength, reverse=True)

    return signals
