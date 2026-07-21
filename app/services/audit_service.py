from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.repositories.audit_repository import AuditRepository

audit_repository = AuditRepository()


async def log_event(
    db: AsyncSession,
    *,
    user_id: int | None,
    action: str,
    resource: str,
    resource_id: int | None,
    request: Request,
) -> None:
    audit_repository.create(
        db,
        AuditLog(
            user_id=user_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        ),
    )
    await db.commit()
