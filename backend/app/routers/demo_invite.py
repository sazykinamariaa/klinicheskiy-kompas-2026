"""Демо-сценарий: новый пациент получил ссылку-приглашение и впервые регистрируется в браузере.

Без телефона, SMS, звонков и внешних сервисов. Ссылка с заранее заданным тестовым токеном: /invite/DEMO-2026.
Пациент создаётся только после регистрации — с пустой историей (без диагнозов, приёмов и назначений) и статусом «new».
Повторное открытие ссылки показывает «ссылка уже использована»; сброс демо: кнопка на этом экране или /invite/DEMO-2026?reset=1.
Отключить сценарий: KK_DEMO_INVITE=0.
"""
from __future__ import annotations

import os
import re
from datetime import date, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit, clock, models as M
from ..config_loader import Config
from ..db import Base
from ..deps import TOKEN_TTL_HOURS, get_cfg, get_db
from ..security import hash_password, new_token, token_hash
from .patient import CONSENT_VERSION

public = APIRouter(prefix="/api/public/demo-invite", tags=["Публичное"])
pages = APIRouter(include_in_schema=False)

# Что известно из приглашения (подставляется в форму автоматически)
DEMO = {
    "token": "DEMO-2026",
    "full_name": "Соколова Анна Сергеевна",
    "clinic": "Медицинский центр «Компас»",
    "doctor_login": "doctor1",
    "login": "new_patient",
    "code": "N1",
}
STATUS_LABEL = "новый · зарегистрирован по ссылке"


def enabled() -> bool:
    return os.environ.get("KK_DEMO_INVITE", "1") == "1"


def _check(token: str) -> None:
    if not enabled() or token.strip().upper() != DEMO["token"]:
        raise HTTPException(404, "приглашение не найдено: проверьте ссылку или попросите врача прислать новую")


def _used(db: Session) -> Optional[M.Invitation]:
    return db.execute(select(M.Invitation).where(M.Invitation.code == DEMO["token"])).scalar_one_or_none()


def _doctor(db: Session) -> M.User:
    d = db.execute(select(M.User).where(M.User.login == DEMO["doctor_login"])).scalar_one_or_none()
    if d is None:
        raise HTTPException(503, "лечащий врач для демо-приглашения не найден")
    return d


@public.get("/{token}", summary="Демо-приглашение: данные для формы регистрации")
def info(token: str, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)) -> Dict[str, Any]:
    _check(token)
    inv = _used(db)
    t = cfg["patient_texts"]
    return {"token": DEMO["token"], "used": inv is not None, "used_at": inv.accepted_at.isoformat() if inv and inv.accepted_at else None,
            "clinic": DEMO["clinic"], "doctor": _doctor(db).name, "prefill": {"full_name": DEMO["full_name"]},
            "privacy": t["privacy_transparency"], "consent_text_status": "текст согласия на обработку персональных данных готовит юридическая часть"}


class RegisterIn(BaseModel):
    full_name: str = Field(default="", max_length=120)
    birth_date: str = Field(default="", max_length=10)
    password: str = Field(default="", max_length=100)
    consent: bool = False


NAME_RE = re.compile(r"^[А-ЯЁA-Z][а-яёa-z]+(-[А-ЯЁA-Z]?[а-яёa-z]+)?$")


def validate(body: RegisterIn) -> Dict[str, str]:
    """Ошибки по полям: {поле: понятное сообщение}. Пустой словарь — всё верно."""
    err: Dict[str, str] = {}
    parts = body.full_name.split()
    if len(parts) < 2:
        err["full_name"] = "Укажите фамилию и имя (отчество — если есть)"
    elif len(parts) > 4 or not all(NAME_RE.match(x) for x in parts):
        err["full_name"] = "ФИО пишется буквами, каждое слово с заглавной, например: Соколова Анна Сергеевна"
    try:
        b = date.fromisoformat(body.birth_date)
        today = clock.now().date()
        age = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
        if b > today:
            err["birth_date"] = "Дата рождения не может быть в будущем"
        elif age < 18:
            err["birth_date"] = "Приложение предназначено для взрослых: с 18 лет"
        elif age > 110:
            err["birth_date"] = "Проверьте год рождения"
    except ValueError:
        err["birth_date"] = "Укажите дату рождения"
    if len(body.password) < 8:
        err["password"] = "Пароль — не короче 8 символов"
    elif not (re.search(r"[A-Za-zА-Яа-яЁё]", body.password) and re.search(r"\d", body.password)):
        err["password"] = "В пароле нужны хотя бы одна буква и одна цифра"
    if not body.consent:
        err["consent"] = "Без согласия на обработку персональных данных продолжить нельзя"
    return err


