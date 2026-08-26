from datetime import date
from calendar import month_abbr

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.trade import Trade
from app.models.signal import Signal
from app.models.strategy import Strategy
from app.schemas.analytics import (
    SummaryStats, StrategyMetrics, MonthlyPnL, EquityCurvePoint,
)


async def get_summary_stats(db: AsyncSession) -> SummaryStats:
    today = date.today()

    total_signals = (await db.execute(select(func.count(Signal.id)))).scalar() or 0
    open_trades = (
        await db.execute(select(func.count(Trade.id)).where(Trade.status == "entered"))
    ).scalar() or 0

    today_pnl_result = await db.execute(
        select(func.sum(Trade.net_pnl)).where(
            Trade.status.in_(["target-hit", "sl-hit", "exited"]),
            func.date(Trade.exit_time) == today,
        )
    )
    today_pnl = float(today_pnl_result.scalar() or 0)

    closed = (
        await db.execute(
            select(Trade).where(Trade.status.in_(["target-hit", "sl-hit", "exited"]))
        )
    ).scalars().all()
    winners = sum(1 for t in closed if (t.net_pnl or 0) > 0)
    win_rate = round(winners / len(closed) * 100, 1) if closed else None

    return SummaryStats(
        total_signals=total_signals,
        open_trades=open_trades,
        today_pnl=today_pnl,
        overall_win_rate=win_rate,
    )


async def get_strategy_metrics(strategy_id, db: AsyncSession) -> StrategyMetrics | None:
    result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
    strategy = result.scalar_one_or_none()
    if not strategy:
        return None

    signals_count = (
        await db.execute(
            select(func.count(Signal.id)).where(Signal.strategy_id == strategy_id)
        )
    ).scalar() or 0

    closed = (
        await db.execute(
            select(Trade).where(
                Trade.strategy_id == strategy_id,
                Trade.status.in_(["target-hit", "sl-hit", "exited"]),
            )
        )
    ).scalars().all()

    total = len(closed)
    winners = [t for t in closed if (t.net_pnl or 0) > 0]
    losers = [t for t in closed if (t.net_pnl or 0) <= 0]
    win_rate = round(len(winners) / total * 100, 1) if total else None

    gross_win = sum(t.net_pnl or 0 for t in winners)
    gross_loss = abs(sum(t.net_pnl or 0 for t in losers))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss else None

    avg_return = None
    if closed:
        returns = [
            ((t.net_pnl or 0) / (t.entry_price * t.quantity)) * 100
            for t in closed
            if t.entry_price and t.quantity
        ]
        avg_return = round(sum(returns) / len(returns), 2) if returns else None

    # Max drawdown from cumulative P&L series
    max_drawdown = None
    if closed:
        sorted_trades = sorted(closed, key=lambda t: t.exit_time or date.today())
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in sorted_trades:
            cumulative += t.net_pnl or 0
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        max_drawdown = round(-max_dd, 2)

    net_pnl = round(sum(t.net_pnl or 0 for t in closed), 2)

    return StrategyMetrics(
        strategy_id=strategy_id,
        strategy_name=strategy.name,
        total_signals=signals_count,
        total_trades=total,
        winners=len(winners),
        losers=len(losers),
        win_rate=win_rate,
        profit_factor=profit_factor,
        avg_return=avg_return,
        max_drawdown=max_drawdown,
        net_pnl=net_pnl,
    )


async def get_monthly_pnl(year: int, db: AsyncSession) -> list[MonthlyPnL]:
    result = await db.execute(
        select(
            func.extract("month", Trade.exit_time).label("month"),
            func.sum(Trade.net_pnl).label("net_pnl"),
        ).where(
            Trade.status.in_(["target-hit", "sl-hit", "exited"]),
            func.extract("year", Trade.exit_time) == year,
        ).group_by(func.extract("month", Trade.exit_time))
        .order_by(func.extract("month", Trade.exit_time))
    )
    rows = result.all()
    monthly: dict[int, float] = {int(r.month): float(r.net_pnl or 0) for r in rows}

    return [
        MonthlyPnL(month=m, month_name=month_abbr[m], net_pnl=monthly.get(m, 0.0))
        for m in range(1, 13)
    ]


async def get_equity_curve(db: AsyncSession) -> list[EquityCurvePoint]:
    result = await db.execute(
        select(Trade).where(
            Trade.status.in_(["target-hit", "sl-hit", "exited"]),
            Trade.exit_time.isnot(None),
        ).order_by(Trade.exit_time)
    )
    trades = result.scalars().all()

    cumulative = 0.0
    points: list[EquityCurvePoint] = []
    seen_dates: dict[str, float] = {}

    for trade in trades:
        cumulative += trade.net_pnl or 0
        date_str = trade.exit_time.strftime("%Y-%m-%d")  # type: ignore[union-attr]
        seen_dates[date_str] = round(cumulative, 2)

    for d, val in seen_dates.items():
        points.append(EquityCurvePoint(date=d, cumulative_pnl=val))

    return points
