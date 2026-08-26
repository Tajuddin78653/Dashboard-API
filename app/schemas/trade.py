from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime


class TradeCreate(BaseModel):
    signal_id: UUID | None = None
    symbol: str
    signal_type: str = "BUY"
    entry_price: float
    stop_loss: float
    target_price: float
    quantity: int
    strategy_id: UUID | None = None


class TradeUpdate(BaseModel):
    stop_loss: float | None = None
    target_price: float | None = None


class TradeExit(BaseModel):
    exit_price: float
    reason: str = "manual-exit"  # manual-exit / target-hit / sl-hit / force-exit-eod


class TradeResponse(BaseModel):
    id: UUID
    trade_id: str
    symbol: str
    signal_type: str
    entry_price: float
    exit_price: float | None = None
    stop_loss: float
    target_price: float
    quantity: int
    gross_pnl: float | None = None
    charges: float | None = None
    net_pnl: float | None = None
    status: str
    reason: str | None = None
    entry_time: datetime
    exit_time: datetime | None = None
    strategy_id: UUID | None = None
    signal_id: UUID | None = None
    model_config = ConfigDict(from_attributes=True)


class OpenPositionResponse(BaseModel):
    trade_id: str
    symbol: str
    signal_type: str
    entry_price: float
    current_price: float | None = None
    mtm: float | None = None
    pnl_pct: float | None = None
    stop_loss: float
    target_price: float
    quantity: int
    status: str
    entry_time: datetime
    model_config = ConfigDict(from_attributes=True)


class TradeListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[TradeResponse]
