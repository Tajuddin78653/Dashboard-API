"""
risk_engine.py — Pre-trade risk controls and capital safety guard.
"""

import logging
from datetime import datetime, date, timezone
from typing import Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.trade import Trade
from app.config import settings

logger = logging.getLogger(__name__)


def is_market_open_ist() -> bool:
    """Check if current time is within Indian equity market hours (9:15 AM - 3:30 PM IST Mon-Fri)."""
    now = datetime.now(timezone.utc)
    # IST = UTC + 5:30
    ist_mins = (now.hour * 60 + now.minute) + 330
    day = (now.weekday() + (1 if ist_mins >= 1440 else 0)) % 7
    ist_mins = ist_mins % 1440

    # Mon-Fri only
    if day > 4:
        return False
    # 9:15 AM is 555 mins, 3:30 PM is 930 mins
    return 555 <= ist_mins <= 930


async def evaluate_pre_trade_risk(
    db: AsyncSession,
    max_concurrent: int = 3,
    max_daily_trades: int = 10,
    daily_loss_limit: float = 5000.0,
) -> Tuple[bool, str]:
    """
    Evaluates whether a new trade signal passes pre-trade risk controls.
    Returns (allowed: bool, reason: str).
    """
    today = date.today()

    # 1. Market Hours Check
    if not is_market_open_ist() and not getattr(settings, "ALLOW_OFF_MARKET_TESTING", True):
        return False, "Market is closed (IST trading window 09:15 - 15:30)"

    # 2. Concurrent Open Positions Check
    open_res = await db.execute(
        select(func.count(Trade.id)).where(Trade.status == "entered")
    )
    open_count = open_res.scalar() or 0
    if open_count >= max_concurrent:
        logger.warning("Risk filter: Max concurrent positions (%d/%d) reached", open_count, max_concurrent)
        return False, f"Max concurrent positions limit ({open_count}/{max_concurrent}) reached"

    # 3. Daily Trade Count Check
    daily_trades_res = await db.execute(
        select(func.count(Trade.id)).where(func.date(Trade.entry_time) == today)
    )
    daily_count = daily_trades_res.scalar() or 0
    if daily_count >= max_daily_trades:
        logger.warning("Risk filter: Daily max trades (%d/%d) reached", daily_count, max_daily_trades)
        return False, f"Daily max trades limit ({daily_count}/{max_daily_trades}) reached"

    # 4. Daily Loss Limit Check
    daily_pnl_res = await db.execute(
        select(func.coalesce(func.sum(Trade.net_pnl), 0.0)).where(
            func.date(Trade.exit_time) == today,
            Trade.status != "entered"
        )
    )
    realized_loss = daily_pnl_res.scalar() or 0.0
    if realized_loss < -abs(daily_loss_limit):
        logger.warning("Risk filter: Daily loss limit breached (Net P&L: ₹%.2f, Limit: ₹%.2f)", realized_loss, daily_loss_limit)
        return False, f"Daily loss limit breached (Loss: ₹{abs(realized_loss):.2f} >= ₹{daily_loss_limit:.2f})"

    return True, "Risk checks passed"
