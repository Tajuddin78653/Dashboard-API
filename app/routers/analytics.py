from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.core.deps import get_current_user
from app.models.trade import Trade
from app.models.strategy import Strategy
from app.services.analytics_service import (
    get_summary_stats, get_strategy_metrics,
    get_monthly_pnl, get_equity_curve,
)
from app.schemas.analytics import (
    SummaryStats, StrategyMetrics, MonthlyPnL, EquityCurvePoint, StrategyResponse,
)

router = APIRouter(tags=["Analytics"])


@router.get("/summary", response_model=SummaryStats)
async def summary(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user),
):
    return await get_summary_stats(db)


@router.get("/strategies", response_model=list[StrategyMetrics])
async def all_strategy_metrics(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user),
):
    result = await db.execute(select(Strategy))
    strategies = result.scalars().all()
    metrics = []
    for s in strategies:
        m = await get_strategy_metrics(s.id, db)
        if m:
            metrics.append(m)
    return metrics


@router.get("/strategies/{strategy_id}", response_model=StrategyMetrics)
async def single_strategy_metrics(
    strategy_id: str,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user),
):
    from fastapi import HTTPException
    m = await get_strategy_metrics(strategy_id, db)
    if not m:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return m


@router.get("/monthly-pnl", response_model=list[MonthlyPnL])
async def monthly_pnl(
    year: int = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user),
):
    from datetime import date
    y = year or date.today().year
    return await get_monthly_pnl(y, db)


@router.get("/equity-curve", response_model=list[EquityCurvePoint])
async def equity_curve(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user),
):
    return await get_equity_curve(db)
