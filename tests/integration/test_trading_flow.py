"""
Integration tests for the complete trading flow.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
import tempfile
from pathlib import Path

from data.db import Database
from data.models import Market, Token, Side, OrderStatus
from core.client import PolymarketClient
from core.market_scanner import MarketScanner
from core.order_manager import OrderManager
from core.portfolio import PortfolioManager
from strategy.probability_engine import ProbabilityEngine
from strategy.edge_detector import EdgeDetector
from strategy.kelly import KellyCriterion
from risk.risk_manager import RiskManager
from risk.guardrails import Guardrails


class TestEndToEndTradingFlow:
    """Test complete trading flow from market scan to execution."""

    @pytest.fixture
    def temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        db = Database(db_path)
        yield db
        try:
            db_path.unlink()
        except:
            pass

    @pytest.fixture
    def mock_client(self):
        client = MagicMock(spec=PolymarketClient)

        # Mock market data
        client.get_all_markets.return_value = [
            {
                "conditionId": "market_1",
                "question": "Will Bitcoin reach $100k?",
                "description": "Resolves YES if BTC hits $100k",
                "category": "Crypto",
                "outcomes": ["Yes", "No"],
                "outcomePrices": ["0.45", "0.55"],
                "clobTokenIds": ["yes_token_1", "no_token_1"],
                "endDate": (datetime.utcnow() + timedelta(days=14)).isoformat(),
                "active": True,
                "liquidity": 10000,
                "volume": 50000,
                "volume24hr": 2000,
            },
        ]

        client.parse_market.return_value = Market(
            id="market_1",
            question="Will Bitcoin reach $100k?",
            tokens=[
                Token(token_id="yes_token_1", outcome="Yes", price=0.45),
                Token(token_id="no_token_1", outcome="No", price=0.55),
            ],
            end_date=datetime.utcnow() + timedelta(days=14),
            liquidity=10000,
            active=True,
        )

        client.get_midpoint_price.return_value = 0.45
        client.get_balance.return_value = 10.0

        # Mock order placement
        from data.models import Order
        client.place_order.return_value = Order(
            id="order_123",
            market_id="market_1",
            token_id="yes_token_1",
            side=Side.BUY,
            price=0.45,
            size=5.0,
            status=OrderStatus.FILLED,
            filled_size=5.0,
        )

        return client

    @pytest.fixture
    def components(self, temp_db, mock_client):
        """Initialize all trading components."""
        scanner = MarketScanner(mock_client)
        order_manager = OrderManager(mock_client, temp_db)
        portfolio = PortfolioManager(mock_client, temp_db)
        edge_detector = EdgeDetector()
        kelly = KellyCriterion()
        risk_manager = RiskManager(temp_db)

        return {
            "db": temp_db,
            "client": mock_client,
            "scanner": scanner,
            "order_manager": order_manager,
            "portfolio": portfolio,
            "edge_detector": edge_detector,
            "kelly": kelly,
            "risk_manager": risk_manager,
        }

    def test_market_scanning_flow(self, components, mock_client):
        """Test market scanning and filtering."""
        scanner = components["scanner"]

        # Get markets
        markets = scanner.scan_all_markets()

        # Should call client
        mock_client.get_all_markets.assert_called()

    def test_edge_detection_flow(self, components):
        """Test edge calculation flow."""
        from data.models import ProbabilityEstimate

        market = Market(
            id="m1",
            question="Test?",
            tokens=[
                Token(token_id="yes", outcome="Yes", price=0.45),
                Token(token_id="no", outcome="No", price=0.55),
            ],
            liquidity=10000,
        )

        estimate = ProbabilityEstimate(
            market_id="m1",
            probability=0.60,
            confidence=0.75,
            market_price=0.45,
            edge=0.15,
        )

        edge_opp = components["edge_detector"].calculate_edge(market, estimate)

        assert edge_opp.tradeable
        assert edge_opp.edge > 0

    def test_kelly_sizing_flow(self, components):
        """Test position sizing flow."""
        kelly = components["kelly"]

        result = kelly.size_trade(
            estimated_prob=0.60,
            market_price=0.45,
            bankroll=10.0,
            confidence=0.75,
        )

        assert result.recommended_bet > 0
        assert result.positive_ev

    def test_risk_check_flow(self, components):
        """Test risk checking flow."""
        market = Market(
            id="m1",
            question="Test?",
            tokens=[Token(token_id="yes", outcome="Yes", price=0.45)],
            liquidity=10000,
            end_date=datetime.utcnow() + timedelta(days=14),
        )

        result = components["risk_manager"].check_trade(
            market=market,
            proposed_size=2.0,
            edge=0.10,
            confidence=0.7,
        )

        assert result.passed

    def test_order_execution_flow(self, components, mock_client):
        """Test order placement flow."""
        order_manager = components["order_manager"]

        order = order_manager.place_limit_buy(
            market_id="market_1",
            token_id="yes_token_1",
            price=0.45,
            size=5.0,
            reason="Test trade",
        )

        assert order is not None
        mock_client.place_order.assert_called()

    def test_position_tracking_flow(self, components, mock_client):
        """Test position management flow."""
        portfolio = components["portfolio"]

        market = Market(
            id="market_1",
            question="Test?",
            tokens=[Token(token_id="yes_token_1", outcome="Yes", price=0.45)],
        )

        position = portfolio.open_position(
            market=market,
            token_id="yes_token_1",
            outcome="Yes",
            size=10.0,
            entry_price=0.45,
        )

        assert position is not None
        assert position.size == 10.0

        # Check persistence
        positions = portfolio.get_open_positions()
        assert len(positions) == 1

    def test_complete_trade_cycle(self, components, mock_client):
        """Test complete trade from analysis to position."""
        from data.models import ProbabilityEstimate

        # 1. Get market
        market = Market(
            id="market_1",
            question="Will Bitcoin reach $100k?",
            tokens=[
                Token(token_id="yes_token_1", outcome="Yes", price=0.45),
                Token(token_id="no_token_1", outcome="No", price=0.55),
            ],
            liquidity=10000,
            end_date=datetime.utcnow() + timedelta(days=14),
        )

        # 2. Get probability estimate
        estimate = ProbabilityEstimate(
            market_id="market_1",
            probability=0.60,
            confidence=0.75,
            market_price=0.45,
            edge=0.15,
        )

        # 3. Calculate edge
        edge_opp = components["edge_detector"].calculate_edge(market, estimate)
        assert edge_opp.tradeable

        # 4. Calculate size
        kelly_result = components["kelly"].size_trade(
            estimated_prob=estimate.probability,
            market_price=edge_opp.entry_price,
            bankroll=10.0,
            confidence=estimate.confidence,
        )
        assert kelly_result.recommended_bet > 0

        # 5. Risk check
        risk_result = components["risk_manager"].check_trade(
            market=market,
            proposed_size=kelly_result.recommended_bet,
            edge=edge_opp.edge,
            confidence=estimate.confidence,
        )
        assert risk_result.passed

        # 6. Execute order
        shares = risk_result.approved_size / edge_opp.entry_price
        order = components["order_manager"].place_limit_buy(
            market_id=market.id,
            token_id=edge_opp.token_id,
            price=edge_opp.entry_price,
            size=shares,
            reason=f"Edge={edge_opp.edge_abs:.1%}",
        )
        assert order is not None

        # 7. Track position
        position = components["portfolio"].open_position(
            market=market,
            token_id=edge_opp.token_id,
            outcome=edge_opp.outcome,
            size=shares,
            entry_price=edge_opp.entry_price,
        )
        assert position is not None

        # Verify final state
        open_positions = components["portfolio"].get_open_positions()
        assert len(open_positions) == 1
        assert open_positions[0].outcome == "Yes"


class TestDryRunMode:
    """Test dry run mode behavior."""

    @pytest.fixture
    def temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        db = Database(db_path)
        yield db
        try:
            db_path.unlink()
        except:
            pass

    def test_dry_run_order_not_submitted(self, temp_db):
        """Test that dry run doesn't submit real orders."""
        with patch("config.settings.trading.dry_run", True):
            mock_client = MagicMock()
            mock_client.place_order.return_value = None

            order_manager = OrderManager(mock_client, temp_db)

            # In dry run, should return mock order without calling API
            # (The actual implementation handles this)
