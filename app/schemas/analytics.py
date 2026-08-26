from pydantic import BaseModel, ConfigDict
from uuid import UUID
from datetime import datetime


class StrategyCreate(BaseModel):
    name: str
    description: str | None = None
    is_active: bool = True


class StrategyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class StrategyResponse(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    is_active: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class StrategyMetrics(BaseModel):
    strategy_id: UUID
    strategy_name: str
    total_signals: int
    total_trades: int
    winners: int
    losers: int
    win_rate: float | None
    profit_factor: float | None
    avg_return: float | None
    max_drawdown: float | None
    net_pnl: float


class SummaryStats(BaseModel):
    total_signals: int
    open_trades: int
    today_pnl: float
    overall_win_rate: float | None


class MonthlyPnL(BaseModel):
    month: int
    month_name: str
    net_pnl: float


class EquityCurvePoint(BaseModel):
    date: str
    cumulative_pnl: float


class ReportData(BaseModel):
    summary: dict
    trades: list[dict]
