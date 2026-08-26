from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date as date_type

from app.database import get_db
from app.core.deps import get_current_user, require_role
from app.core.redis_client import get_redis
from app.models.trade import Trade
from app.schemas.trade import (
    TradeCreate, TradeUpdate, TradeExit,
    TradeResponse, OpenPositionResponse, TradeListResponse,
)
from app.services.trade_service import open_trade, close_trade

router = APIRouter(tags=["Trades"])


@router.get("", response_model=TradeListResponse)
async def list_trades(
    status: str | None = Query(None),
    symbol: str | None = Query(None),
    signal_type: str | None = Query(None),
    date_from: date_type | None = Query(None),
    date_to: date_type | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user),
):
    query = select(Trade).order_by(Trade.entry_time.desc())
    count_query = select(func.count(Trade.id))

    if status:
        query = query.where(Trade.status == status)
        count_query = count_query.where(Trade.status == status)
    if symbol:
        query = query.where(Trade.symbol.ilike(f"%{symbol}%"))
        count_query = count_query.where(Trade.symbol.ilike(f"%{symbol}%"))
    if signal_type:
        query = query.where(Trade.signal_type == signal_type.upper())
        count_query = count_query.where(Trade.signal_type == signal_type.upper())
    if date_from:
        query = query.where(func.date(Trade.entry_time) >= date_from)
        count_query = count_query.where(func.date(Trade.entry_time) >= date_from)
    if date_to:
        query = query.where(func.date(Trade.entry_time) <= date_to)
        count_query = count_query.where(func.date(Trade.entry_time) <= date_to)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    items = result.scalars().all()

    return TradeListResponse(total=total, page=page, page_size=page_size, items=list(items))


@router.get("/open", response_model=list[OpenPositionResponse])
async def get_open_positions(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user),
):
    redis = await get_redis()
    result = await db.execute(select(Trade).where(Trade.status == "entered"))
    trades = result.scalars().all()

    positions = []
    for trade in trades:
        # Try cached price first
        cached = await redis.get(f"prices:{trade.symbol}")
        current_price = float(cached) if cached else None

        mtm = None
        pnl_pct = None
        if current_price is not None:
            mtm = round((current_price - trade.entry_price) * trade.quantity, 2)
            if trade.signal_type == "SELL":
                mtm = -mtm
            capital = trade.entry_price * trade.quantity
            pnl_pct = round((mtm / capital) * 100, 2) if capital else None

        positions.append(OpenPositionResponse(
            trade_id=trade.trade_id,
            symbol=trade.symbol,
            signal_type=trade.signal_type,
            entry_price=trade.entry_price,
            current_price=current_price,
            mtm=mtm,
            pnl_pct=pnl_pct,
            stop_loss=trade.stop_loss,
            target_price=trade.target_price,
            quantity=trade.quantity,
            status=trade.status,
            entry_time=trade.entry_time,
        ))

    return positions


@router.get("/{trade_id}", response_model=TradeResponse)
async def get_trade(
    trade_id: str,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user),
):
    result = await db.execute(select(Trade).where(Trade.trade_id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade


@router.post("", response_model=TradeResponse)
async def create_trade(
    body: TradeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(require_role("trader", "admin")),
):
    redis = await get_redis()
    trade = await open_trade(body.model_dump(), db, redis)
    return trade


@router.put("/{trade_id}/exit", response_model=TradeResponse)
async def exit_trade(
    trade_id: str,
    body: TradeExit,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(require_role("trader", "admin")),
):
    result = await db.execute(select(Trade).where(Trade.trade_id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    if trade.status not in ("entered", "pending"):
        raise HTTPException(status_code=400, detail=f"Cannot exit trade with status: {trade.status}")
    redis = await get_redis()
    return await close_trade(trade, body.exit_price, body.reason, db, redis)


@router.put("/{trade_id}/update", response_model=TradeResponse)
async def update_trade(
    trade_id: str,
    body: TradeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(require_role("trader", "admin")),
):
    result = await db.execute(select(Trade).where(Trade.trade_id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    if body.stop_loss is not None:
        trade.stop_loss = body.stop_loss
    if body.target_price is not None:
        trade.target_price = body.target_price
    await db.commit()
    await db.refresh(trade)
    return trade


@router.delete("/{trade_id}", status_code=204)
async def cancel_trade(
    trade_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(require_role("admin")),
):
    result = await db.execute(select(Trade).where(Trade.trade_id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    if trade.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending trades can be cancelled")
    trade.status = "cancelled"
    await db.commit()
