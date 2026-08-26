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

MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def _is_market_hours() -> bool:
    now_ist = datetime.now(IST).time()
    weekday = datetime.now(IST).weekday()
    return weekday < 5 and MARKET_OPEN <= now_ist <= MARKET_CLOSE


async def monitor_open_trades() -> None:
    """Every 60s: check open trades against live prices, auto-close on TP/SL."""
    if not _is_market_hours():
        return

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Trade).where(Trade.status == "entered"))
            trades = result.scalars().all()
            if not trades:
                return

            symbols = list({t.symbol for t in trades})
            prices = await get_prices_batch(symbols)

            redis = await get_redis()
            # Cache fetched prices
            for sym, price in prices.items():
                await redis.setex(f"prices:{sym}", 90, str(price))

            for trade in trades:
                price = prices.get(trade.symbol)
                if price is None:
                    continue

                if price >= trade.target_price:
                    logger.info("TP hit: %s @ %.2f", trade.symbol, price)
                    await close_trade(trade, price, "target-hit", db, redis)
                elif price <= trade.stop_loss:
                    logger.info("SL hit: %s @ %.2f", trade.symbol, price)
                    await close_trade(trade, price, "sl-hit", db, redis)

    except Exception as exc:
        logger.error("monitor_open_trades error: %s", exc)


async def force_exit_all() -> None:
    """3:12 PM IST — force-exit all remaining open trades."""
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Trade).where(Trade.status == "entered"))
            trades = result.scalars().all()
            if not trades:
                return

            symbols = list({t.symbol for t in trades})
            prices = await get_prices_batch(symbols)
            redis = await get_redis()

            for trade in trades:
                price = prices.get(trade.symbol, trade.entry_price)
                logger.info("Force exit: %s @ %.2f", trade.symbol, price)
                await close_trade(trade, price, "force-exit-eod", db, redis)

    except Exception as exc:
        logger.error("force_exit_all error: %s", exc)


async def eod_summary() -> None:
    """3:30 PM IST — send EOD P&L summary via Telegram."""
    try:
        from sqlalchemy import func
        from datetime import date

        async with AsyncSessionLocal() as db:
            today = date.today()
            result = await db.execute(
                select(Trade).where(
                    Trade.status.in_(["target-hit", "sl-hit", "exited"]),
                    func.date(Trade.exit_time) == today,
                )
            )
            trades = result.scalars().all()

        total = len(trades)
        winners = sum(1 for t in trades if (t.net_pnl or 0) > 0)
        losers = total - winners
        net_pnl = sum(t.net_pnl or 0 for t in trades)

        await notify_eod_summary(total=total, winners=winners, losers=losers, net_pnl=net_pnl)

    except Exception as exc:
        logger.error("eod_summary error: %s", exc)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=IST)

    # Monitor open trades every 60 seconds
    scheduler.add_job(monitor_open_trades, "interval", seconds=60, id="monitor")

    # Force exit at 15:12 IST on weekdays
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
