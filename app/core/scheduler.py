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
SL_PCT    = 0.015   # Hard stop loss  = -1.5% from entry  (always active)
TP_PCT    = 0.005   # Initial target  = +0.5% from entry  (phase 1)
TRAIL_PCT = 0.005   # Trailing gap    = -0.5% below peak  (phase 2, after TP hit)


def _is_market_hours() -> bool:
    now_ist = datetime.now(IST).time()
    weekday = datetime.now(IST).weekday()
    return weekday < 5 and MARKET_OPEN <= now_ist <= MARKET_CLOSE


async def monitor_open_trades() -> None:
    """
    Every 60s during market hours - two-phase exit logic:

    PHASE 1  (tp_hit is not True):
       Hard SL    : price <= entry x (1 - 1.5%)   EXIT "sl-hit"
       Initial TP : price >= entry x (1 + 0.5%)   lock profit, enter Phase 2
                    Set tp_hit=True, highest_price=price, trailing_sl=price*(1-0.5%)

    PHASE 2  (tp_hit is True AND trailing_sl is set):
       Price rises  -> update highest_price -> raise trailing_sl to (highest * 0.995)
       Trailing SL  : price <= trailing_sl   EXIT "trailing-sl-hit"  (profit secured)
       Hard SL      : price <= hard_sl        EXIT "sl-hit"           (safety net)

    NOTE: tp_hit is checked with `trade.tp_hit is True` (not `not trade.tp_hit`) to
    correctly handle NULL values that may exist from older rows — NULL must behave
    as Phase 1 (not yet hit TP), never as Phase 2.
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

                # PHASE 1: tp_hit must be explicitly True to be in Phase 2
                # NULL or False both mean Phase 1 (waiting for initial TP)
                if trade.tp_hit is not True:

                    if price <= hard_sl:
                        logger.info("SL hit (Phase 1): %s @ %.2f  SL=%.2f",
                                    trade.symbol, price, hard_sl)
                        await close_trade(trade, price, "sl-hit", db, redis)

                    elif price >= tp_level:
                        # TP touched - lock profit, activate trailing
                        logger.info("TP hit (Phase 1): %s @ %.2f  TP=%.2f - activating trailing",
                                    trade.symbol, price, tp_level)
                        trade.tp_hit        = True
                        trade.highest_price = round(price, 2)
                        trade.trailing_sl   = round(price * (1 - TRAIL_PCT), 2)
                        await db.commit()
                        logger.info("  Trailing SL set to %.2f", trade.trailing_sl)

                # PHASE 2: profit locked, trail behind the peak
                # Extra guard: trailing_sl MUST be set — if somehow NULL, recalculate from highest
                else:
                    highest = trade.highest_price or price

                    # Raise trailing SL as price moves higher
                    if price > highest:
                        highest = round(price, 2)
                        trade.highest_price = highest
                        trade.trailing_sl   = round(highest * (1 - TRAIL_PCT), 2)
                        await db.commit()
                        logger.info("TSL raised: %s  new_peak=%.2f  tsl=%.2f",
                                    trade.symbol, highest, trade.trailing_sl)

                    # Use stored trailing_sl; if NULL for any reason, derive from highest
                    current_tsl = trade.trailing_sl
                    if current_tsl is None:
                        current_tsl = round(highest * (1 - TRAIL_PCT), 2)
                        trade.trailing_sl = current_tsl
                        await db.commit()
                        logger.warning("trailing_sl was NULL in Phase 2 for %s — recalculated to %.2f",
                                       trade.symbol, current_tsl)

                    if price <= current_tsl:
                        logger.info("Trailing SL hit (Phase 2): %s @ %.2f  TSL=%.2f",
                                    trade.symbol, price, current_tsl)
                        await close_trade(trade, price, "trailing-sl-hit", db, redis)

                    elif price <= hard_sl:
                        logger.info("Hard SL hit (Phase 2): %s @ %.2f  SL=%.2f",
                                    trade.symbol, price, hard_sl)
                        await close_trade(trade, price, "sl-hit", db, redis)

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