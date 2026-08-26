from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime


class SignalResponse(BaseModel):
    id: UUID
    signal_id: str
    symbol: str
    signal_type: str
    entry_price: float | None = None
    status: str
    timestamp: datetime
    strategy_id: UUID | None = None
    model_config = ConfigDict(from_attributes=True)


class SignalListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[SignalResponse]
