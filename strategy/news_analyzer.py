"""
News analyzer for fetching relevant information via RSS feeds.
"""

import re
import time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote_plus

import feedparser

from config import settings
from utils.logger import get_logger
from utils.helpers import memoize_with_ttl

logger = get_logger("polymarket.news")


class NewsAnalyzer:
    """
    Fetches and analyzes news relevant to prediction markets.
    Uses Google News RSS for free, unauthenticated news access.
    """

    def __init__(self, cache_minutes: int = 15):
        self.cache_minutes = cache_minutes
        self._cache: dict[str, tuple[float, list[dict]]] = {}

    def _get_cached(self, key: str) -> Optional[list[dict]]:
        """Get cached results if not expired."""
        if key in self._cache:
            timestamp, results = self._cache[key]
            if time.time() - timestamp < self.cache_minutes * 60:
                return results
        return None

    def _set_cache(self, key: str, results: list[dict]):
        """Cache results."""
        self._cache[key] = (time.time(), results)

    def search_google_news(
        self,
        query: str,
        max_results: int = 5,
    ) -> list[dict]:
        """
        Search Google News RSS feed.

        Args:
            query: Search query
            max_results: Maximum number of results

        Returns:
            List of news items with title, link, published, source
        """
        cache_key = f"google:{query}"
        cached = self._get_cached(cache_key)
        if cached:
            logger.debug(f"Using cached news for '{query}'")
            return cached[:max_results]

        try:
            # Google News RSS endpoint
            encoded_query = quote_plus(query)
            url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"

            feed = feedparser.parse(url)

            results = []
            for entry in feed.entries[:max_results]:
                # Extract source from title (Google News format: "Title - Source")
                title = entry.get("title", "")
                source = ""
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    if len(parts) == 2:
                        title, source = parts

                # Parse published date
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime(*entry.published_parsed[:6])

                results.append({
                    "title": title.strip(),
                    "link": entry.get("link", ""),
                    "source": source.strip(),
                    "published": published,
                    "summary": self._clean_html(entry.get("summary", "")),
                })

            self._set_cache(cache_key, results)
            logger.info(f"Fetched {len(results)} news items for '{query}'")
            return results

        except Exception as e:
            logger.error(f"Failed to fetch news for '{query}': {e}")
            return []

    def _clean_html(self, text: str) -> str:
        """Remove HTML tags from text."""
        clean = re.sub(r"<[^>]+>", "", text)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()

    def get_news_for_market(
        self,
        question: str,
        max_results: int = 5,
    ) -> list[dict]:
        """
        Get relevant news for a market question.

        Extracts key terms from the question and searches for news.
        """
        # Extract key terms from question
        keywords = self._extract_keywords(question)

        if not keywords:
            return []

        # Search with extracted keywords
        search_query = " ".join(keywords[:5])  # Limit to top 5 keywords
        return self.search_google_news(search_query, max_results)

    def _extract_keywords(self, question: str) -> list[str]:
        """
        Extract important keywords from a market question.
        """
        # Remove common question words and stopwords
        stopwords = {
            "will", "the", "be", "to", "in", "on", "at", "by", "for", "of",
            "and", "or", "a", "an", "is", "are", "was", "were", "been", "being",
            "have", "has", "had", "do", "does", "did", "what", "who", "where",
            "when", "why", "how", "which", "that", "this", "these", "those",
            "it", "its", "than", "then", "their", "there", "they", "them",
            "before", "after", "during", "yes", "no", "if", "any", "all",
        }

        # Also remove Polymarket-specific patterns
        question = re.sub(r"\d{4}", "", question)  # Remove years sometimes
        question = re.sub(r"[?!.,;:]", "", question)  # Remove punctuation

        words = question.lower().split()
        keywords = [
            w for w in words
            if w not in stopwords and len(w) > 2
        ]

        return keywords

    def format_news_context(self, news_items: list[dict]) -> str:
        """
        Format news items into a context string for LLM analysis.
        """
        if not news_items:
            return "No recent news found."

        lines = ["Recent relevant news:"]

        for i, item in enumerate(news_items, 1):
            date_str = ""
            if item.get("published"):
                date_str = item["published"].strftime("%Y-%m-%d")

            lines.append(
                f"{i}. [{date_str}] {item['title']}"
                + (f" (Source: {item['source']})" if item.get("source") else "")
            )

            if item.get("summary"):
                # Truncate long summaries
                summary = item["summary"][:200]
                if len(item["summary"]) > 200:
                    summary += "..."
                lines.append(f"   Summary: {summary}")

        return "\n".join(lines)

    def get_topic_sentiment(self, query: str) -> dict:
        """
        Get a rough sentiment analysis of news on a topic.

        Returns dict with positive/negative/neutral counts and keywords.
        """
        news_items = self.search_google_news(query, max_results=10)

        if not news_items:
            return {
                "total": 0,
                "sentiment": "unknown",
                "positive_keywords": [],
                "negative_keywords": [],
            }

        # Simple keyword-based sentiment
        positive_words = {
            "surge", "gain", "rise", "win", "success", "positive", "growth",
            "improve", "boost", "advance", "rally", "strong", "support",
            "lead", "ahead", "victory", "breakthrough", "optimis",
        }
        negative_words = {
            "fall", "drop", "decline", "lose", "loss", "fail", "negative",
            "crisis", "crash", "plunge", "weak", "concern", "worry", "fear",
            "behind", "defeat", "struggle", "pessimis", "risk", "threat",
        }

        positive_count = 0
        negative_count = 0
        found_positive = []
        found_negative = []

        for item in news_items:
            text = (item.get("title", "") + " " + item.get("summary", "")).lower()

            for word in positive_words:
                if word in text:
                    positive_count += 1
                    found_positive.append(word)
                    break

            for word in negative_words:
                if word in text:
                    negative_count += 1
                    found_negative.append(word)
                    break

        total = len(news_items)
        if positive_count > negative_count + 2:
            sentiment = "positive"
        elif negative_count > positive_count + 2:
            sentiment = "negative"
        else:
            sentiment = "mixed"

        return {
            "total": total,
            "positive_count": positive_count,
            "negative_count": negative_count,
            "sentiment": sentiment,
            "positive_keywords": list(set(found_positive)),
            "negative_keywords": list(set(found_negative)),
        }

    def clear_cache(self):
        """Clear the news cache."""
        self._cache.clear()
        logger.info("News cache cleared")
