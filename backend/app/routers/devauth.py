"""Быстрая регистрация пациента по приглашению врача (1 тап), вход через Google, режим разработки."""
from __future__ import annotations

import json
import os
import secrets
import urllib.parse
import urllib.request
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import ForeignKey, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import audit, clock, models as M
from ..db import Base
from ..deps import TOKEN_TTL_HOURS, get_db
from ..security import hash_password, new_token, token_hash
from .patient import CONSENT_VERSION, _invitation

public = APIRouter(prefix="/api/public", tags=["Публичное"])
auth = APIRouter(prefix="/api/auth", tags=["Авторизация"])
dev = APIRouter(prefix="/api/dev", tags=["Режим разработки"])

class GoogleIdentity(Base):
    __tablename__ = "google_identities"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    sub: Mapped[str] = mapped_column(String(64), unique=True, index=True)


def dev_mode() -> bool:
    return os.environ.get("KK_DEV_MODE", "0") == "1"


def google_client_id() -> Optional[str]:
    cid = os.environ.get("KK_GOOGLE_CLIENT_ID", "").strip()
    return cid if cid else None


def public_id(patient_id: int) -> str:
    return f"KK-{patient_id:06d}"


def verify_google_token(id_token: str) -> dict:
    cid = google_client_id()
    if not cid:
        raise HTTPException(503, "вход через Google не настроен")
    try:
        url = "https://oauth2.googleapis.com/tokeninfo?id_token=" + urllib.parse.quote(id_token)
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read())
    except Exception:
        raise HTTPException(401, "Google не подтвердил вход")
    if data.get("aud") != cid or str(data.get("email_verified")).lower() != "true":
        raise HTTPException(401, "Google не подтвердил вход")
    if not data.get("sub"):
        raise HTTPException(401, "Google не подтвердил вход")
    return data


def _issue(db: Session, user: M.User) -> str:
    tok = new_token()
    db.add(M.Token(user_id=user.id, token_hash=token_hash(tok), expires_at=clock.now() + timedelta(hours=TOKEN_TTL_HOURS)))
    return tok


def _create_patient_user(db: Session, inv: M.Invitation, login: str, password: str) -> tuple:
    p = db.get(M.Patient, inv.patient_id)
    if db.execute(select(M.User).where(M.User.login == login)).first():
        raise HTTPException(409, "логин занят")
    u = M.User(login=login, password_hash=hash_password(password), role="patient", name=p.code)
    db.add(u)
    db.flush()
    p.user_id = u.id
    p.status = "active"
    inv.accepted_at = clock.now()
    db.add(M.Consent(patient_id=p.id, version=CONSENT_VERSION, text_status="stub_pending_legal"))
    audit.log(db, u, "consent.accepted", "patient", p.id, p.id, version=CONSENT_VERSION)
    return u, p


class QuickIn(BaseModel):
    consent: bool


class GoogleAcceptIn(BaseModel):
    consent: bool
    id_token: str


class GoogleLoginIn(BaseModel):
    id_token: str


class ImpersonateIn(BaseModel):
    login: str


@public.get("/auth-config", summary="Какие способы входа доступны")
def auth_config():
    return {"dev_mode": dev_mode(), "google_client_id": google_client_id()}


@public.post("/invitation/{code}/accept-quick", summary="Регистрация в 1 тап по коду врача")
def accept_quick(code: str, body: QuickIn, db: Session = Depends(get_db, scope="function")):
    inv = _invitation(db, code)
    if not body.consent:
        raise HTTPException(422, "без согласия на обработку персональных данных продолжить нельзя")
    pid = public_id(inv.patient_id)
    login = pid.lower()
    password = secrets.token_urlsafe(9)
    u, p = _create_patient_user(db, inv, login, password)
    tok = _issue(db, u)
    return {"token": tok, "role": "patient", "patient_id": p.id, "public_id": pid, "login": login, "password": password}


@public.post("/invitation/{code}/accept-google", summary="Регистрация по коду врача через Google")
def accept_google(code: str, body: GoogleAcceptIn, db: Session = Depends(get_db, scope="function")):
    if not body.consent:
        raise HTTPException(422, "без согласия на обработку персональных данных продолжить нельзя")
    data = verify_google_token(body.id_token)
    inv = _invitation(db, code)
    if db.execute(select(GoogleIdentity).where(GoogleIdentity.sub == data["sub"])).first():
        raise HTTPException(409, "этот аккаунт Google уже зарегистрирован: войдите через Google")
    pid = public_id(inv.patient_id)
    u, p = _create_patient_user(db, inv, pid.lower(), secrets.token_urlsafe(24))
    db.add(GoogleIdentity(user_id=u.id, sub=data["sub"]))
    tok = _issue(db, u)
    return {"token": tok, "role": "patient", "patient_id": p.id, "public_id": pid}


@auth.post("/google", summary="Вход через Google")
def login_google(body: GoogleLoginIn, db: Session = Depends(get_db, scope="function")):
    data = verify_google_token(body.id_token)
    gi = db.execute(select(GoogleIdentity).where(GoogleIdentity.sub == data["sub"])).scalar_one_or_none()
    user = db.get(M.User, gi.user_id) if gi else None
    if not user or not user.active:
        raise HTTPException(401, "аккаунт Google не привязан: зарегистрируйтесь по коду врача")
    tok = _issue(db, user)
    audit.log(db, user, "auth.login_google", "user", user.id)
    return {"token": tok, "role": user.role, "name": user.name, "user_id": user.id}


@dev.get("/users", summary="Режим разработки: пользователи для переключения")
def dev_users(db: Session = Depends(get_db, scope="function")):
    if not dev_mode():
        raise HTTPException(404, "не найдено")
    rows = db.execute(select(M.User).where(M.User.active.is_(True)).order_by(M.User.role, M.User.login)).scalars().all()
    return [{"login": u.login, "role": u.role, "name": u.name} for u in rows]


@dev.post("/impersonate", summary="Режим разработки: войти под выбранным пользователем")
def impersonate(body: ImpersonateIn, db: Session = Depends(get_db, scope="function")):
    if not dev_mode():
        raise HTTPException(404, "не найдено")
    user = db.execute(select(M.User).where(M.User.login == body.login.strip())).scalar_one_or_none()
    if not user or not user.active:
        raise HTTPException(404, "пользователь не найден")
    tok = _issue(db, user)
    audit.log(db, user, "auth.dev_impersonate", "user", user.id)
    return {"token": tok, "role": user.role, "name": user.name, "user_id": user.id}