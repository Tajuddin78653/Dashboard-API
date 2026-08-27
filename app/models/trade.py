import uuid
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trade_id: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True
    )
    signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signals.id"), nullable=True
    )
    strategy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id"), nullable=True
    )
    symbol: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="BUY"
    )
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    trailing_sl: Mapped[float] = mapped_column(Float, nullable=True)    # trailing stop level (active after TP hit)
    highest_price: Mapped[float] = mapped_column(Float, nullable=True)  # highest price seen since TP hit
    target_price: Mapped[float] = mapped_column(Float, nullable=False)
    tp_hit: Mapped[bool] = mapped_column(Boolean(), nullable=True, default=False)  # True once initial TP is touched
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    gross_pnl: Mapped[float] = mapped_column(Float, nullable=True)
    charges: Mapped[float] = mapped_column(Float, nullable=True)
    net_pnl: Mapped[float] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="entered"
    )
    reason: Mapped[str] = mapped_column(String(100), nullable=True)
    entry_time: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    exit_time: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
