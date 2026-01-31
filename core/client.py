"""
Polymarket API client wrapper for Gamma (public) and CLOB (trading) APIs.
"""

import time
from datetime import datetime
from typing import Optional, Any
import requests

from config import settings
from data.models import Market, Token, Order, OrderStatus, OrderType, Side
from utils.logger import get_logger
from utils.helpers import (
    retry_with_backoff,
    RateLimiter,
    SlidingWindowRateLimiter,
    parse_iso_datetime,
)

logger = get_logger("polymarket.client")


class PolymarketClient:
    """
    Unified client for Polymarket APIs.

    - Gamma API: Public, no auth required. For fetching events and markets.
    - CLOB API: Authenticated. For order book data and trading.
    """

    def __init__(self):
        self.gamma_url = settings.polymarket.gamma_url
        self.clob_url = settings.polymarket.clob_url

        # Rate limiters
        self.public_limiter = SlidingWindowRateLimiter(
            max_calls=settings.polymarket.public_rate_limit,
            window_seconds=60.0
        )
        self.trading_limiter = SlidingWindowRateLimiter(
            max_calls=settings.polymarket.trading_rate_limit,
            window_seconds=60.0
        )

        # Session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

        # CLOB client (for authenticated operations)
        self._clob_client = None
        self._initialize_clob()

    def _initialize_clob(self):
        """Initialize the py-clob-client for authenticated operations."""
        if not settings.polymarket.private_key:
            logger.warning("No private key configured - trading disabled")
            return

        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds

            # Create API credentials
            creds = ApiCreds(
                api_key=settings.polymarket.api_key,
                api_secret=settings.polymarket.api_secret,
                api_passphrase=settings.polymarket.api_passphrase,
            )

            self._clob_client = ClobClient(
                host=self.clob_url,
                key=settings.polymarket.private_key,
                chain_id=137,  # Polygon mainnet
                creds=creds,
            )
            logger.info("CLOB client initialized successfully")
        except ImportError:
            logger.warning("py-clob-client not installed - trading disabled")
        except Exception as e:
            logger.error(f"Failed to initialize CLOB client: {e}")

    # ========== Gamma API (Public) ==========

    @retry_with_backoff(max_retries=3, base_delay=1.0)
    def _gamma_request(
        self,
        endpoint: str,
        params: Optional[dict] = None,
    ) -> Any:
        """Make a request to the Gamma API."""
        self.public_limiter.acquire()

        url = f"{self.gamma_url}{endpoint}"
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()

        return response.json()

    def get_events(
        self,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """
        Fetch events from Gamma API.

        Events are containers for related markets (e.g., "US Election 2024"
        contains "Winner" market plus individual state markets).
        """
        params = {
            "active": str(active).lower(),
            "closed": str(closed).lower(),
            "limit": limit,
            "offset": offset,
        }

        data = self._gamma_request("/events", params)
        return data if isinstance(data, list) else []

    def get_all_events(self, active: bool = True) -> list[dict]:
        """Paginate through all events."""
        all_events = []
        offset = 0
        limit = 100

        while True:
            events = self.get_events(active=active, limit=limit, offset=offset)
            if not events:
                break
            all_events.extend(events)
            if len(events) < limit:
                break
            offset += limit

        logger.info(f"Fetched {len(all_events)} events from Gamma API")
        return all_events

    def get_markets(
        self,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """
        Fetch markets from Gamma API.

        Markets are individual prediction questions with YES/NO outcomes.
        """
        params = {
            "active": str(active).lower(),
            "closed": str(closed).lower(),
            "limit": limit,
            "offset": offset,
        }

        data = self._gamma_request("/markets", params)
        return data if isinstance(data, list) else []

    def get_all_markets(self, active: bool = True) -> list[dict]:
        """Paginate through all markets."""
        all_markets = []
        offset = 0
        limit = 100

        while True:
            markets = self.get_markets(active=active, limit=limit, offset=offset)
            if not markets:
                break
            all_markets.extend(markets)
            if len(markets) < limit:
                break
            offset += limit

        logger.info(f"Fetched {len(all_markets)} markets from Gamma API")
        return all_markets

    def get_market(self, condition_id: str) -> Optional[dict]:
        """Fetch a single market by condition ID."""
        try:
            return self._gamma_request(f"/markets/{condition_id}")
        except Exception as e:
            logger.error(f"Failed to fetch market {condition_id}: {e}")
            return None

    def get_event(self, event_id: str) -> Optional[dict]:
        """Fetch a single event by ID."""
        try:
            return self._gamma_request(f"/events/{event_id}")
        except Exception as e:
            logger.error(f"Failed to fetch event {event_id}: {e}")
            return None

    def parse_market(self, raw: dict) -> Market:
        """Parse raw Gamma API response into Market model."""
        # Extract tokens
        tokens = []
        for outcome in raw.get("outcomes", ["Yes", "No"]):
            # Find the corresponding token
            outcome_lower = outcome.lower()
            price = 0.5  # Default

            # Gamma API returns prices in various formats
            if "outcomePrices" in raw:
                prices = raw["outcomePrices"]
                if isinstance(prices, list) and len(prices) >= 2:
                    idx = 0 if outcome_lower == "yes" else 1
                    price = float(prices[idx]) if idx < len(prices) else 0.5
            elif "bestBid" in raw or "bestAsk" in raw:
                # Use mid price if available
                bid = float(raw.get("bestBid", 0) or 0)
                ask = float(raw.get("bestAsk", 0) or 0)
                if bid and ask:
                    price = (bid + ask) / 2
                elif bid:
                    price = bid
                elif ask:
                    price = ask

            # Get token ID
            token_id = ""
            if "clobTokenIds" in raw:
                token_ids = raw["clobTokenIds"]
                if isinstance(token_ids, list):
                    idx = 0 if outcome_lower == "yes" else 1
                    token_id = token_ids[idx] if idx < len(token_ids) else ""

            tokens.append(Token(
                token_id=token_id,
                outcome=outcome,
                price=price,
            ))

        # Parse end date
        end_date = None
        if raw.get("endDate"):
            end_date = parse_iso_datetime(raw["endDate"])
        elif raw.get("endDateIso"):
            end_date = parse_iso_datetime(raw["endDateIso"])

        return Market(
            id=raw.get("conditionId", raw.get("id", "")),
            question=raw.get("question", ""),
            description=raw.get("description", ""),
            category=raw.get("category", raw.get("groupItemTitle", "")),
            tokens=tokens,
            end_date=end_date,
            active=raw.get("active", True),
            closed=raw.get("closed", False),
            resolved=raw.get("resolved", False),
            liquidity=float(raw.get("liquidity", 0) or 0),
            volume=float(raw.get("volume", 0) or 0),
            volume_24h=float(raw.get("volume24hr", 0) or 0),
            neg_risk=raw.get("negRisk", False),
            event_id=raw.get("eventSlug", raw.get("event_id")),
            event_title=raw.get("groupItemTitle", ""),
        )

    # ========== CLOB API (Trading) ==========

    def get_order_book(self, token_id: str) -> dict:
        """
        Fetch order book for a token from CLOB API.

        Returns dict with 'bids' and 'asks' lists.
        """
        if not self._clob_client:
            return {"bids": [], "asks": []}

        try:
            self.public_limiter.acquire()
            book = self._clob_client.get_order_book(token_id)
            return {
                "bids": book.bids if hasattr(book, "bids") else [],
                "asks": book.asks if hasattr(book, "asks") else [],
            }
        except Exception as e:
            logger.error(f"Failed to fetch order book for {token_id}: {e}")
            return {"bids": [], "asks": []}

    def get_midpoint_price(self, token_id: str) -> Optional[float]:
        """Get midpoint price from order book."""
        book = self.get_order_book(token_id)

        bids = book.get("bids", [])
        asks = book.get("asks", [])

        if not bids or not asks:
            return None

        best_bid = float(bids[0]["price"]) if bids else 0
        best_ask = float(asks[0]["price"]) if asks else 1

        return (best_bid + best_ask) / 2

    def get_spread(self, token_id: str) -> dict:
        """Get bid-ask spread information."""
        book = self.get_order_book(token_id)

        bids = book.get("bids", [])
        asks = book.get("asks", [])

        best_bid = float(bids[0]["price"]) if bids else 0
        best_ask = float(asks[0]["price"]) if asks else 1

        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": best_ask - best_bid,
            "spread_pct": (best_ask - best_bid) / best_ask if best_ask > 0 else 0,
            "bid_depth": sum(float(b.get("size", 0)) for b in bids[:5]),
            "ask_depth": sum(float(a.get("size", 0)) for a in asks[:5]),
        }

    def place_order(
        self,
        token_id: str,
        side: Side,
        price: float,
        size: float,
        order_type: OrderType = OrderType.GTC,
    ) -> Optional[Order]:
        """
        Place an order on the CLOB.

        Args:
            token_id: Token to trade
            side: BUY or SELL
            price: Limit price (0-1)
            size: Number of shares
            order_type: GTC, FOK, or IOC

        Returns:
            Order object with ID if successful, None otherwise
        """
        if settings.trading.dry_run:
            logger.info(f"[DRY RUN] Would place {side.value} order: {size} @ {price}")
            # Return a mock order for dry run
            return Order(
                id=f"dry_run_{int(time.time())}",
                market_id="",
                token_id=token_id,
                side=side,
                order_type=order_type,
                price=price,
                size=size,
                status=OrderStatus.FILLED,
                filled_size=size,
            )

        if not self._clob_client:
            logger.error("CLOB client not initialized - cannot place order")
            return None

        try:
            self.trading_limiter.acquire()

            # Map our types to py-clob-client types
            from py_clob_client.clob_types import OrderArgs, OrderType as ClobOrderType

            clob_order_type = {
                OrderType.GTC: ClobOrderType.GTC,
                OrderType.FOK: ClobOrderType.FOK,
                OrderType.IOC: ClobOrderType.IOC,
            }.get(order_type, ClobOrderType.GTC)

            # Create and sign the order
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=side.value,
            )

            signed_order = self._clob_client.create_order(order_args)
            response = self._clob_client.post_order(signed_order, clob_order_type)

            if response and response.get("orderID"):
                logger.info(f"Order placed: {response['orderID']}")
                return Order(
                    id=response["orderID"],
                    market_id="",
                    token_id=token_id,
                    side=side,
                    order_type=order_type,
                    price=price,
                    size=size,
                    status=OrderStatus.OPEN,
                )
            else:
                logger.error(f"Order placement failed: {response}")
                return None

        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        if settings.trading.dry_run:
            logger.info(f"[DRY RUN] Would cancel order {order_id}")
            return True

        if not self._clob_client:
            return False

        try:
            self.trading_limiter.acquire()
            response = self._clob_client.cancel(order_id)
            return response.get("success", False)
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    def get_order_status(self, order_id: str) -> Optional[OrderStatus]:
        """Get current status of an order."""
        if not self._clob_client:
            return None

        try:
            self.public_limiter.acquire()
            order = self._clob_client.get_order(order_id)
            if order:
                status_map = {
                    "OPEN": OrderStatus.OPEN,
                    "FILLED": OrderStatus.FILLED,
                    "CANCELLED": OrderStatus.CANCELLED,
                    "EXPIRED": OrderStatus.EXPIRED,
                    "MATCHED": OrderStatus.FILLED,
                }
                return status_map.get(order.get("status", ""), OrderStatus.PENDING)
            return None
        except Exception as e:
            logger.error(f"Failed to get order status for {order_id}: {e}")
            return None

    def get_positions(self) -> list[dict]:
        """Get current positions from CLOB API."""
        if not self._clob_client:
            return []

        try:
            self.public_limiter.acquire()
            return self._clob_client.get_positions() or []
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            return []

    def get_balance(self) -> float:
        """Get USDC balance."""
        if settings.trading.dry_run:
            # Return simulated balance in dry run mode
            return settings.trading.starting_capital

        if not self._clob_client:
            return 0.0

        try:
            self.public_limiter.acquire()
            balance = self._clob_client.get_balance_allowance()
            if balance:
                return float(balance.get("balance", 0)) / 1e6  # Convert from USDC decimals
            return 0.0
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return 0.0

    # ========== Utility Methods ==========

    def health_check(self) -> dict:
        """Check API connectivity."""
        status = {
            "gamma_api": False,
            "clob_api": False,
            "authenticated": False,
        }

        # Check Gamma API
        try:
            self._gamma_request("/markets", {"limit": 1})
            status["gamma_api"] = True
        except Exception as e:
            logger.error(f"Gamma API health check failed: {e}")

        # Check CLOB API
        if self._clob_client:
            try:
                self._clob_client.get_ok()
                status["clob_api"] = True
                status["authenticated"] = True
            except Exception as e:
                logger.error(f"CLOB API health check failed: {e}")

        return status
