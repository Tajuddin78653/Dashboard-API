import logging
from fastapi import APIRouter, Depends
from app.core.deps import get_current_user
from app.services.ema_scanner import run_ema_scanner, get_cached_scan

router = APIRouter(tags=["Scanner"])
logger = logging.getLogger(__name__)


@router.get("/latest")
async def get_latest_scan(
    _: object = Depends(get_current_user),
):
    """
    Return the most recent cached EMA scan result from Redis.
    Returns null if no scan has run yet (scheduler hasn't fired or cache expired).
    Fast — just reads Redis, no yfinance calls.
    """
    result = await get_cached_scan()
    return result  # null = no cache yet


@router.post("/run")
async def run_scanner(
    _: object = Depends(get_current_user),
):
    """
    Manually trigger EMA 13/50 strict crossover scan on all ~180 F&O stocks.
    Use during off-market hours. Result is also cached to Redis.
    Takes ~30-60s (180 yfinance calls in parallel).
    """
    logger.info("EMA scanner triggered manually")
    result = await run_ema_scanner()
    logger.info(
        "EMA scan done: %d BUY, %d SELL, trend=%s",
        result["buy_count"], result["sell_count"], result["market_trend"]
    )
    return result