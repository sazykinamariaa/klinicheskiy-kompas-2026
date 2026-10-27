"""Журнал аудита: кто, когда, что смотрел и менял. Запись делается в той же транзакции, что и действие."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from . import models as M


def log(db: Session, actor: Optional[M.User], action: str, entity: str = None, entity_id: Any = None,
        patient_id: Optional[int] = None, **detail: Any) -> None:
    db.add(M.AuditLog(
        actor_id=actor.id if actor else None,
        actor_role=actor.role if actor else "system",
        action=action, entity=entity, entity_id=str(entity_id) if entity_id is not None else None,
        patient_id=patient_id, detail=detail,
    ))
