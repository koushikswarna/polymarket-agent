"""
Configuration management for Polymarket Trading Agent.
Loads settings from environment variables with sensible defaults.
"""

import os
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load .env file if it exists
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    # Try parent directory
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)


class PolymarketSettings(BaseSettings):
    """Polymarket API configuration."""
    api_key: str = Field(default="", alias="POLYMARKET_API_KEY")
    api_secret: str = Field(default="", alias="POLYMARKET_API_SECRET")
    api_passphrase: str = Field(default="", alias="POLYMARKET_API_PASSPHRASE")
    private_key: str = Field(default="", alias="PRIVATE_KEY")

    # API endpoints
    gamma_url: str = "https://gamma-api.polymarket.com"
    clob_url: str = "https://clob.polymarket.com"

    # Rate limits
    public_rate_limit: int = 100  # requests per minute
    trading_rate_limit: int = 60  # orders per minute


class LLMSettings(BaseSettings):
    """LLM API configuration."""
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    # Model selection
    claude_model: str = "claude-sonnet-4-20250514"
    gpt_model: str = "gpt-4o-mini"

    # Budget limits (USD)
    anthropic_budget: float = Field(default=4.50, alias="ANTHROPIC_BUDGET")
    openai_budget: float = Field(default=5.00, alias="OPENAI_BUDGET")

    # Cost per call estimates (approximate)
    claude_cost_per_call: float = 0.005
    gpt_cost_per_call: float = 0.001


class TradingSettings(BaseSettings):
    """Trading configuration."""
    dry_run: bool = Field(default=True, alias="DRY_RUN")
    starting_capital: float = Field(default=10.0, alias="STARTING_CAPITAL")
    max_position_size: float = Field(default=3.0, alias="MAX_POSITION_SIZE")
    max_total_exposure: float = Field(default=8.0, alias="MAX_TOTAL_EXPOSURE")
    daily_loss_limit: float = Field(default=3.0, alias="DAILY_LOSS_LIMIT")


class RiskSettings(BaseSettings):
    """Risk management configuration."""
    min_edge_threshold: float = Field(default=0.05, alias="MIN_EDGE_THRESHOLD")
    min_liquidity: float = Field(default=500.0, alias="MIN_LIQUIDITY")
    max_open_positions: int = Field(default=8, alias="MAX_OPEN_POSITIONS")
    consecutive_loss_cooldown: int = Field(default=5, alias="CONSECUTIVE_LOSS_COOLDOWN")
    cooldown_hours: float = 1.0


class MarketFilterSettings(BaseSettings):
    """Market filtering configuration."""
    min_hours_to_resolution: int = Field(default=6, alias="MIN_HOURS_TO_RESOLUTION")
    max_days_to_resolution: int = Field(default=60, alias="MAX_DAYS_TO_RESOLUTION")
    min_price: float = Field(default=0.03, alias="MIN_PRICE")
    max_price: float = Field(default=0.97, alias="MAX_PRICE")

    # Priority filters
    priority_days: int = 14  # Markets resolving within this many days get priority


class IntervalSettings(BaseSettings):
    """Polling interval configuration."""
    market_scan_interval: int = Field(default=300, alias="MARKET_SCAN_INTERVAL")
    position_check_interval: int = Field(default=60, alias="POSITION_CHECK_INTERVAL")
    news_cache_minutes: int = 15


class LogSettings(BaseSettings):
    """Logging configuration."""
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: str = Field(default="trading.log", alias="LOG_FILE")


class Settings:
    """Main settings container aggregating all configuration."""

    def __init__(self):
        self.polymarket = PolymarketSettings()
        self.llm = LLMSettings()
        self.trading = TradingSettings()
        self.risk = RiskSettings()
        self.market_filter = MarketFilterSettings()
        self.intervals = IntervalSettings()
        self.logging = LogSettings()

        # Data directory
        self.data_dir = Path(__file__).parent.parent / "data"
        self.data_dir.mkdir(exist_ok=True)

        # Database path
        self.db_path = self.data_dir / "trading.db"

        # Budget tracking file
        self.budget_file = self.data_dir / "llm_budget.json"

    def validate(self) -> list[str]:
        """Validate required settings are present. Returns list of missing items."""
        missing = []

        if not self.trading.dry_run:
            # Only require API keys for live trading
            if not self.polymarket.api_key:
                missing.append("POLYMARKET_API_KEY")
            if not self.polymarket.api_secret:
                missing.append("POLYMARKET_API_SECRET")
            if not self.polymarket.api_passphrase:
                missing.append("POLYMARKET_API_PASSPHRASE")
            if not self.polymarket.private_key:
                missing.append("PRIVATE_KEY")

        # LLM keys always needed
        if not self.llm.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")
        if not self.llm.openai_api_key:
            missing.append("OPENAI_API_KEY")

        return missing

    def is_valid(self) -> bool:
        """Check if all required settings are present."""
        return len(self.validate()) == 0

    def __repr__(self) -> str:
        return (
            f"Settings(\n"
            f"  dry_run={self.trading.dry_run},\n"
            f"  starting_capital=${self.trading.starting_capital},\n"
            f"  max_position=${self.trading.max_position_size},\n"
            f"  llm_budget=${self.llm.anthropic_budget + self.llm.openai_budget}\n"
            f")"
        )


# Singleton instance
settings = Settings()
