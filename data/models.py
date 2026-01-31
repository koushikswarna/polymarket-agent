"""
Pydantic data models for the Polymarket Trading Agent.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Side(str, Enum):
    """Order side."""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Order type for CLOB."""
    GTC = "GTC"  # Good Till Cancelled - default for normal trades
    FOK = "FOK"  # Fill Or Kill - for arbitrage (atomic execution)
    IOC = "IOC"  # Immediate Or Cancel - for momentum


class OrderStatus(str, Enum):
    """Order status in lifecycle."""
    PENDING = "PENDING"
    OPEN = "OPEN"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class Token(BaseModel):
    """Represents a tradeable token (YES or NO outcome)."""
    token_id: str
    outcome: str  # "Yes" or "No"
    price: float = Field(ge=0.0, le=1.0)
    winner: Optional[bool] = None  # Set after resolution


class Market(BaseModel):
    """Represents a Polymarket prediction market."""
    id: str  # Condition ID
    question: str
    description: str = ""
    category: str = ""

    # Outcomes
    tokens: list[Token] = []

    # Market metadata
    end_date: Optional[datetime] = None
    resolution_date: Optional[datetime] = None
    active: bool = True
    closed: bool = False
    resolved: bool = False

    # Liquidity and volume
    liquidity: float = 0.0
    volume: float = 0.0
    volume_24h: float = 0.0

    # NegRisk flag (for multi-outcome arbitrage)
    neg_risk: bool = False

    # Event grouping
    event_id: Optional[str] = None
    event_title: Optional[str] = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def hours_to_resolution(self) -> Optional[float]:
        """Calculate hours until market resolution."""
        if not self.end_date:
            return None
        delta = self.end_date - datetime.utcnow()
        return delta.total_seconds() / 3600

    @property
    def days_to_resolution(self) -> Optional[float]:
        """Calculate days until market resolution."""
        hours = self.hours_to_resolution
        return hours / 24 if hours else None

    @property
    def yes_price(self) -> Optional[float]:
        """Get YES token price."""
        for token in self.tokens:
            if token.outcome.lower() == "yes":
                return token.price
        return None

    @property
    def no_price(self) -> Optional[float]:
        """Get NO token price."""
        for token in self.tokens:
            if token.outcome.lower() == "no":
                return token.price
        return None


class Order(BaseModel):
    """Represents an order on the CLOB."""
    id: Optional[str] = None  # Assigned by CLOB
    market_id: str
    token_id: str

    side: Side
    order_type: OrderType = OrderType.GTC

    price: float = Field(ge=0.0, le=1.0)
    size: float = Field(gt=0.0)  # In shares

    status: OrderStatus = OrderStatus.PENDING
    filled_size: float = 0.0

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Metadata
    reason: str = ""  # Why this order was placed

    @property
    def remaining_size(self) -> float:
        """Calculate unfilled portion."""
        return self.size - self.filled_size

    @property
    def is_complete(self) -> bool:
        """Check if order is in a terminal state."""
        return self.status in [
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
            OrderStatus.FAILED,
        ]


class Trade(BaseModel):
    """Represents an executed trade."""
    id: str
    order_id: str
    market_id: str
    token_id: str

    side: Side
    price: float
    size: float

    # Cost basis
    cost: float  # price * size
    fees: float = 0.0  # Polymarket is fee-free on maker

    # Timestamps
    executed_at: datetime = Field(default_factory=datetime.utcnow)

    # Metadata
    reason: str = ""


class Position(BaseModel):
    """Represents an open position."""
    market_id: str
    token_id: str
    market_question: str = ""
    outcome: str = ""  # "Yes" or "No"

    # Position details
    size: float = 0.0  # Number of shares
    avg_entry_price: float = 0.0
    cost_basis: float = 0.0  # Total cost

    # Current state
    current_price: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0

    # Resolution
    resolved: bool = False
    winning: Optional[bool] = None
    realized_pnl: float = 0.0

    # Timestamps
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None

    def update_mark(self, current_price: float):
        """Update position with current market price."""
        self.current_price = current_price
        self.market_value = self.size * current_price
        self.unrealized_pnl = self.market_value - self.cost_basis
        if self.cost_basis > 0:
            self.unrealized_pnl_pct = self.unrealized_pnl / self.cost_basis
        self.updated_at = datetime.utcnow()


class ProbabilityEstimate(BaseModel):
    """AI-generated probability estimate for a market."""
    market_id: str

    # Estimate details
    probability: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)  # Model's confidence in estimate

    # Source
    model: str  # "claude" or "gpt"
    reasoning: str = ""

    # Market context at time of estimate
    market_price: float = 0.0

    # Calculated edge
    edge: float = 0.0  # probability - market_price (for YES)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # News used in analysis
    news_summary: str = ""

    @property
    def has_positive_edge(self) -> bool:
        """Check if there's positive edge in either direction."""
        return abs(self.edge) > 0


class ArbitrageOpportunity(BaseModel):
    """Detected arbitrage opportunity in NegRisk markets."""
    event_id: str
    event_title: str = ""

    # Market details
    markets: list[str] = []  # List of market IDs in the arb

    # Arb type
    arb_type: str  # "long" (sum of YES < 1) or "short" (sum of NO < 1)

    # Expected profit
    total_cost: float  # Cost to buy all positions
    guaranteed_payout: float  # Guaranteed return (1.0 for binary)
    profit: float  # guaranteed_payout - total_cost
    profit_pct: float  # profit / total_cost

    # Individual legs
    legs: list[dict] = []  # [{market_id, token_id, price, size}]

    # Timestamps
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    executed: bool = False
    executed_at: Optional[datetime] = None


class RiskCheckResult(BaseModel):
    """Result of pre-trade risk checks."""
    passed: bool
    checks: dict[str, bool] = {}  # Individual check results
    reasons: list[str] = []  # Failure reasons if any

    # Adjusted sizing
    original_size: float = 0.0
    approved_size: float = 0.0
    size_reduced: bool = False
    reduction_reason: str = ""


class DailyStats(BaseModel):
    """Daily trading statistics."""
    date: str  # YYYY-MM-DD

    # P&L
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_pnl: float = 0.0

    # Trading activity
    trades_count: int = 0
    wins: int = 0
    losses: int = 0

    # LLM usage
    claude_calls: int = 0
    gpt_calls: int = 0
    claude_cost: float = 0.0
    gpt_cost: float = 0.0

    # Risk metrics
    max_drawdown: float = 0.0
    consecutive_losses: int = 0


class LLMBudget(BaseModel):
    """Track LLM API usage and remaining budget."""
    anthropic_spent: float = 0.0
    anthropic_budget: float = 4.50
    anthropic_calls: int = 0

    openai_spent: float = 0.0
    openai_budget: float = 5.00
    openai_calls: int = 0

    last_updated: datetime = Field(default_factory=datetime.utcnow)

    @property
    def anthropic_remaining(self) -> float:
        return max(0.0, self.anthropic_budget - self.anthropic_spent)

    @property
    def openai_remaining(self) -> float:
        return max(0.0, self.openai_budget - self.openai_spent)

    @property
    def total_remaining(self) -> float:
        return self.anthropic_remaining + self.openai_remaining

    @property
    def anthropic_exhausted(self) -> bool:
        return self.anthropic_remaining <= 0

    @property
    def openai_exhausted(self) -> bool:
        return self.openai_remaining <= 0

    @property
    def all_exhausted(self) -> bool:
        return self.anthropic_exhausted and self.openai_exhausted