@public.post("/{token}/register", summary="Демо-приглашение: регистрация нового пациента (без телефона и SMS)")
def register(token: str, body: RegisterIn, db: Session = Depends(get_db, scope="function")) -> Dict[str, Any]:
    _check(token)
    if _used(db):
        raise HTTPException(409, "Эта ссылка уже использована: по ней пациент уже зарегистрирован. Войдите со своим логином и паролем.")
    err = validate(body)
    if err:
        raise HTTPException(422, {"message": "Проверьте поля формы", "fields": err})
    if db.execute(select(M.User).where(M.User.login == DEMO["login"])).first():
        raise HTTPException(409, "Эта ссылка уже использована. Сбросьте демо, чтобы показать сценарий заново.")
    doctor, now = _doctor(db), clock.now()
    u = M.User(login=DEMO["login"], password_hash=hash_password(body.password), role="patient", name=" ".join(body.full_name.split()))
    db.add(u)
    db.flush()
    p = M.Patient(code=DEMO["code"], sex=None, birth_date=body.birth_date, doctor_id=doctor.id, user_id=u.id, status="new", synthetic=False)
    db.add(p)
    db.flush()
    db.add(M.Invitation(patient_id=p.id, code=DEMO["token"], expires_at=now + timedelta(days=365), accepted_at=now))
    db.add(M.Consent(patient_id=p.id, version=CONSENT_VERSION, text_status="stub_pending_legal"))
    tok = new_token()
    db.add(M.Token(user_id=u.id, token_hash=token_hash(tok), expires_at=now + timedelta(hours=TOKEN_TTL_HOURS)))
    audit.log(db, u, "consent.accepted", "patient", p.id, p.id, version=CONSENT_VERSION, via="demo_invite")
    db.flush()
    first = u.name.split()[1] if len(u.name.split()) > 1 else u.name
    return {"token": tok, "role": "patient", "name": u.name, "first_name": first, "login": u.login, "patient_id": p.id,
            "public_id": "KK-%06d" % p.id, "clinic": DEMO["clinic"], "doctor": doctor.name}


def reset(db: Session) -> bool:
    """Удалить пациента, зарегистрированного по демо-ссылке, со всеми его записями — ссылку можно открыть снова."""
    inv = _used(db)
    u = db.execute(select(M.User).where(M.User.login == DEMO["login"])).scalar_one_or_none()
    pid = inv.patient_id if inv else None
    if pid is None and u is not None:
        p = db.execute(select(M.Patient).where(M.Patient.user_id == u.id)).scalar_one_or_none()
        pid = p.id if p else None
    if pid is None and u is None:
        return False
    if pid is not None:
        alert_ids = [r[0] for r in db.execute(select(M.Alert.id).where(M.Alert.patient_id == pid))]
        for table in Base.metadata.sorted_tables:  # записи без внешнего ключа (очередь, журнал доставки) — по колонкам
            if table.name in KEEP:
                continue
            if "alert_id" in table.c and alert_ids and not any(fk.parent.name == "alert_id" for fk in table.foreign_keys):
                db.execute(delete(table).where(table.c.alert_id.in_(alert_ids)))
            if "patient_id" in table.c and not any(fk.parent.name == "patient_id" for fk in table.foreign_keys):
                db.execute(delete(table).where(table.c.patient_id == pid))
        _purge(db, M.Patient.__table__, M.Patient.__table__.c.id == pid)  # анкета, шкалы, сигналы, согласие и всё, что на них ссылается
    if u is not None:
        db.execute(delete(M.Token).where(M.Token.user_id == u.id))  # прежние сессии больше не действуют
        try:
            with db.begin_nested():
                _purge(db, M.User.__table__, M.User.__table__.c.id == u.id)
        except IntegrityError:  # на учётную запись ссылается журнал аудита: он не удаляется, запись отключается и освобождает логин
            u.active = False
            u.login = "%s~%s" % (DEMO["login"], clock.now().strftime("%Y%m%d%H%M%S%f"))
    db.flush()
    return True


KEEP = {"audit_log"}  # журнал аудита не удаляется и при сбросе демо


def _purge(db: Session, table, where) -> None:
    """Удалить строки и (рекурсивно) все строки других таблиц, ссылающиеся на них внешним ключом."""
    ids = [r[0] for r in db.execute(select(table.c.id).where(where))] if "id" in table.c else []
    if ids:
        for t2 in Base.metadata.sorted_tables:
            if t2.name in KEEP:
                continue
            for fk in t2.foreign_keys:
                if fk.column.table is table:
                    _purge(db, t2, fk.parent.in_(ids))
    db.execute(delete(table).where(where))


@public.post("/{token}/reset", summary="Сбросить демо: удалить зарегистрированного по ссылке пациента")
def reset_api(token: str, db: Session = Depends(get_db, scope="function")) -> Dict[str, Any]:
    _check(token)
    return {"ok": True, "removed": reset(db)}


@pages.get("/invite/{token}")
def invite_page(token: str, reset_demo: Optional[str] = Query(default=None, alias="reset"), db: Session = Depends(get_db, scope="function")):
    """Прямая ссылка-приглашение (открывается без входа). ?reset=1 — сбросить демо и открыть заново."""
    if reset_demo == "1":
        _check(token)
        reset(db)
    return RedirectResponse("/#/invite/" + token.strip().upper(), status_code=303)
