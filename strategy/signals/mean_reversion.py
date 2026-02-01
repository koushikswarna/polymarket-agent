"""
Mean reversion trading signals.

Mean reversion is based on the idea that prices tend to return to their
average over time. When a price moves too far from its "normal" level,
it often bounces back.

In prediction markets, this can happen when:
- Overreaction to news (price spikes then settles)
- Market manipulation (temporary price distortion)
- Low liquidity causing temporary mispricings

⚠️ CAUTION: Mean reversion can be dangerous in prediction markets!
Unlike stocks, prediction market prices can legitimately go to 0 or 1
when new information arrives. Always consider if there's a fundamental
reason for the price move before betting on reversion.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import math

from data.models import Market


@dataclass
class MeanReversionSignal:
    """
    A mean reversion trading signal.

    When we detect that a price has deviated significantly from its
    historical average, this signal suggests it might revert back.

    Attributes:
        market_id: Which market this signal is for
        current_price: Where the price is now
        mean_price: The historical average price
        deviation: How far from the mean (in standard deviations)
        expected_reversion: How much we expect the price to move back
        confidence: How confident we are in this signal
    """
    market_id: str
    current_price: float
    mean_price: float
    deviation: float  # In standard deviations
    expected_reversion: float  # Expected price movement toward mean
    confidence: float
    generated_at: datetime = None

    def __post_init__(self):
        if self.generated_at is None:
            self.generated_at = datetime.utcnow()

    @property
    def is_actionable(self) -> bool:
        """
        Is this signal strong enough to trade?

        We want:
        - Large deviation from mean (> 2 std devs)
        - Decent expected profit (> 5%)
        - Good confidence
        """
        return (
            abs(self.deviation) > 2.0 and
            abs(self.expected_reversion) > 0.05 and
            self.confidence > 0.5
        )

    @property
    def trade_direction(self) -> str:
        """
        Which way should we trade?

        If price is ABOVE mean -> expect it to go DOWN -> sell/short
        If price is BELOW mean -> expect it to go UP -> buy
        """
        if self.current_price > self.mean_price:
            return "sell"  # Or buy NO
        else:
            return "buy"  # Buy YES


class MeanReversionAnalyzer:
    """
    Detects mean reversion opportunities in prediction markets.

    The key insight: When prices move too fast or too far, they often
    overcorrect and then bounce back. But we need to be careful to
    distinguish between:

    1. Temporary overreaction (good for mean reversion)
    2. Legitimate information update (NOT good for mean reversion)

    We try to identify overreactions by looking at:
    - Speed of price movement
    - Whether volume supports the move
    - How extreme the deviation is

    Example usage:
        analyzer = MeanReversionAnalyzer()
        signal = analyzer.analyze(market, price_history)
        if signal and signal.is_actionable:
            # Consider trading against the recent move
    """

    def __init__(
        self,
        lookback_hours: int = 72,  # 3 days of history
        min_deviation: float = 1.5,  # Minimum std devs to signal
        spike_threshold: float = 0.10,  # 10% move considered a spike
    ):
        """
        Initialize the mean reversion analyzer.

        Args:
            lookback_hours: How much history to use for calculating mean
            min_deviation: Minimum standard deviations for a signal
            spike_threshold: What % move is considered a spike
        """
        self.lookback_hours = lookback_hours
        self.min_deviation = min_deviation
        self.spike_threshold = spike_threshold

    def analyze(
        self,
        market: Market,
        price_history: list[dict],
    ) -> Optional[MeanReversionSignal]:
        """
        Analyze a market for mean reversion opportunities.

        Args:
            market: The market to analyze
            price_history: List of {timestamp, price, volume} dicts

        Returns:
            MeanReversionSignal if opportunity found, None otherwise
        """
        if not price_history or len(price_history) < 10:
            # Need enough data for meaningful statistics
            return None

        # Calculate mean and standard deviation
        prices = [p["price"] for p in price_history]
        mean_price = sum(prices) / len(prices)
        std_dev = self._calculate_std_dev(prices, mean_price)

        if std_dev == 0:
            return None  # No variation = no opportunity

        # Get current price
        current_price = prices[-1]

        # Calculate deviation from mean in standard deviations
        deviation = (current_price - mean_price) / std_dev

        # Is this deviation significant?
        if abs(deviation) < self.min_deviation:
            return None

        # Check if this looks like an overreaction (spike)
        is_spike = self._detect_spike(price_history)

        # Calculate expected reversion
        # We don't expect full reversion, maybe 50-70% of the way back
        reversion_factor = 0.5 if is_spike else 0.3
        expected_reversion = (mean_price - current_price) * reversion_factor

        # Calculate confidence
        confidence = self._calculate_confidence(
            deviation=deviation,
            is_spike=is_spike,
            data_points=len(prices),
        )

        return MeanReversionSignal(
            market_id=market.id,
            current_price=current_price,
            mean_price=mean_price,
            deviation=deviation,
            expected_reversion=expected_reversion,
            confidence=confidence,
        )

    def _calculate_std_dev(self, values: list[float], mean: float) -> float:
        """Calculate standard deviation."""
        if len(values) < 2:
            return 0.0

        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return math.sqrt(variance)

    def _detect_spike(self, price_history: list[dict]) -> bool:
        """
        Detect if there was a sudden price spike.

        Spikes are more likely to revert than gradual moves.
        """
        if len(price_history) < 5:
            return False

        # Look at the last few price changes
        recent = price_history[-5:]
        prices = [p["price"] for p in recent]

        # Calculate max single-period change
        max_change = 0
        for i in range(1, len(prices)):
            change = abs(prices[i] - prices[i-1])
            max_change = max(max_change, change)

        return max_change > self.spike_threshold

    def _calculate_confidence(
        self,
        deviation: float,
        is_spike: bool,
        data_points: int,
    ) -> float:
        """
        Calculate confidence in the mean reversion signal.

        Higher confidence when:
        - More data points (better estimate of mean)
        - It looks like a spike (more likely to revert)
        - Deviation is extreme (stronger pull back to mean)
        """
        # Base confidence from data quantity
        data_factor = min(1.0, data_points / 50)

        # Spike factor (spikes are more likely to revert)
        spike_factor = 1.3 if is_spike else 0.8

        # Deviation factor (but cap it - very extreme might be real)
        if abs(deviation) < 3:
            deviation_factor = abs(deviation) / 3
        else:
            # Too extreme might be real news, lower confidence
            deviation_factor = 0.8

        confidence = data_factor * spike_factor * deviation_factor
        return min(0.9, confidence)  # Cap confidence at 90%


def find_reversion_opportunities(
    markets: list[Market],
    price_histories: dict[str, list[dict]],
) -> list[MeanReversionSignal]:
    """
    Scan markets for mean reversion opportunities.

    Returns signals sorted by expected profit potential.
    """
    analyzer = MeanReversionAnalyzer()
    signals = []

    for market in markets:
        history = price_histories.get(market.id, [])
        signal = analyzer.analyze(market, history)

        if signal and signal.is_actionable:
            signals.append(signal)

    # Sort by expected reversion (biggest profit potential first)
    signals.sort(key=lambda s: abs(s.expected_reversion), reverse=True)

    return signals
