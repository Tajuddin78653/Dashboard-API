from fastapi import APIRouter, Depends
from app.core.deps import require_role
from app.core.telegram import send_message
from app.config import settings

router = APIRouter(tags=["Admin"])


@router.get("/config")
async def get_config(_: object = Depends(require_role("admin"))):
    return {
        "webhook_url_bot1": "/webhook/chartink",
        "webhook_url_bot2": "/webhook/chartink2",
        "paper_trading": settings.PAPER_TRADING,
        "capital_per_trade": settings.CAPITAL_PER_TRADE,
        "force_exit_time": settings.FORCE_EXIT_TIME,
        "telegram_bot1_configured": bool(settings.BOT_TOKEN and settings.CHAT_ID),
        "telegram_bot2_configured": bool(settings.BOT2_TOKEN and settings.BOT2_CHAT_ID),
    }


@router.post("/telegram/test")
async def test_telegram(_: object = Depends(require_role("admin"))):
    await send_message("✅ <b>TradeDash</b> — Telegram test message successful!")
    return {"status": "sent"}
