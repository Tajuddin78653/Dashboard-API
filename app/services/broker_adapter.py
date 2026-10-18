"""
broker_adapter.py — Modular broker execution adapters for Paper Trading and DhanHQ API v2.
"""

import abc
import logging
import uuid
from typing import Dict, Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class BaseBrokerAdapter(abc.ABC):
    """Abstract base class for trading execution brokers."""

    @abc.abstractmethod
    async def get_available_funds(self) -> float:
        """Fetch current available trading margin / cash."""
        pass

    @abc.abstractmethod
    async def get_ltp(self, symbol: str) -> Optional[float]:
        """Fetch last traded price for symbol."""
        pass

    @abc.abstractmethod
    async def place_buy_order(
        self,
        symbol: str,
        quantity: int,
        order_type: str = "MARKET",
        price: float = 0.0,
    ) -> Dict[str, Any]:
        """Submit a BUY order."""
        pass

    @abc.abstractmethod
    async def place_sell_order(
        self,
        symbol: str,
        quantity: int,
        order_type: str = "MARKET",
        price: float = 0.0,
    ) -> Dict[str, Any]:
        """Submit a SELL order to exit."""
        pass


class PaperBrokerAdapter(BaseBrokerAdapter):
    """Simulated Paper Trading broker."""

    def __init__(self, virtual_balance: float = 100000.0):
        self.virtual_balance = virtual_balance

    async def get_available_funds(self) -> float:
        return self.virtual_balance

    async def get_ltp(self, symbol: str) -> Optional[float]:
        from app.utils.price import get_price
        return await get_price(symbol)

    async def place_buy_order(
        self,
        symbol: str,
        quantity: int,
        order_type: str = "MARKET",
        price: float = 0.0,
    ) -> Dict[str, Any]:
        simulated_order_id = f"PAPER-BUY-{uuid.uuid4().hex[:8].upper()}"
        logger.info("Paper BUY Order placed: %s | Qty: %d | ID: %s", symbol, quantity, simulated_order_id)
        return {
            "status": "success",
            "order_id": simulated_order_id,
            "broker": "paper",
            "symbol": symbol,
            "quantity": quantity,
        }

    async def place_sell_order(
        self,
        symbol: str,
        quantity: int,
        order_type: str = "MARKET",
        price: float = 0.0,
    ) -> Dict[str, Any]:
        simulated_order_id = f"PAPER-SELL-{uuid.uuid4().hex[:8].upper()}"
        logger.info("Paper SELL Order placed: %s | Qty: %d | ID: %s", symbol, quantity, simulated_order_id)
        return {
            "status": "success",
            "order_id": simulated_order_id,
            "broker": "paper",
            "symbol": symbol,
            "quantity": quantity,
        }


class DhanBrokerAdapter(BaseBrokerAdapter):
    """Live broker adapter using DhanHQ API v2."""

    def __init__(self):
        self.client_id = getattr(settings, "DHAN_CLIENT_ID", "")
        self.access_token = getattr(settings, "DHAN_ACCESS_TOKEN", "")
        self._dhan_client = None
        self._init_client()

    def _init_client(self):
        try:
            from dhanhq import dhanhq, DhanContext
            if self.client_id and self.access_token:
                context = DhanContext(self.client_id, self.access_token)
                self._dhan_client = dhanhq(context)
                logger.info("DhanHQ v2 client initialized successfully.")
        except Exception as e:
            logger.warning("Could not initialize DhanHQ SDK: %s", e)

    async def get_available_funds(self) -> float:
        if not self._dhan_client:
            return 0.0
        try:
            resp = self._dhan_client.get_fund_limits()
            data = resp.get("data", {})
            return float(data.get("availabelBalance") or data.get("availableBalance") or 0.0)
        except Exception as e:
            logger.error("Dhan get_fund_limits error: %s", e)
            return 0.0

    async def get_ltp(self, symbol: str) -> Optional[float]:
        from app.utils.price import get_price
        return await get_price(symbol)

    async def place_buy_order(
        self,
        symbol: str,
        quantity: int,
        order_type: str = "MARKET",
        price: float = 0.0,
    ) -> Dict[str, Any]:
        if not self._dhan_client:
            raise RuntimeError("Dhan credentials not configured.")
        try:
            # Look up security ID if needed or submit order
            resp = self._dhan_client.place_order(
                security_id=symbol,
                exchange_segment=self._dhan_client.NSE,
                transaction_type=self._dhan_client.BUY,
                quantity=quantity,
                order_type=self._dhan_client.MARKET if order_type == "MARKET" else self._dhan_client.LIMIT,
                product_type=self._dhan_client.INTRA,
                price=price,
            )
            order_id = resp.get("data", {}).get("orderId", "")
            logger.info("Live Dhan BUY Order placed: %s | Qty: %d | ID: %s", symbol, quantity, order_id)
            return {
                "status": "success",
                "order_id": order_id,
                "broker": "dhan",
                "raw": resp,
            }
        except Exception as e:
            logger.error("Dhan place_buy_order failed: %s", e)
            raise

    async def place_sell_order(
        self,
        symbol: str,
        quantity: int,
        order_type: str = "MARKET",
        price: float = 0.0,
    ) -> Dict[str, Any]:
        if not self._dhan_client:
            raise RuntimeError("Dhan credentials not configured.")
        try:
            resp = self._dhan_client.place_order(
                security_id=symbol,
                exchange_segment=self._dhan_client.NSE,
                transaction_type=self._dhan_client.SELL,
                quantity=quantity,
                order_type=self._dhan_client.MARKET,
                product_type=self._dhan_client.INTRA,
                price=price,
            )
            order_id = resp.get("data", {}).get("orderId", "")
            logger.info("Live Dhan SELL Order placed: %s | Qty: %d | ID: %s", symbol, quantity, order_id)
            return {
                "status": "success",
                "order_id": order_id,
                "broker": "dhan",
                "raw": resp,
            }
        except Exception as e:
            logger.error("Dhan place_sell_order failed: %s", e)
            raise


def get_broker_adapter(paper_mode: bool = True) -> BaseBrokerAdapter:
    """Factory helper returning appropriate broker adapter."""
    if paper_mode:
        return PaperBrokerAdapter()
    return DhanBrokerAdapter()
