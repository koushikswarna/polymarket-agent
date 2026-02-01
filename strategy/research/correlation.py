"""
Correlation analysis between markets.

Understanding correlations helps with:
- Portfolio diversification
- Identifying related markets
- Avoiding concentrated risk
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class CorrelationResult:
    """Result of correlation analysis between two markets."""
    market_a: str
    market_b: str
    correlation: float  # -1 to +1
    strength: str  # "strong", "moderate", "weak", "none"
    sample_size: int


class CorrelationAnalyzer:
    """
    Analyzes correlations between markets.

    Correlated markets move together. This is important because:
    - Betting on correlated markets doubles your risk
    - Finding uncorrelated markets helps diversification
    - Strong correlations might indicate arbitrage

    Example:
        analyzer = CorrelationAnalyzer()
        result = analyzer.analyze(
            prices_a=[0.4, 0.45, 0.5, 0.48],
            prices_b=[0.6, 0.62, 0.65, 0.63]
        )
        print(f"Correlation: {result.correlation}")
    """

    def analyze(
        self,
        market_a_id: str,
        market_b_id: str,
        prices_a: list[float],
        prices_b: list[float],
    ) -> CorrelationResult:
        """
        Calculate correlation between two markets.

        Args:
            market_a_id: First market ID
            market_b_id: Second market ID
            prices_a: Price series for market A
            prices_b: Price series for market B

        Returns:
            CorrelationResult with correlation coefficient
        """
        # Need same length
        min_len = min(len(prices_a), len(prices_b))
        if min_len < 3:
            return CorrelationResult(
                market_a=market_a_id,
                market_b=market_b_id,
                correlation=0,
                strength="none",
                sample_size=min_len,
            )

        prices_a = prices_a[-min_len:]
        prices_b = prices_b[-min_len:]

        # Calculate returns
        returns_a = self._calculate_returns(prices_a)
        returns_b = self._calculate_returns(prices_b)

        # Calculate correlation
        correlation = self._pearson_correlation(returns_a, returns_b)

        # Determine strength
        abs_corr = abs(correlation)
        if abs_corr >= 0.7:
            strength = "strong"
        elif abs_corr >= 0.4:
            strength = "moderate"
        elif abs_corr >= 0.2:
            strength = "weak"
        else:
            strength = "none"

        return CorrelationResult(
            market_a=market_a_id,
            market_b=market_b_id,
            correlation=correlation,
            strength=strength,
            sample_size=min_len,
        )

    def _calculate_returns(self, prices: list[float]) -> list[float]:
        """Calculate returns from prices."""
        returns = []
        for i in range(1, len(prices)):
            if prices[i-1] > 0:
                returns.append((prices[i] - prices[i-1]) / prices[i-1])
            else:
                returns.append(0)
        return returns

    def _pearson_correlation(self, x: list[float], y: list[float]) -> float:
        """Calculate Pearson correlation coefficient."""
        n = len(x)
        if n != len(y) or n < 2:
            return 0

        mean_x = sum(x) / n
        mean_y = sum(y) / n

        numerator = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))

        var_x = sum((xi - mean_x) ** 2 for xi in x)
        var_y = sum((yi - mean_y) ** 2 for yi in y)

        denominator = (var_x * var_y) ** 0.5

        if denominator == 0:
            return 0

        return numerator / denominator

    def find_correlated_markets(
        self,
        target_market_id: str,
        target_prices: list[float],
        other_markets: dict[str, list[float]],
        min_correlation: float = 0.5,
    ) -> list[CorrelationResult]:
        """
        Find markets correlated with a target market.

        Args:
            target_market_id: The market to compare against
            target_prices: Price history for target
            other_markets: Dict of market_id -> prices
            min_correlation: Minimum absolute correlation to include

        Returns:
            List of correlated markets, sorted by correlation strength
        """
        results = []

        for market_id, prices in other_markets.items():
            if market_id == target_market_id:
                continue

            result = self.analyze(target_market_id, market_id, target_prices, prices)

            if abs(result.correlation) >= min_correlation:
                results.append(result)

        # Sort by absolute correlation (strongest first)
        results.sort(key=lambda r: abs(r.correlation), reverse=True)

        return results
