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

# ── Risk constants ────────────────────────────────────────────────────────────
SL_PCT       = 0.015   # Hard stop loss   = -1.5% from entry
INITIAL_TP   = 0.0005  # Initial target   = +0.05% from entry (quick scalp)
TRAIL_PCT    = 0.005   # Trailing SL gap  = -0.5% below the highest price seen


def _is_market_hours() -> bool:
    now_ist = datetime.now(IST).time()
    weekday = datetime.now(IST).weekday()
    return weekday < 5 and MARKET_OPEN <= now_ist <= MARKET_CLOSE


async def monitor_open_trades() -> None:
    """
    Every 60s during market hours:
      1. Fetch live price for each open trade.
      2. Update highest_price seen → raise trailing_sl accordingly.
      3. Exit if:
         • price <= hard stop_loss        (SL hit  — -1.5% from entry)
         • price <= trailing_sl           (TSL hit — -0.5% from peak)
         • price >= target_price          (TP hit  — +0.05% initial target)
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

            # Cache live prices (90s TTL)
            for sym, p in prices.items():
                try:
                    await redis.set(f"prices:{sym}", str(p))
                except Exception:
                    pass

            for trade in trades:
                price = prices.get(trade.symbol)
                if price is None:
                    continue

                # ── Update highest price + raise trailing SL ────────────────
                highest = trade.highest_price or trade.entry_price
                if price > highest:
                    highest = price
                    trade.highest_price = round(highest, 2)
                    # Raise trailing SL to (highest − TRAIL_PCT)
                    new_tsl = round(highest * (1 - TRAIL_PCT), 2)
                    # Never lower trailing SL below hard SL
                    hard_sl = round(trade.entry_price * (1 - SL_PCT), 2)
                    trade.trailing_sl = max(new_tsl, hard_sl)
                    await db.commit()

                current_tsl  = trade.trailing_sl or round(trade.entry_price * (1 - TRAIL_PCT), 2)
                current_sl   = trade.stop_loss
                current_tp   = trade.target_price

                # ── Exit conditions ──────────────────────────────────────────
                if price <= current_sl:
                    logger.info("Hard SL hit: %s @ %.2f (SL=%.2f)", trade.symbol, price, current_sl)
                    await close_trade(trade, price, "sl-hit", db, redis)

                elif price <= current_tsl and price > trade.entry_price:
                    # Only trail-stop if price actually moved above entry first
                    logger.info("Trailing SL hit: %s @ %.2f (TSL=%.2f)", trade.symbol, price, current_tsl)
                    await close_trade(trade, price, "trailing-sl-hit", db, redis)

                elif price >= current_tp:
                    logger.info("TP hit: %s @ %.2f (TP=%.2f)", trade.symbol, price, current_tp)
                    await close_trade(trade, price, "target-hit", db, redis)

    except Exception as exc:
        logger.error("monitor_open_trades error: %s", exc)


async def force_exit_all() -> None:
    """FORCE_EXIT_TIME IST — force-exit all remaining open trades at market price."""
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
    """3:30 PM IST — send EOD P&L summary via Telegram."""
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
