from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from datetime import date as date_type

from app.database import get_db
from app.core.deps import get_current_user, require_role
from app.models.signal import Signal
from app.models.strategy import Strategy
from app.schemas.signal import SignalResponse, SignalListResponse

router = APIRouter(tags=["Signals"])


def _enrich(signal: Signal, strategy_map: dict) -> dict:
    """Add strategy_name to signal dict for response."""
    d = {
        "id": signal.id,
        "signal_id": signal.signal_id,
        "symbol": signal.symbol,
        "signal_type": signal.signal_type,
        "entry_price": signal.entry_price,
        "status": signal.status,
        "timestamp": signal.timestamp,
        "strategy_id": signal.strategy_id,
        "strategy_name": strategy_map.get(str(signal.strategy_id)) if signal.strategy_id else None,
    }
    return d


@router.get("", response_model=SignalListResponse)
async def list_signals(
    symbol: str | None = Query(None),
    status: str | None = Query(None),
    signal_type: str | None = Query(None),
    date_from: date_type | None = Query(None),
    date_to: date_type | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user),
):
    query = select(Signal).order_by(Signal.timestamp.desc())
    count_query = select(func.count(Signal.id))

    if symbol:
        query = query.where(Signal.symbol.ilike(f"%{symbol}%"))
        count_query = count_query.where(Signal.symbol.ilike(f"%{symbol}%"))
    if status:
        query = query.where(Signal.status == status)
        count_query = count_query.where(Signal.status == status)
    if signal_type:
        query = query.where(Signal.signal_type == signal_type.upper())
        count_query = count_query.where(Signal.signal_type == signal_type.upper())
    if date_from:
        query = query.where(func.date(Signal.timestamp) >= date_from)
        count_query = count_query.where(func.date(Signal.timestamp) >= date_from)
    if date_to:
        query = query.where(func.date(Signal.timestamp) <= date_to)
        count_query = count_query.where(func.date(Signal.timestamp) <= date_to)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    result = await db.execute(query.offset(offset).limit(page_size))
    items = result.scalars().all()

    # Build strategy name map for enrichment
    strategy_ids = list({str(s.strategy_id) for s in items if s.strategy_id})
    strategy_map: dict = {}
    if strategy_ids:
        strat_result = await db.execute(select(Strategy))
        for strat in strat_result.scalars().all():
            strategy_map[str(strat.id)] = strat.name

    enriched = [_enrich(s, strategy_map) for s in items]
    return SignalListResponse(total=total, page=page, page_size=page_size, items=enriched)


@router.delete("/cleanup", status_code=200)
async def cleanup_test_signals(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_role("admin")),
):
    """Delete signals with test/garbage symbols (admin only)."""
    test_symbols = ["SYMBOL", "SYMBOL 1", "SYMBOL 2", "SYMBOL 3", "1", "2", "3",
                    "STEEL", "NMDC", "LTD", "OF", "INDIA", "WHIRLPOOL"]
    deleted = 0
    for sym in test_symbols:
        r = await db.execute(delete(Signal).where(Signal.symbol == sym))
        deleted += r.rowcount
    await db.commit()
    return {"status": "ok", "deleted": deleted}


@router.get("/{signal_id}", response_model=SignalResponse)
async def get_signal(
    signal_id: str,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user),
):
    result = await db.execute(select(Signal).where(Signal.signal_id == signal_id))
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    # Enrich with strategy name
    strategy_map: dict = {}
    if signal.strategy_id:
        strat_r = await db.execute(select(Strategy).where(Strategy.id == signal.strategy_id))
        strat = strat_r.scalar_one_or_none()
        if strat:
            strategy_map[str(signal.strategy_id)] = strat.name
    return _enrich(signal, strategy_map)
