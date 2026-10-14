import logging
from fastapi import APIRouter, Depends
from app.core.deps import get_current_user
from app.services.ema_scanner import run_ema_scanner

router = APIRouter(tags=["Scanner"])
logger = logging.getLogger(__name__)


@router.post("/run")
async def run_scanner(
    _: object = Depends(get_current_user),
):
    """
    Trigger EMA 13/50 strict crossover scan on all ~180 F&O stocks.
    Runs on demand - works both during and outside market hours.
    Returns triggered BUY/SELL stocks + market trend (A/D ratio).
    Takes ~30-60s to complete (180 yfinance calls in parallel).
    """
    logger.info("EMA scanner triggered manually")
    result = await run_ema_scanner()
    logger.info(
        "EMA scan done: %d BUY, %d SELL, trend=%s",
        result["buy_count"], result["sell_count"], result["market_trend"]
    )
    return result