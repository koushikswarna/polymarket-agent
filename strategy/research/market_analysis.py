"""
Market analysis tools for research.

Use these tools to understand market dynamics before trading.
"""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class MarketProfile:
    """
    Profile of a market's characteristics.

    This helps understand what kind of market you're dealing with.
    """
    market_id: str
    question: str

    # Liquidity characteristics
    avg_liquidity: float
    liquidity_stability: float  # How stable is liquidity over time

    # Price characteristics
    avg_spread: float
    price_volatility: float
    price_trend: str  # "up", "down", "sideways"

    # Activity
    avg_daily_volume: float
    active_hours: list[int]  # Hours of day with most activity

    # Market type
    is_binary: bool
    time_to_resolution_days: float
    category: str


class MarketAnalyzer:
    """
    Analyzes markets to create profiles.

    Use market profiles to:
    - Identify good trading opportunities
    - Adjust strategy parameters per market
    - Avoid problematic markets

    Example:
        analyzer = MarketAnalyzer()
        profile = analyzer.analyze(market, price_history)

        if profile.liquidity_stability < 0.5:
            print("Warning: Unstable liquidity")
    """

    def analyze(
        self,
        market,
        price_history: list[dict],
    ) -> MarketProfile:
        """
        Create a profile for a market.

        Args:
            market: Market object
            price_history: Historical price/volume data

        Returns:
            MarketProfile with analysis results
        """
        # Calculate liquidity stats
        if price_history:
            volumes = [p.get("volume", 0) for p in price_history]
            avg_liquidity = sum(volumes) / len(volumes) if volumes else 0

            # Stability = 1 - coefficient of variation
            if avg_liquidity > 0:
                import math
                variance = sum((v - avg_liquidity) ** 2 for v in volumes) / len(volumes)
                std_dev = math.sqrt(variance)
                liquidity_stability = max(0, 1 - std_dev / avg_liquidity)
            else:
                liquidity_stability = 0
        else:
            avg_liquidity = market.liquidity if hasattr(market, 'liquidity') else 0
            liquidity_stability = 0.5  # Unknown

        # Calculate price stats
        if price_history:
            prices = [p["price"] for p in price_history]

            # Volatility
            price_volatility = self._calculate_volatility(prices)

            # Trend
            if len(prices) >= 2:
                start = sum(prices[:len(prices)//4]) / (len(prices)//4) if len(prices) >= 4 else prices[0]
                end = sum(prices[-len(prices)//4:]) / (len(prices)//4) if len(prices) >= 4 else prices[-1]
                if end > start * 1.05:
                    price_trend = "up"
                elif end < start * 0.95:
                    price_trend = "down"
                else:
                    price_trend = "sideways"
            else:
                price_trend = "unknown"
        else:
            price_volatility = 0
            price_trend = "unknown"

        return MarketProfile(
            market_id=market.id,
            question=market.question,
            avg_liquidity=avg_liquidity,
            liquidity_stability=liquidity_stability,
            avg_spread=0.02,  # Would need order book data
            price_volatility=price_volatility,
            price_trend=price_trend,
            avg_daily_volume=avg_liquidity,
            active_hours=[9, 10, 11, 14, 15, 16],  # Default US market hours
            is_binary=len(market.tokens) == 2,
            time_to_resolution_days=market.days_to_resolution or 0,
            category=market.category,
        )

    def _calculate_volatility(self, prices: list[float]) -> float:
        """Calculate price volatility."""
        if len(prices) < 2:
            return 0

        returns = []
        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                returns.append((prices[i] - prices[i-1]) / prices[i-1])

        if not returns:
            return 0

        import math
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        return math.sqrt(variance)
