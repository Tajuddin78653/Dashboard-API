import re
import uuid
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.signal import Signal
from app.models.strategy import Strategy
from app.utils.price import get_price
from app.core.telegram import notify_new_signal


async def parse_webhook_payload(data: dict) -> tuple[list[str], list[str]]:
    """Parse Chartink webhook payload. Returns (symbols, prices).

    Chartink sends stocks as comma-separated values (e.g. "NMDC Steel Ltd,Whirlpool Of India Ltd").
    We split ONLY on commas — never on spaces — so multi-word stock names are preserved.
    The symbol stored is the trimmed stock name as-is (Chartink uses company names, not NSE codes).
    """
    stocks_raw = data.get("stocks", data.get("stock", ""))
    if isinstance(stocks_raw, list):
        symbols = [s.strip() for s in stocks_raw if s.strip()]
    else:
        # Split only on commas — preserve spaces within stock names
        symbols = [s.strip() for s in str(stocks_raw).split(",") if s.strip()]

    prices_raw = data.get("trigger_prices", data.get("trigger_price", ""))
    if isinstance(prices_raw, list):
        prices = [str(p).strip() for p in prices_raw]
    else:
        # Prices are always comma-separated numbers — safe to split on comma
        prices = [p.strip() for p in str(prices_raw).split(",") if p.strip()]

    return symbols, prices


async def generate_signal_id(db: AsyncSession) -> str:
    """Generate SIG-YYYYMMDD-NNN format signal ID."""
    today = date.today()
    result = await db.execute(
        select(func.count(Signal.id)).where(func.date(Signal.timestamp) == today)
    )
    count = (result.scalar() or 0) + 1
    return f"SIG-{today.strftime('%Y%m%d')}-{count:03d}"


async def receive_webhook(
    payload: dict,
    db: AsyncSession,
    redis,
    strategy_name: str = "Chartink Webhook",
) -> dict:
    symbols, prices = await parse_webhook_payload(payload)
    if not symbols:
        return {"status": "error", "message": "No symbols found in payload"}

    # Get strategy
    result = await db.execute(select(Strategy).where(Strategy.name == strategy_name))
    strategy = result.scalar_one_or_none()
    strategy_id = strategy.id if strategy else None

    today_key = f"traded_today:{date.today().isoformat()}"
    results = []

    for i, symbol in enumerate(symbols):
        # Check duplicate via Redis (non-fatal — if Redis is down, allow through)
        try:
            already_traded = await redis.sismember(today_key, symbol)
        except Exception:
            already_traded = False
        if already_traded:
            results.append({"symbol": symbol, "status": "skipped", "reason": "already traded today"})
            continue

        # Get price
        price_str = prices[i] if i < len(prices) else None
        fallback = float(price_str) if price_str else None
        price = await get_price(symbol, fallback)

        # Create signal record
        signal_id_str = await generate_signal_id(db)
        signal = Signal(
            id=uuid.uuid4(),
            signal_id=signal_id_str,
            strategy_id=strategy_id,
            symbol=symbol,
            signal_type="BUY",
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

        # Telegram alert
        await notify_new_signal(
            symbol=symbol,
            signal_type="BUY",
            price=price or 0.0,
            strategy=strategy_name,
            signal_id=signal_id_str,
        )

        results.append({
            "symbol": symbol,
            "status": "signal_created",
            "signal_id": signal_id_str,
            "price": price,
        })

    return {"status": "processed", "results": results}
