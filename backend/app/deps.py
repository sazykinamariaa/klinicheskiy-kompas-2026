"""Зависимости API: сессия БД, конфигурация, текущий пользователь, проверка ролей и доступа к пациенту."""
from __future__ import annotations

from datetime import timedelta
from typing import Callable, Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit, clock, db as DB, models as M
from .config_loader import Config, load_config
from .security import token_hash

_cfg: Optional[Config] = None
TOKEN_TTL_HOURS = 12


def get_cfg() -> Config:
    global _cfg
    if _cfg is None:
        _cfg = reload_config()
    return _cfg


def reload_config(path=None) -> Config:
    """Загрузить конфигурацию (две фазы: каталог фактов нужен проверке исполнимости правил)."""
    global _cfg
    from . import facts as F, alerts_service
    first = load_config(path, strict=False)
    cfg = load_config(path, known_facts=F.fact_catalog(first), strict=True)
    cfg.errors = []
    _cfg = cfg
    alerts_service.set_text_config(cfg)
    return cfg


def set_cfg(cfg: Config) -> None:
    global _cfg
    from . import alerts_service
    _cfg = cfg
    alerts_service.set_text_config(cfg)


def get_db():
    s = DB.Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def current_user(authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db, scope="function")) -> M.User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "нужна авторизация")
    th = token_hash(authorization.split(None, 1)[1])
    tok = db.execute(select(M.Token).where(M.Token.token_hash == th)).scalar_one_or_none()
    if tok is None or tok.expires_at < clock.now():
        raise HTTPException(401, "сессия недействительна или истекла")
    user = db.get(M.User, tok.user_id)
    if not user or not user.active:
        raise HTTPException(401, "пользователь отключён")
    return user


def require_roles(*roles: str) -> Callable:
    def dep(user: M.User = Depends(current_user)) -> M.User:
        if user.role not in roles:
            raise HTTPException(403, "недостаточно прав для роли «%s»" % user.role)
        return user
    return dep


def patient_for_doctor(patient_id: int, user: M.User = Depends(require_roles("doctor")), db: Session = Depends(get_db, scope="function")) -> M.Patient:
    p = db.get(M.Patient, patient_id)
    if p is None or p.doctor_id != user.id:
        raise HTTPException(404, "пациент не найден среди ваших пациентов")
    audit.log(db, user, "patient.view", "patient", p.id, p.id)
    return p


def own_patient(user: M.User = Depends(require_roles("patient")), db: Session = Depends(get_db, scope="function")) -> M.Patient:
    p = db.execute(select(M.Patient).where(M.Patient.user_id == user.id)).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, "карточка пациента не найдена")
    c = db.execute(select(M.Consent).where(M.Consent.patient_id == p.id, M.Consent.revoked_at.is_(None))).first()
    if c is None:
        raise HTTPException(403, "до принятия согласия на обработку персональных данных данные не вводятся")
    return p
