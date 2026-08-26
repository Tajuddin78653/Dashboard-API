from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from urllib.parse import parse_qs

from app.database import get_db
from app.core.redis_client import get_redis
from app.services.signal_service import receive_webhook

router = APIRouter(tags=["Webhook"])


async def parse_request_data(request: Request) -> dict:
    """Accept Chartink payload as JSON, form-data, or URL-encoded body."""
    # Try JSON
    try:
        data = await request.json()
        if data:
            return data
    except Exception:
        pass
    # Try form data
    try:
        form = await request.form()
        if form:
            return dict(form)
    except Exception:
        pass
    # Try URL-encoded body
    try:
        body = await request.body()
        parsed = parse_qs(body.decode("utf-8"))
        return {k: v[0] for k, v in parsed.items()}
    except Exception:
        pass
    return {}


@router.post("/webhook/chartink")
async def chartink_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    data = await parse_request_data(request)
    redis = await get_redis()
    return await receive_webhook(data, db, redis, strategy_name="Chartink Webhook")


@router.post("/webhook/chartink2")
async def chartink_webhook2(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    data = await parse_request_data(request)
    redis = await get_redis()
    return await receive_webhook(data, db, redis, strategy_name="Chartink Webhook 2")
