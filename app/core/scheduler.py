import logging
from datetime import datetime, time, timezone, timedelta

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

# Risk constants — applied symmetrically for BUY and SELL
SL_PCT = 0.01   # Hard stop loss = 1% from entry
TP_PCT = 0.01   # Take profit    = 1% from entry


def _is_market_hours() -> bool:
    now_ist = datetime.now(IST).time()
    weekday = datetime.now(IST).weekday()
    return weekday < 5 and MARKET_OPEN <= now_ist <= MARKET_CLOSE


async def monitor_open_trades() -> None:
    """
    Every 60s during market hours - fixed exit logic for both BUY and SELL:

    BUY  trade: profit when price rises
      SL  : price <= entry x (1 - 1%)   EXIT "sl-hit"
      TP  : price >= entry x (1 + 1%)   EXIT "target-hit"

    SELL trade: profit when price falls
      SL  : price >= entry x (1 + 1%)   EXIT "sl-hit"
      TP  : price <= entry x (1 - 1%)   EXIT "target-hit"
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
                    logger.warning("No live price for %s - skipping this tick", trade.symbol)
                    continue

                hard_sl  = round(trade.entry_price * (1 - SL_PCT), 2)
                tp_level = round(trade.entry_price * (1 + TP_PCT), 2)

                if trade.signal_type == "SELL":
                    # SELL: SL is above entry, TP is below entry
                    sell_sl = round(trade.entry_price * (1 + SL_PCT), 2)
                    sell_tp = round(trade.entry_price * (1 - TP_PCT), 2)

                    if price >= sell_sl:
                        logger.info("SELL SL hit: %s @ %.2f  SL=%.2f", trade.symbol, price, sell_sl)
                        await close_trade(trade, price, "sl-hit", db, redis)

                    elif price <= sell_tp:
                        logger.info("SELL TP hit: %s @ %.2f  TP=%.2f", trade.symbol, price, sell_tp)
                        await close_trade(trade, price, "target-hit", db, redis)

                else:
                    # BUY: SL is below entry, TP is above entry
                    if price <= hard_sl:
                        logger.info("BUY SL hit: %s @ %.2f  SL=%.2f", trade.symbol, price, hard_sl)
                        await close_trade(trade, price, "sl-hit", db, redis)

                    elif price >= tp_level:
                        logger.info("BUY TP hit: %s @ %.2f  TP=%.2f", trade.symbol, price, tp_level)
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


async def weekly_cleanup() -> None:
    """
    Every Sunday at 11:00 PM IST - wipe all trades + signals for a fresh week.

    Flow:
      1. Force-exit any open trades at current price (safety net)
      2. Delete ALL trades from DB
      3. Delete ALL signals from DB
      4. Clear Redis dedup keys (traded_today:*)
      5. Send Telegram weekly summary + cleanup confirmation
    """
    logger.info("Weekly cleanup starting - wiping all trades and signals...")
    try:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import text
            from app.models.signal import Signal

            # Step 1: Force-exit any open trades first
            result = await db.execute(select(Trade).where(Trade.status == "entered"))
            open_trades = result.scalars().all()
            if open_trades:
                symbols = list({t.symbol for t in open_trades})
                prices  = await get_prices_batch(symbols)
                redis   = await get_redis()
                for trade in open_trades:
                    price = prices.get(trade.symbol, trade.entry_price)
                    await close_trade(trade, price, "weekly-cleanup", db, redis)
                logger.info("Force-exited %d open trades before cleanup", len(open_trades))

            # Step 2: Calculate weekly P&L before deleting
            result_all = await db.execute(select(Trade))
            all_trades = result_all.scalars().all()
            total_trades = len(all_trades)
            winners      = sum(1 for t in all_trades if (t.net_pnl or 0) > 0)
            losers        = total_trades - winners
            weekly_pnl   = sum(t.net_pnl or 0 for t in all_trades)

            # Step 3: Delete all trades
            await db.execute(text("DELETE FROM trades"))
            await db.commit()
            logger.info("Deleted all trades")

            # Step 4: Delete all signals
            await db.execute(text("DELETE FROM signals"))
            await db.commit()
            logger.info("Deleted all signals")

            # Step 5: Clear Redis dedup keys
            try:
                redis = await get_redis()
                for i in range(7):
                    day = (datetime.now(IST) - timedelta(days=i)).strftime("%Y-%m-%d")
                    await redis.delete(f"traded_today:{day}")
                logger.info("Cleared Redis dedup keys")
            except Exception as e:
                logger.warning("Redis cleanup partial: %s", e)

            # Step 6: Send Telegram weekly summary
            try:
                from app.core.telegram import send_message
                week_end = datetime.now(IST).strftime("%d %b %Y")
                msg = (
                    f"\U0001f5d1 <b>Weekly Cleanup - TradeDash</b>\n"
                    f"Week ending: {week_end}\n\n"
                    f"\U0001f4ca <b>Weekly Summary</b>\n"
                    f"  \U0001f3af Total Trades : {total_trades}\n"
                    f"  \u2705 Winners     : {winners}\n"
                    f"  \u274c Losers      : {losers}\n"
                    f"  \U0001f4b0 Net P&amp;L    : \u20b9{weekly_pnl:+.2f}\n\n"
                    f"\U0001f504 <b>Database wiped clean</b>\n"
                    f"  All trades &amp; signals deleted\n"
                    f"  Fresh start from Monday \U0001f680"
                )
                await send_message(msg)
            except Exception as e:
                logger.warning("Weekly cleanup Telegram notification failed: %s", e)

            logger.info(
                "Weekly cleanup done - %d trades deleted, weekly P&L: %.2f",
                total_trades, weekly_pnl
            )

    except Exception as exc:
        logger.error("weekly_cleanup error: %s", exc)


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

    # Weekly cleanup every Sunday at 11:00 PM IST
    # Wipes ALL trades + signals so Monday starts with clean fresh DB
    scheduler.add_job(
        weekly_cleanup, "cron",
        day_of_week="sun",
        hour=23, minute=0,
        id="weekly_cleanup",
    )

    return scheduler