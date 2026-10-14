import logging
import re
import uuid
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.signal import Signal
from app.models.strategy import Strategy
from app.utils.price import get_price
from app.core.telegram import notify_new_signal
from app.config import settings


async def parse_webhook_payload(data: dict) -> tuple[list[str], list[str], str]:
    """Parse Chartink webhook payload. Returns (symbols, prices, signal_type).

    Chartink sends stocks as comma-separated values (e.g. "NMDC Steel Ltd,Whirlpool Of India Ltd").
    We split ONLY on commas - never on spaces - so multi-word stock names are preserved.
    The symbol stored is the trimmed stock name as-is (Chartink uses company names, not NSE codes).

    Signal type detection via scan_name convention:
      scan_name contains "BUL" → BUY  (e.g. "Tazbul09151115")
      scan_name contains "SEL" → SELL (e.g. "Tazsel09151115")
      anything else             → BUY  (safe default)
    """
    stocks_raw = data.get("stocks", data.get("stock", ""))
    if isinstance(stocks_raw, list):
        symbols = [s.strip() for s in stocks_raw if s.strip()]
    else:
        # Split only on commas - preserve spaces within stock names
        symbols = [s.strip() for s in str(stocks_raw).split(",") if s.strip()]

    prices_raw = data.get("trigger_prices", data.get("trigger_price", ""))
    if isinstance(prices_raw, list):
        prices = [str(p).strip() for p in prices_raw]
    else:
        # Prices are always comma-separated numbers - safe to split on comma
        prices = [p.strip() for p in str(prices_raw).split(",") if p.strip()]

    # Detect signal type from scan_name
    scan_name = str(data.get("scan_name", "")).upper()
    if "SEL" in scan_name:
        signal_type = "SELL"
    else:
        signal_type = "BUY"  # BUL match or safe default

    return symbols, prices, signal_type


async def generate_signal_id(db: AsyncSession) -> str:
    """Generate SIG-YYYYMMDD-NNN format signal ID - unique even within a batch."""
    import random
    today = date.today()
    prefix = f"SIG-{today.strftime('%Y%m%d')}"
    # Keep trying until we find an unused ID
    for _ in range(20):
        result = await db.execute(
            select(func.count(Signal.id)).where(func.date(Signal.timestamp) == today)
        )
        count = (result.scalar() or 0) + 1
        candidate = f"{prefix}-{count:03d}"
        # Check it doesn't already exist
        exists = await db.execute(select(Signal.id).where(Signal.signal_id == candidate))
        if exists.scalar_one_or_none() is None:
            return candidate
        # If exists, bump by a random offset to avoid tight loops
        await db.execute(select(func.count(Signal.id)))  # no-op flush
    # Fallback: use timestamp-based unique suffix
    import time
    return f"{prefix}-{int(time.time() % 100000):05d}"


