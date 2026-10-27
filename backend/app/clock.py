"""Единые «часы» приложения: в тестах время подменяется, в рабочем режиме это UTC."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

_override: Optional[datetime] = None


def now() -> datetime:
    """Текущее время UTC (наивное)."""
    return _override if _override is not None else datetime.utcnow()


def set_now(dt: Optional[datetime]) -> None:
    global _override
    _override = dt


def advance(**kw) -> datetime:
    global _override
    _override = (_override or datetime.utcnow()) + timedelta(**kw)
    return _override
