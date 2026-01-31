"""
THE BRAIN: Two-tier LLM probability estimation engine.

Uses GPT-4o-mini for screening and Claude for final decisions.
Implements Tetlock's superforecasting methodology.
"""

import json
import re
from datetime import datetime
from typing import Optional
from pathlib import Path

from anthropic import Anthropic
from openai import OpenAI

from config import settings
from data.models import Market, ProbabilityEstimate, LLMBudget
from data.db import Database
from utils.logger import get_logger
from utils.helpers import retry_with_backoff

from .news_analyzer import NewsAnalyzer

logger = get_logger("polymarket.probability")


# Superforecaster prompt based on Tetlock's research
SUPERFORECASTER_SYSTEM_PROMPT = """You are a superforecaster trained in Philip Tetlock's methodology. Your task is to estimate the probability of events with exceptional accuracy.

Key principles you follow:
1. OUTSIDE VIEW FIRST: Start with base rates before considering specifics
2. MULTIPLE PERSPECTIVES: Consider the question from different angles
3. DECOMPOSITION: Break complex questions into simpler components
4. UPDATE INCREMENTALLY: Adjust from base rates based on specific evidence
5. QUANTIFY UNCERTAINTY: Express confidence precisely, avoid round numbers
6. AVOID BIASES: Watch for overconfidence, anchoring, and availability bias
7. CONSIDER CONTRARIAN VIEWS: What would someone who disagrees say?

When estimating probabilities:
- Use specific numbers (e.g., 0.67 not "about 70%")
- Consider time horizon carefully
- Account for unknown unknowns
- Be willing to say "I don't know" when evidence is weak

You must respond in valid JSON format."""


SCREENING_PROMPT_TEMPLATE = """Analyze this prediction market and provide a quick probability estimate.

MARKET QUESTION: {question}

MARKET DESCRIPTION: {description}

CURRENT MARKET PRICE (YES): {market_price:.1%}

TIME UNTIL RESOLUTION: {time_to_resolution}

{news_context}

Respond with JSON in this exact format:
{{
    "probability": <float between 0 and 1>,
    "confidence": <float between 0 and 1, your confidence in this estimate>,
    "reasoning": "<brief 1-2 sentence reasoning>",
    "worth_deeper_analysis": <true/false, is there likely edge here?>
}}

Focus on quick pattern matching and obvious mispricings. If the market seems fairly priced, set worth_deeper_analysis to false."""


FINAL_ANALYSIS_PROMPT_TEMPLATE = """Perform a deep superforecaster analysis of this prediction market.

MARKET QUESTION: {question}

MARKET DESCRIPTION: {description}

CURRENT MARKET PRICE (YES): {market_price:.1%}

TIME UNTIL RESOLUTION: {time_to_resolution}

CATEGORY: {category}

{news_context}

SCREENING ANALYSIS: {screening_summary}

Follow this analytical framework:

1. BASE RATE ANALYSIS
   - What is the historical base rate for similar events?
   - What reference class does this belong to?

2. SPECIFIC EVIDENCE
   - What factors push probability UP from base rate?
   - What factors push probability DOWN from base rate?

3. CONTRARIAN CONSIDERATIONS
   - Why might the market be wrong?
   - What would the other side argue?

4. SYNTHESIS
   - Combine all factors into final probability
   - Use specific numbers, not round ones

Respond with JSON in this exact format:
{{
    "probability": <float between 0 and 1, e.g., 0.73>,
    "confidence": <float between 0 and 1>,
    "base_rate": <float, the base rate you started from>,
    "base_rate_reasoning": "<why this base rate?>",
    "upside_factors": ["<factor 1>", "<factor 2>"],
    "downside_factors": ["<factor 1>", "<factor 2>"],
    "contrarian_view": "<strongest argument against your estimate>",
    "reasoning": "<2-3 sentence synthesis of your analysis>",
    "trade_recommendation": "<BUY_YES/BUY_NO/NO_TRADE>",
    "edge_assessment": "<estimated edge size: NONE/SMALL/MEDIUM/LARGE>"
}}"""


