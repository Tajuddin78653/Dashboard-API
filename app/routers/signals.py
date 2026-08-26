from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date as date_type

from app.database import get_db
from app.core.deps import get_current_user
from app.models.signal import Signal
from app.schemas.signal import SignalResponse, SignalListResponse

router = APIRouter(tags=["Signals"])


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
    query = query.offset(offset).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()

    return SignalListResponse(total=total, page=page, page_size=page_size, items=list(items))


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
    return signal
