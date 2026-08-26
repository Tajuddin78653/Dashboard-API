import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.core.deps import get_current_user, require_role
from app.models.strategy import Strategy
from app.schemas.analytics import StrategyCreate, StrategyUpdate, StrategyResponse

router = APIRouter(tags=["Strategies"])

DEFAULT_STRATEGIES = [
    {"name": "13/50 EMA", "description": "EMA crossover strategy for trend following"},
    {"name": "Gap D/U", "description": "Gap up/down breakout strategy"},
    {"name": "ST+ADX", "description": "Supertrend combined with ADX strength filter"},
    {"name": "Pro Engine", "description": "Multi-factor momentum strategy"},
    {"name": "Chartink Webhook", "description": "Direct Chartink webhook signals (Bot 1)"},
    {"name": "Chartink Webhook 2", "description": "Direct Chartink webhook signals (Bot 2)"},
]


async def seed_strategies(db: AsyncSession) -> None:
    for strat in DEFAULT_STRATEGIES:
        result = await db.execute(select(Strategy).where(Strategy.name == strat["name"]))
        if not result.scalar_one_or_none():
            db.add(Strategy(id=uuid.uuid4(), **strat))
    await db.commit()


@router.get("", response_model=list[StrategyResponse])
async def list_strategies(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(get_current_user),
):
    result = await db.execute(select(Strategy).order_by(Strategy.name))
    return result.scalars().all()


@router.post("", response_model=StrategyResponse)
async def create_strategy(
    body: StrategyCreate,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_role("admin")),
):
    strategy = Strategy(id=uuid.uuid4(), **body.model_dump())
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    return strategy


@router.put("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: str,
    body: StrategyUpdate,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_role("admin")),
):
    result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    for field, val in body.model_dump(exclude_none=True).items():
        setattr(strategy, field, val)
    await db.commit()
    await db.refresh(strategy)
    return strategy


@router.delete("/{strategy_id}", status_code=204)
async def delete_strategy(
    strategy_id: str,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_role("admin")),
):
    result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    await db.delete(strategy)
    await db.commit()
