import uuid
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.trade import Trade
from app.models.signal import Signal
from app.utils.charges import calc_charges
from app.core.telegram import notify_trade_entry, notify_trade_exit


async def generate_trade_id(db: AsyncSession) -> str:
    """Generate TRD-YYYYMMDD-NNN format trade ID."""
    today = date.today()
    result = await db.execute(
        select(func.count(Trade.id)).where(func.date(Trade.entry_time) == today)
    )
    count = (result.scalar() or 0) + 1
    return f"TRD-{today.strftime('%Y%m%d')}-{count:03d}"


async def open_trade(data: dict, db: AsyncSession, redis) -> Trade:
    """Create a new trade record and notify via Telegram."""
    trade_id = await generate_trade_id(db)
    trade = Trade(
        id=uuid.uuid4(),
        trade_id=trade_id,
        signal_id=data.get("signal_id"),
        strategy_id=data.get("strategy_id"),
        symbol=data["symbol"],
        signal_type=data.get("signal_type", "BUY"),
        entry_price=data["entry_price"],
        stop_loss=data["stop_loss"],
        target_price=data["target_price"],
        quantity=data["quantity"],
        status="entered",
    )
    db.add(trade)

    # Update linked signal status to entered
    if data.get("signal_id"):
        result = await db.execute(select(Signal).where(Signal.id == data["signal_id"]))
        signal = result.scalar_one_or_none()
        if signal:
            signal.status = "entered"

    await db.commit()
    await db.refresh(trade)

    # Cache open trade fields in Redis
    capital = data["entry_price"] * data["quantity"]
    await redis.hset(
        f"open_trade:{trade_id}",
        mapping={
            "symbol": data["symbol"],
            "entry_price": str(data["entry_price"]),
            "stop_loss": str(data["stop_loss"]),
            "target_price": str(data["target_price"]),
            "quantity": str(data["quantity"]),
            "signal_type": data.get("signal_type", "BUY"),
        },
    )

    await notify_trade_entry(
        trade_id=trade_id,
        symbol=data["symbol"],
        entry=data["entry_price"],
        qty=data["quantity"],
        sl=data["stop_loss"],
        tp=data["target_price"],
        capital=capital,
    )

    return trade


async def close_trade(trade: Trade, exit_price: float, reason: str, db: AsyncSession, redis) -> Trade:
    """Close a trade, compute P&L, notify, and remove from Redis cache."""
    gross_pnl = (exit_price - trade.entry_price) * trade.quantity
    if trade.signal_type == "SELL":
        gross_pnl = -gross_pnl
    charges = calc_charges(trade.entry_price, exit_price, trade.quantity)
    net_pnl = round(gross_pnl - charges, 2)

    status_map = {
        "target-hit": "target-hit",
        "sl-hit": "sl-hit",
        "force-exit-eod": "exited",
        "manual-exit": "exited",
    }

    trade.exit_price = exit_price
    trade.gross_pnl = round(gross_pnl, 2)
    trade.charges = charges
    trade.net_pnl = net_pnl
    trade.status = status_map.get(reason, "exited")
    trade.reason = reason
    trade.exit_time = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(trade)

    # Remove from Redis
    await redis.delete(f"open_trade:{trade.trade_id}")

    await notify_trade_exit(
        trade_id=trade.trade_id,
        symbol=trade.symbol,
        entry=trade.entry_price,
        exit_p=exit_price,
        net_pnl=net_pnl,
        reason=reason,
    )

    return trade
