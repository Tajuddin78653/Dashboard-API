from datetime import date as date_type
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.core.deps import get_current_user
from app.models.trade import Trade
from app.models.strategy import Strategy

router = APIRouter(tags=["Reports"])


@router.get("/generate")
async def generate_report(
    date_from: date_type | None = Query(None),
    date_to: date_type | None = Query(None),
    strategy: str | None = Query(None),
    report_type: str = Query(default="daily"),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user),
):
    query = select(Trade).where(Trade.status.in_(["target-hit", "sl-hit", "trailing-sl-hit", "exited"]))

    if date_from:
        from sqlalchemy import func
        query = query.where(func.date(Trade.exit_time) >= date_from)
    if date_to:
        from sqlalchemy import func
        query = query.where(func.date(Trade.exit_time) <= date_to)

    # Filter by strategy name if provided
    if strategy and strategy != "all":
        strat_result = await db.execute(
            select(Strategy).where(Strategy.name.ilike(f"%{strategy}%"))
        )
        strat = strat_result.scalar_one_or_none()
        if strat:
            query = query.where(Trade.strategy_id == strat.id)

    result = await db.execute(query.order_by(Trade.exit_time.desc()))
    trades = result.scalars().all()

    total = len(trades)
    winners = sum(1 for t in trades if (t.net_pnl or 0) > 0)
    losers  = sum(1 for t in trades if (t.net_pnl or 0) <= 0)
    net_pnl = round(sum(t.net_pnl or 0 for t in trades), 2)

    return {
        "summary": {
            "total_trades": total,
            "winners": winners,
            "losers": losers,
            "net_pnl": net_pnl,
            "date_from": str(date_from or ""),
            "date_to": str(date_to or ""),
        },
        "trades": [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "signal_type": t.signal_type,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "net_pnl": t.net_pnl,
                "status": t.status,
                "entry_time": str(t.entry_time),
                "exit_time": str(t.exit_time),
            }
            for t in trades
        ],
    }
