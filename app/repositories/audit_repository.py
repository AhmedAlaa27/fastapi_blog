from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditLog]):
    model = AuditLog

    def create(self, db: AsyncSession, audit_log: AuditLog) -> AuditLog:
        db.add(audit_log)
        return audit_log
