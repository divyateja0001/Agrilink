from __future__ import annotations

from . import _typing  # noqa: F401
from ..models import AuditEvent


def record_audit(db, action, entity_type, entity_id=None, *, actor=None, organization_id=None, details=None):
    db.add(
        AuditEvent(
            actor_user_id=getattr(actor, "id", actor),
            organization_id=organization_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )

