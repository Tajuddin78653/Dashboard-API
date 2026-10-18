"""
dynamic_tsl_monitor.py — Real-time price tracking, dynamic TSL ratcheting, and auto-exits.
"""

import asyncio
import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.trade import Trade
from app.services.trade_service import close_trade
from app.services.strategy_engine import update_trailing_stop_loss
from app.utils.price import get_price
from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)


async def monitor_open_positions_tick(db: AsyncSession) -> list[dict]:
    """
    Single tick iteration for all open positions:
    - Fetches current LTP
    - Dynamically ratchets trailing stop loss upward
    - Triggers auto-exit on Target, Trailing SL, or Initial SL hit
    """
    result = await db.execute(
        select(Trade).where(Trade.status == "entered")
    )
    open_trades = result.scalars().all()
    if not open_trades:
        return []

    redis = await get_redis()
    events = []

    for trade in open_trades:
        try:
            current_price = await get_price(trade.symbol)
            if not current_price or current_price <= 0:
                continue

            # Default initial values if not set
            initial_sl = trade.stop_loss
            target_price = trade.target_price
            current_tsl = getattr(trade, "trailing_sl", None) or initial_sl

            # Dynamic upward ratcheting of Trailing SL
            tsl_pct = 1.0  # Default 1% trailing step
            new_tsl = update_trailing_stop_loss(
                entry_price=trade.entry_price,
                peak_price=current_price,
                current_tsl=current_tsl,
                tsl_pct=tsl_pct,
            )

            # Check Auto-Exit Triggers
            exit_reason = None
            if current_price >= target_price:
                exit_reason = "target-hit"
            elif current_price <= new_tsl and new_tsl > initial_sl:
                exit_reason = "trailing-sl-hit"
            elif current_price <= initial_sl:
                exit_reason = "sl-hit"

            if exit_reason:
                logger.info(
                    "Auto-Exit triggered for %s (ID: %s) @ ₹%.2f | Reason: %s",
                    trade.symbol, trade.trade_id, current_price, exit_reason
                )
                closed = await close_trade(
                    trade=trade,
                    exit_price=current_price,
                    reason=exit_reason,
                    db=db,
                    redis=redis,
                )
                events.append({
                    "event": "trade_closed",
                    "trade_id": closed.trade_id,
                    "symbol": closed.symbol,
                    "exit_price": current_price,
                    "reason": exit_reason,
                    "net_pnl": closed.net_pnl,
                })
            else:
                events.append({
                    "event": "price_update",
                    "trade_id": trade.trade_id,
                    "symbol": trade.symbol,
                    "current_price": current_price,
                    "trailing_sl": new_tsl,
                    "mtm": round((current_price - trade.entry_price) * trade.quantity, 2),
                })

        except Exception as exc:
            logger.error("Error monitoring trade %s: %s", trade.trade_id, exc)

    return events
