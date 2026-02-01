"""
Trading signals module.

This module contains various signal generators that analyze markets
and produce actionable trading signals based on different methodologies.
"""

from .momentum import MomentumSignal
from .mean_reversion import MeanReversionSignal
from .sentiment import SentimentSignal

__all__ = ["MomentumSignal", "MeanReversionSignal", "SentimentSignal"]
