import logging
from datetime import datetime, time, timezone

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.trade import Trade
from app.utils.price import get_prices_batch
from app.services.trade_service import close_trade
from app.core.redis_client import get_redis
from app.core.telegram import notify_eod_summary
from app.config import settings

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

MARKET_OPEN  = time(9, 15)
MARKET_CLOSE = time(15, 30)

# Risk constants
SL_PCT = 0.01   # Hard stop loss = -1% from entry (always active)
TP_PCT = 0.01   # Take profit    = +1% from entry (auto-exit, no trailing)


def _is_market_hours() -> bool:
    now_ist = datetime.now(IST).time()
    weekday = datetime.now(IST).weekday()
    return weekday < 5 and MARKET_OPEN <= now_ist <= MARKET_CLOSE


async def monitor_open_trades() -> None:
    """
    Every 60s during market hours - simple fixed exit logic:

    SL  : price <= entry x (1 - 1%)  → EXIT "sl-hit"
    TP  : price >= entry x (1 + 1%)  → EXIT "target-hit"

    No trailing SL. Trade closes immediately on either trigger.
    """
    if not _is_market_hours():
        return

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Trade).where(Trade.status == "entered"))
            trades = result.scalars().all()
            if not trades:
                return

            symbols = list({t.symbol for t in trades})
            prices  = await get_prices_batch(symbols)
            redis   = await get_redis()

            # Cache live prices
            for sym, p in prices.items():
                try:
                    await redis.set(f"prices:{sym}", str(p))
                except Exception:
                    pass

            for trade in trades:
                price = prices.get(trade.symbol)
                if price is None:
                    logger.warning("No live price for %s — skipping this tick", trade.symbol)
                    continue

                hard_sl  = round(trade.entry_price * (1 - SL_PCT), 2)
                tp_level = round(trade.entry_price * (1 + TP_PCT),  2)

                if price <= hard_sl:
                    logger.info("SL hit: %s @ %.2f  SL=%.2f", trade.symbol, price, hard_sl)
                    await close_trade(trade, price, "sl-hit", db, redis)

                elif price >= tp_level:
                    logger.info("TP hit: %s @ %.2f  TP=%.2f", trade.symbol, price, tp_level)
                    await close_trade(trade, price, "target-hit", db, redis)

    except Exception as exc:
        logger.error("monitor_open_trades error: %s", exc)


async def force_exit_all() -> None:
    """FORCE_EXIT_TIME IST - force-exit all remaining open trades at market price."""
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Trade).where(Trade.status == "entered"))
            trades = result.scalars().all()
            if not trades:
                return

            symbols = list({t.symbol for t in trades})
            prices  = await get_prices_batch(symbols)
            redis   = await get_redis()

            for trade in trades:
                price = prices.get(trade.symbol, trade.entry_price)
                logger.info("Force exit: %s @ %.2f", trade.symbol, price)
                await close_trade(trade, price, "force-exit-eod", db, redis)

    except Exception as exc:
        logger.error("force_exit_all error: %s", exc)


async def eod_summary() -> None:
    """3:30 PM IST - send EOD P&L summary via Telegram."""
    try:
        from sqlalchemy import func
        from datetime import date

        async with AsyncSessionLocal() as db:
            today = date.today()
            result = await db.execute(
                select(Trade).where(
                    Trade.status.in_(["target-hit", "sl-hit", "trailing-sl-hit", "exited"]),
                    func.date(Trade.exit_time) == today,
                )
            )
            trades = result.scalars().all()

        total   = len(trades)
        winners = sum(1 for t in trades if (t.net_pnl or 0) > 0)
        losers  = total - winners
        net_pnl = sum(t.net_pnl or 0 for t in trades)

        await notify_eod_summary(total=total, winners=winners, losers=losers, net_pnl=net_pnl)

    except Exception as exc:
        logger.error("eod_summary error: %s", exc)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=IST)

    # Monitor open trades every 60 seconds
    scheduler.add_job(monitor_open_trades, "interval", seconds=60, id="monitor")

    # Force exit at configured time IST on weekdays
    force_h, force_m = (int(x) for x in settings.FORCE_EXIT_TIME.split(":"))
    scheduler.add_job(
        force_exit_all, "cron",
        hour=force_h, minute=force_m,
        day_of_week="mon-fri",
        id="force_exit",
    )

    # EOD summary at 15:30 IST on weekdays
    scheduler.add_job(
        eod_summary, "cron",
        hour=15, minute=30,
        day_of_week="mon-fri",
        id="eod_summary",
    )

    return scheduler
