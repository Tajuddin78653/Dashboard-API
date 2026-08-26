import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def log_action(
    action: str,
    db: AsyncSession,
    details: str | None = None,
    user_id=None,
    ip_address: str | None = None,
) -> None:
    log = AuditLog(
        id=uuid.uuid4(),
        user_id=user_id,
        action=action,
        details=details,
        ip_address=ip_address,
    )
    db.add(log)
    await db.commit()