class ProbabilityEngine:
    """
    Two-tier LLM system for probability estimation.

    Tier 1 (GPT-4o-mini): Fast, cheap screening of all candidates
    Tier 2 (Claude): Deep analysis of promising markets
    """

    def __init__(self, db: Database):
        self.db = db
        self.news = NewsAnalyzer()

        # Initialize clients
        self.anthropic = None
        self.openai = None

        if settings.llm.anthropic_api_key:
            self.anthropic = Anthropic(api_key=settings.llm.anthropic_api_key)

        if settings.llm.openai_api_key:
            self.openai = OpenAI(api_key=settings.llm.openai_api_key)

        # Load budget state
        self.budget = self.db.get_llm_budget()

    def _check_budget(self, provider: str) -> bool:
        """Check if we have budget for this provider."""
        self.budget = self.db.get_llm_budget()

        if provider == "anthropic":
            return not self.budget.anthropic_exhausted
        elif provider == "openai":
            return not self.budget.openai_exhausted
        return False

    def _record_usage(self, provider: str, cost: float):
        """Record LLM API usage."""
        self.db.record_llm_call(provider, cost)
        self.budget = self.db.get_llm_budget()

        # Log budget warning if low
        if provider == "anthropic" and self.budget.anthropic_remaining < 1.0:
            logger.warning(
                f"Anthropic budget low: ${self.budget.anthropic_remaining:.2f} remaining"
            )
        elif provider == "openai" and self.budget.openai_remaining < 1.0:
            logger.warning(
                f"OpenAI budget low: ${self.budget.openai_remaining:.2f} remaining"
            )

    def _format_time_to_resolution(self, market: Market) -> str:
        """Format time to resolution for prompt."""
        hours = market.hours_to_resolution
        if hours is None:
            return "Unknown"

        if hours < 24:
            return f"{hours:.1f} hours"
        elif hours < 24 * 7:
            return f"{hours / 24:.1f} days"
        else:
            return f"{hours / 24 / 7:.1f} weeks"

    def _parse_json_response(self, text: str) -> dict:
        """Parse JSON from LLM response, handling common issues."""
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code block
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find JSON object in text
        json_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        logger.error(f"Failed to parse JSON from response: {text[:200]}")
        return {}

    @retry_with_backoff(max_retries=2, base_delay=1.0)
    def screen_market(self, market: Market) -> Optional[dict]:
        """
        Tier 1: Quick screening with GPT-4o-mini.

        Returns screening result dict or None if budget exhausted.
        """
        if not self._check_budget("openai"):
            logger.warning("OpenAI budget exhausted - skipping screening")
            return None

        if not self.openai:
            logger.error("OpenAI client not initialized")
            return None

        # Get news context
        news_items = self.news.get_news_for_market(market.question, max_results=3)
        news_context = self.news.format_news_context(news_items)

        # Format prompt
        prompt = SCREENING_PROMPT_TEMPLATE.format(
            question=market.question,
            description=market.description[:500] if market.description else "N/A",
            market_price=market.yes_price or 0.5,
            time_to_resolution=self._format_time_to_resolution(market),
            news_context=news_context,
        )

        try:
            response = self.openai.chat.completions.create(
                model=settings.llm.gpt_model,
                messages=[
                    {"role": "system", "content": SUPERFORECASTER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=500,
            )

            # Record usage
            self._record_usage("openai", settings.llm.gpt_cost_per_call)

            # Parse response
            result = self._parse_json_response(response.choices[0].message.content)

            if result:
                result["model"] = "gpt-4o-mini"
                result["news_summary"] = news_context[:500]
                logger.info(
                    f"Screened '{market.question[:50]}...' -> "
                    f"P={result.get('probability', 'N/A')}, "
                    f"Deeper={result.get('worth_deeper_analysis', False)}"
                )

            return result

        except Exception as e:
            logger.error(f"GPT screening failed: {e}")
            return None

    @retry_with_backoff(max_retries=2, base_delay=2.0)
    def deep_analyze(
        self,
        market: Market,
        screening_result: Optional[dict] = None,
    ) -> Optional[ProbabilityEstimate]:
        """
        Tier 2: Deep analysis with Claude.

        Returns ProbabilityEstimate or None if budget exhausted.
        """
        if not self._check_budget("anthropic"):
            logger.warning("Anthropic budget exhausted - skipping deep analysis")
            return None

        if not self.anthropic:
            logger.error("Anthropic client not initialized")
            return None

        # Get news context (more detailed for deep analysis)
        news_items = self.news.get_news_for_market(market.question, max_results=5)
        news_context = self.news.format_news_context(news_items)

        # Format screening summary
        screening_summary = "No prior screening."
        if screening_result:
            screening_summary = (
                f"Initial estimate: {screening_result.get('probability', 'N/A')}, "
                f"Confidence: {screening_result.get('confidence', 'N/A')}, "
                f"Reasoning: {screening_result.get('reasoning', 'N/A')}"
            )

        # Format prompt
        prompt = FINAL_ANALYSIS_PROMPT_TEMPLATE.format(
            question=market.question,
            description=market.description[:1000] if market.description else "N/A",
            market_price=market.yes_price or 0.5,
            time_to_resolution=self._format_time_to_resolution(market),
            category=market.category or "General",
            news_context=news_context,
            screening_summary=screening_summary,
        )

        try:
            response = self.anthropic.messages.create(
                model=settings.llm.claude_model,
                max_tokens=1000,
                system=SUPERFORECASTER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            # Record usage
            self._record_usage("anthropic", settings.llm.claude_cost_per_call)

            # Parse response
            result = self._parse_json_response(response.content[0].text)

            if not result or "probability" not in result:
                logger.error("Failed to parse Claude response")
                return None

            # Calculate edge
            market_price = market.yes_price or 0.5
            probability = float(result["probability"])
            edge = probability - market_price

            estimate = ProbabilityEstimate(
                market_id=market.id,
                probability=probability,
                confidence=float(result.get("confidence", 0.5)),
                model="claude",
                reasoning=result.get("reasoning", ""),
                market_price=market_price,
                edge=edge,
                news_summary=news_context[:500],
            )

            # Save to database
            self.db.save_probability_estimate(
                market_id=estimate.market_id,
                probability=estimate.probability,
                confidence=estimate.confidence,
                model=estimate.model,
                reasoning=estimate.reasoning,
                market_price=estimate.market_price,
                edge=estimate.edge,
                news_summary=estimate.news_summary,
            )

            logger.info(
                f"Deep analysis '{market.question[:50]}...' -> "
                f"P={estimate.probability:.2f} vs Market={market_price:.2f}, "
                f"Edge={edge:+.2f}"
            )

            return estimate

        except Exception as e:
            logger.error(f"Claude analysis failed: {e}")
            return None

    def analyze_market(
        self,
        market: Market,
        skip_screening: bool = False,
    ) -> Optional[ProbabilityEstimate]:
        """
        Full two-tier analysis of a market.

        1. Screen with GPT-4o-mini
        2. If promising, deep analyze with Claude

        Args:
            market: Market to analyze
            skip_screening: Go straight to Claude (use sparingly)

        Returns:
            ProbabilityEstimate if successful
        """
        screening_result = None

        # Tier 1: Screening
        if not skip_screening:
            screening_result = self.screen_market(market)

            if screening_result is None:
                # Budget exhausted or error
                return None

            # Check if worth deeper analysis
            if not screening_result.get("worth_deeper_analysis", False):
                # Return screening result as estimate
                probability = float(screening_result.get("probability", 0.5))
                market_price = market.yes_price or 0.5

                estimate = ProbabilityEstimate(
                    market_id=market.id,
                    probability=probability,
                    confidence=float(screening_result.get("confidence", 0.3)),
                    model="gpt-4o-mini",
                    reasoning=screening_result.get("reasoning", ""),
                    market_price=market_price,
                    edge=probability - market_price,
                    news_summary=screening_result.get("news_summary", ""),
                )

                logger.info(
                    f"Screening complete (no deep analysis needed) for "
                    f"'{market.question[:40]}...'"
                )
                return estimate

        # Tier 2: Deep analysis
        return self.deep_analyze(market, screening_result)

    def batch_screen(
        self,
        markets: list[Market],
        max_screens: int = 20,
    ) -> list[tuple[Market, dict]]:
        """
        Screen multiple markets and return promising ones.

        Returns list of (market, screening_result) tuples worth deeper analysis.
        """
        promising = []

        for market in markets[:max_screens]:
            if not self._check_budget("openai"):
                logger.warning("Budget exhausted during batch screening")
                break

            result = self.screen_market(market)

            if result and result.get("worth_deeper_analysis", False):
                promising.append((market, result))

        logger.info(
            f"Batch screened {min(len(markets), max_screens)} markets, "
            f"{len(promising)} worth deeper analysis"
        )
        return promising

    def get_budget_status(self) -> dict:
        """Get current LLM budget status."""
        self.budget = self.db.get_llm_budget()
        return {
            "anthropic": {
                "spent": self.budget.anthropic_spent,
                "remaining": self.budget.anthropic_remaining,
                "calls": self.budget.anthropic_calls,
                "exhausted": self.budget.anthropic_exhausted,
            },
            "openai": {
                "spent": self.budget.openai_spent,
                "remaining": self.budget.openai_remaining,
                "calls": self.budget.openai_calls,
                "exhausted": self.budget.openai_exhausted,
            },
            "total_remaining": self.budget.total_remaining,
            "all_exhausted": self.budget.all_exhausted,
        }
