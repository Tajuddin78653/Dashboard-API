from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date as date_type

from app.database import get_db
from app.core.deps import require_role
from app.models.audit_log import AuditLog

router = APIRouter(tags=["Audit"])


@router.get("")
async def list_audit_logs(
    action: str | None = Query(None),
    date_from: date_type | None = Query(None),
    date_to: date_type | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_role("admin")),
):
    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    count_query = select(func.count(AuditLog.id))

    if action and action != "all":
        query = query.where(AuditLog.action == action.upper())
        count_query = count_query.where(AuditLog.action == action.upper())
    if date_from:
        query = query.where(func.date(AuditLog.created_at) >= date_from)
        count_query = count_query.where(func.date(AuditLog.created_at) >= date_from)
    if date_to:
        query = query.where(func.date(AuditLog.created_at) <= date_to)
        count_query = count_query.where(func.date(AuditLog.created_at) <= date_to)

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    items = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": str(log.id),
                "user_id": str(log.user_id) if log.user_id else None,
                "action": log.action,
                "details": log.details,
                "ip_address": log.ip_address,
                "created_at": str(log.created_at),
            }
            for log in items
        ],
    }
