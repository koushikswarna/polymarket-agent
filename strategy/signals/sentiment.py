"""
Sentiment-based trading signals.

This module analyzes news and social media sentiment to generate
trading signals. The idea is simple: positive news about an event
increases the probability of YES, and vice versa.

How it works:
1. Fetch recent news for a market's topic
2. Analyze the sentiment (positive/negative/neutral)
3. Compare sentiment to current market price
4. If there's a mismatch, we might have an opportunity

Example: If news is overwhelmingly positive about a candidate winning,
but the market price is still low, the market might be slow to react.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from data.models import Market
from strategy.news_analyzer import NewsAnalyzer


@dataclass
class SentimentSignal:
    """
    A sentiment-based trading signal.

    This signal is generated when news sentiment doesn't match
    the current market price, suggesting a potential opportunity.

    Attributes:
        market_id: Which market this signal is for
        sentiment_score: -1.0 (very negative) to +1.0 (very positive)
        current_price: Current YES price in the market
        sentiment_price_gap: Difference between implied sentiment and price
        news_count: How many news articles we analyzed
        confidence: Our confidence in this signal
        key_headlines: Most important headlines driving the sentiment
    """
    market_id: str
    sentiment_score: float  # -1.0 to +1.0
    current_price: float
    sentiment_price_gap: float
    news_count: int
    confidence: float
    key_headlines: list[str]
    generated_at: datetime = None

    def __post_init__(self):
        if self.generated_at is None:
            self.generated_at = datetime.utcnow()

    @property
    def implied_probability(self) -> float:
        """
        Convert sentiment score to an implied probability.

        Sentiment of +1.0 -> ~90% probability
        Sentiment of 0.0 -> ~50% probability
        Sentiment of -1.0 -> ~10% probability
        """
        # Map [-1, 1] to [0.1, 0.9]
        return 0.5 + (self.sentiment_score * 0.4)

    @property
    def is_actionable(self) -> bool:
        """
        Is this signal strong enough to trade?

        We need:
        - Significant gap between sentiment and price
        - Enough news articles to be confident
        - Good overall confidence
        """
        return (
            abs(self.sentiment_price_gap) > 0.10 and
            self.news_count >= 3 and
            self.confidence > 0.5
        )

    @property
    def trade_direction(self) -> str:
        """Which way should we trade based on sentiment?"""
        if self.sentiment_score > 0 and self.current_price < self.implied_probability:
            return "buy_yes"  # Positive news, price too low
        elif self.sentiment_score < 0 and self.current_price > self.implied_probability:
            return "buy_no"  # Negative news, price too high
        return "hold"


class SentimentAnalyzer:
    """
    Analyzes news sentiment to find trading opportunities.

    This analyzer fetches recent news about a market's topic and
    determines if the sentiment matches the current market price.

    The key insight: Markets don't always react immediately to news.
    By analyzing sentiment, we can sometimes get ahead of price moves.

    ⚠️ IMPORTANT CAVEATS:
    - News can be misleading or outdated
    - Sentiment analysis isn't perfect
    - Markets might have already priced in the news
    - Use this as ONE input, not the only signal

    Example usage:
        analyzer = SentimentAnalyzer()
        signal = analyzer.analyze(market)
        if signal and signal.is_actionable:
            print(f"Sentiment suggests {signal.trade_direction}")
    """

    def __init__(self, news_analyzer: Optional[NewsAnalyzer] = None):
        """
        Initialize the sentiment analyzer.

        Args:
            news_analyzer: NewsAnalyzer instance (creates one if not provided)
        """
        self.news = news_analyzer or NewsAnalyzer()

        # Words that indicate positive sentiment
        self.positive_words = {
            "win", "winning", "lead", "leading", "ahead", "surge",
            "rise", "rising", "gain", "gains", "success", "successful",
            "strong", "strengthen", "boost", "positive", "optimistic",
            "breakthrough", "victory", "triumph", "soar", "rally",
            "improve", "improving", "progress", "advance", "momentum",
        }

        # Words that indicate negative sentiment
        self.negative_words = {
            "lose", "losing", "behind", "trail", "trailing", "fall",
            "falling", "drop", "decline", "fail", "failure", "weak",
            "weaken", "negative", "pessimistic", "defeat", "loss",
            "struggle", "struggling", "crash", "plunge", "crisis",
            "concern", "worried", "fear", "risk", "threat", "problem",
        }

    def analyze(self, market: Market) -> Optional[SentimentSignal]:
        """
        Analyze sentiment for a market.

        Args:
            market: The market to analyze

        Returns:
            SentimentSignal if we can generate one, None otherwise
        """
        # Fetch news for this market
        news_items = self.news.get_news_for_market(
            question=market.question,
            max_results=10,
        )

        if not news_items:
            return None

        # Analyze sentiment of each article
        sentiment_scores = []
        key_headlines = []

        for item in news_items:
            score = self._analyze_text_sentiment(
                item.get("title", "") + " " + item.get("summary", "")
            )
            sentiment_scores.append(score)

            # Keep track of strong headlines
            if abs(score) > 0.3:
                key_headlines.append(item.get("title", ""))

        if not sentiment_scores:
            return None

        # Calculate overall sentiment
        avg_sentiment = sum(sentiment_scores) / len(sentiment_scores)

        # Get current price
        current_price = market.yes_price or 0.5

        # Calculate gap between sentiment and price
        implied_prob = 0.5 + (avg_sentiment * 0.4)
        gap = implied_prob - current_price

        # Calculate confidence
        confidence = self._calculate_confidence(
            sentiment_scores=sentiment_scores,
            news_count=len(news_items),
        )

        return SentimentSignal(
            market_id=market.id,
            sentiment_score=avg_sentiment,
            current_price=current_price,
            sentiment_price_gap=gap,
            news_count=len(news_items),
            confidence=confidence,
            key_headlines=key_headlines[:3],  # Top 3 headlines
        )

    def _analyze_text_sentiment(self, text: str) -> float:
        """
        Simple keyword-based sentiment analysis.

        Returns a score from -1.0 (very negative) to +1.0 (very positive).

        This is a basic approach. In production, you might want to use
        a proper NLP model for better accuracy.
        """
        text_lower = text.lower()
        words = text_lower.split()

        positive_count = sum(1 for word in words if word in self.positive_words)
        negative_count = sum(1 for word in words if word in self.negative_words)

        total = positive_count + negative_count
        if total == 0:
            return 0.0

        # Score from -1 to +1
        score = (positive_count - negative_count) / total
        return max(-1.0, min(1.0, score))

    def _calculate_confidence(
        self,
        sentiment_scores: list[float],
        news_count: int,
    ) -> float:
        """
        Calculate confidence in the sentiment signal.

        Higher confidence when:
        - More news articles (more data)
        - Consistent sentiment across articles
        - Strong sentiment (not wishy-washy)
        """
        if not sentiment_scores:
            return 0.0

        # Data quantity factor
        data_factor = min(1.0, news_count / 10)

        # Consistency factor (are all articles agreeing?)
        avg = sum(sentiment_scores) / len(sentiment_scores)
        variance = sum((s - avg) ** 2 for s in sentiment_scores) / len(sentiment_scores)
        consistency_factor = max(0.3, 1.0 - variance)

        # Strength factor (is sentiment strong?)
        strength_factor = min(1.0, abs(avg) * 2)

        confidence = data_factor * consistency_factor * strength_factor
        return min(0.85, confidence)  # Cap at 85%


def scan_for_sentiment_opportunities(
    markets: list[Market],
    min_gap: float = 0.10,
) -> list[SentimentSignal]:
    """
    Scan multiple markets for sentiment-based opportunities.

    This function is useful for batch processing many markets
    to find where news sentiment doesn't match market prices.

    Args:
        markets: List of markets to analyze
        min_gap: Minimum sentiment-price gap to include

    Returns:
        List of actionable signals, sorted by gap size
    """
    analyzer = SentimentAnalyzer()
    signals = []

    for market in markets:
        try:
            signal = analyzer.analyze(market)
            if signal and abs(signal.sentiment_price_gap) >= min_gap:
                signals.append(signal)
        except Exception:
            # Skip markets that fail analysis
            continue

    # Sort by gap size (biggest opportunities first)
    signals.sort(key=lambda s: abs(s.sentiment_price_gap), reverse=True)

    return signals
