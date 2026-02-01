"""
Mock objects for testing.

This module provides mock implementations of external services
(APIs, databases, etc.) for use in unit tests.
"""

from .mock_client import MockPolymarketClient
from .mock_llm import MockLLMClient

__all__ = ["MockPolymarketClient", "MockLLMClient"]