async def receive_webhook(
    payload: dict,
    db: AsyncSession,
    redis,
    strategy_name: str = "Chartink Webhook",
) -> dict:
    symbols, prices, signal_type = await parse_webhook_payload(payload)
    if not symbols:
        return {"status": "error", "message": "No symbols found in payload"}

    logger.info("Webhook received: %d symbols, signal_type=%s, scan_name=%s",
                len(symbols), signal_type, payload.get("scan_name", ""))

    # Get strategy
    result = await db.execute(select(Strategy).where(Strategy.name == strategy_name))
    strategy = result.scalar_one_or_none()
    strategy_id = strategy.id if strategy else None

    today_key = f"traded_today:{date.today().isoformat()}"
    results = []

    for i, symbol in enumerate(symbols):
        # Check duplicate via Redis - blocks same symbol regardless of BUY/SELL direction
        try:
            already_traded = await redis.sismember(today_key, symbol)
        except Exception:
            already_traded = False
        if already_traded:
            results.append({"symbol": symbol, "status": "skipped", "reason": "already traded today"})
            continue

        # Get price - use Chartink trigger price as fallback only; never use previous_close
        price_str = prices[i] if i < len(prices) else None
        fallback = float(price_str) if price_str else None
        price = await get_price(symbol, fallback)

        # Capital guard: skip stocks we cannot buy even 1 share of with our capital
        if price and price > settings.CAPITAL_PER_TRADE:
            results.append({
                "symbol": symbol,
                "status": "skipped",
                "reason": f"price {price:.2f} exceeds capital {settings.CAPITAL_PER_TRADE}",
            })
            continue

        # Min-profit guard: skip stocks where gross profit at TP (1%) < Rs.20
        if price and price > 0:
            _qty = max(1, int(settings.CAPITAL_PER_TRADE / price))
            _gross_at_tp = round(_qty * price * 0.01, 2)
            if _gross_at_tp < 20:
                logger.info("Min-profit guard: skipping %s - gross at TP=%.2f < Rs.20", symbol, _gross_at_tp)
                results.append({
                    "symbol": symbol,
                    "status": "skipped",
                    "reason": f"gross at TP too low: Rs.{_gross_at_tp} (min Rs.20)",
                })
                continue

        # SL / TP depend on direction
        # BUY:  profit when price rises  → SL below entry, TP above entry
        # SELL: profit when price falls  → SL above entry, TP below entry
        if signal_type == "SELL":
            stop_loss    = round(price * 1.01, 2)  # +1% above entry
            target_price = round(price * 0.99, 2)  # -1% below entry
        else:
            stop_loss    = round(price * 0.99, 2)  # -1% below entry
            target_price = round(price * 1.01, 2)  # +1% above entry

        # Create signal record
        signal_id_str = await generate_signal_id(db)
        signal = Signal(
            id=uuid.uuid4(),
            signal_id=signal_id_str,
            strategy_id=strategy_id,
            symbol=symbol,
            signal_type=signal_type,
            entry_price=price,
            status="pending",
            raw_payload=payload,
        )
        db.add(signal)

        # Mark traded today in Redis, expire at midnight (non-fatal)
        try:
            await redis.sadd(today_key, symbol)
            now = datetime.now(timezone.utc)
            midnight = now.replace(hour=23, minute=59, second=59)
            await redis.expireat(today_key, int(midnight.timestamp()))
        except Exception:
            pass

        await db.commit()
        await db.refresh(signal)

        # Telegram alert for the signal
        await notify_new_signal(
            symbol=symbol,
            signal_type=signal_type,
            price=price or 0.0,
            strategy=strategy_name,
            signal_id=signal_id_str,
        )

        # Auto-create trade (paper trading) via open_trade() to keep Redis cache in sync
        trade_result = None
        if price and price > 0:
            try:
                from app.services.trade_service import open_trade

                capital = settings.CAPITAL_PER_TRADE
                quantity = max(1, int(capital / price))

                trade = await open_trade(
                    data={
                        "signal_id": signal.id,
                        "strategy_id": strategy_id,
                        "symbol": symbol,
                        "signal_type": signal_type,
                        "entry_price": price,
                        "stop_loss": stop_loss,
                        "target_price": target_price,
                        "quantity": quantity,
                    },
                    db=db,
                    redis=redis,
                )
                # Mark signal as entered
                signal.status = "entered"
                await db.commit()

                trade_result = {
                    "trade_id": trade.trade_id,
                    "quantity": quantity,
                    "entry_price": price,
                    "stop_loss": stop_loss,
                    "target_price": target_price,
                    "capital_deployed": round(price * quantity, 2),
                }
            except Exception as e:
                trade_result = {"error": str(e)}

        results.append({
            "symbol": symbol,
            "status": "signal_created",
            "signal_id": signal_id_str,
            "signal_type": signal_type,
            "price": price,
            "trade": trade_result,
        })

    return {"status": "processed", "results": results}