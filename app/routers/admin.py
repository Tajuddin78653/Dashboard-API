from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.deps import require_role
from app.core.telegram import send_message
from app.config import settings
from app.database import get_db
from app.models.strategy import Strategy

router = APIRouter(tags=["Admin"])

BASE_URL = "https://trading-dashboard-api-zmho.onrender.com"


@router.get("/config")
async def get_config(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_role("admin")),
):
    # Fetch webhook tokens for the two Chartink strategies
    result = await db.execute(
        select(Strategy).where(
            Strategy.name.in_(["Chartink Webhook", "Chartink Webhook 2"])
        )
    )
    strategies = {s.name: s for s in result.scalars().all()}

    def webhook_url(name: str, legacy_path: str) -> str:
        """Return the secure UUID URL if token exists, else the legacy path."""
        s = strategies.get(name)
        if s and s.webhook_token:
            return f"{BASE_URL}/webhook/chartink/{s.webhook_token}"
        return f"{BASE_URL}{legacy_path}"

    return {
        # Secure token-based URLs (shown in Admin page for copy-paste into Chartink)
        "webhook_url_bot1": webhook_url("Chartink Webhook", "/webhook/chartink"),
        "webhook_url_bot2": webhook_url("Chartink Webhook 2", "/webhook/chartink2"),
        # Token values separately (so Admin UI can show/hide them)
        "webhook_token_bot1": strategies.get("Chartink Webhook", None) and strategies["Chartink Webhook"].webhook_token,
        "webhook_token_bot2": strategies.get("Chartink Webhook 2", None) and strategies["Chartink Webhook 2"].webhook_token,
        # Other config
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
