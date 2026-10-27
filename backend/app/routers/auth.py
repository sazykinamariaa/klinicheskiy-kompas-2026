from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, clock, models as M
from ..deps import TOKEN_TTL_HOURS, current_user, get_db
from ..security import new_token, token_hash, verify_password

router = APIRouter(prefix="/api/auth", tags=["Авторизация"])


class LoginIn(BaseModel):
    login: str
    password: str


@router.post("/login", summary="Вход: возвращает токен доступа")
def login(body: LoginIn, db: Session = Depends(get_db, scope="function")):
    user = db.execute(select(M.User).where(func.lower(M.User.login) == body.login.strip().lower())).scalar_one_or_none()
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        audit.log(db, None, "auth.login_failed", "user", body.login[:40])
        db.commit()
        raise HTTPException(401, "неверный логин или пароль")
    tok = new_token()
    db.add(M.Token(user_id=user.id, token_hash=token_hash(tok), expires_at=clock.now() + timedelta(hours=TOKEN_TTL_HOURS)))
    audit.log(db, user, "auth.login", "user", user.id)
    return {"token": tok, "role": user.role, "name": user.name, "user_id": user.id}


@router.post("/logout", summary="Выход")
def logout(user: M.User = Depends(current_user), db: Session = Depends(get_db, scope="function")):
    db.query(M.Token).filter(M.Token.user_id == user.id).delete()
    audit.log(db, user, "auth.logout", "user", user.id)
    return {"ok": True}


@router.get("/me", summary="Текущий пользователь")
def me(user: M.User = Depends(current_user), db: Session = Depends(get_db, scope="function")):
    out = {"id": user.id, "login": user.login, "role": user.role, "name": user.name, "duty_role": user.duty_role}
    if user.role == "patient":
        p = db.execute(select(M.Patient).where(M.Patient.user_id == user.id)).scalar_one_or_none()
        out["patient_id"] = p.id if p else None
    return out
