"""Панель администратора: состояние конфигурации, ожидаемые данные, правила, очередь, журнал, пользователи.

Администратор НЕ имеет доступа к клиническим данным: в журнале аудита он видит действие и время, но не содержимое и не пациента.
Редактирование конфигурации не требует изменения кода: файл проверяется целиком (структура, ссылки, исполнимость правил) и только потом сохраняется.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, clock, deps, facts as F, models as M, queue as Q
from ..config_loader import CONFIG_FILES, EXTRA_FILES, Config, ConfigError, load_config
from ..deps import get_cfg, get_db, require_roles
from ..security import hash_password

router = APIRouter(prefix="/api/admin", tags=["Администратор"])
Admin = Depends(require_roles("admin"))


@router.get("/config/summary", summary="Состояние конфигурации: сколько утверждено, ждёт данных, требует проверки")
def summary(user: M.User = Admin, cfg: Config = Depends(get_cfg)):
    ex = cfg.exec_report
    return {"statuses": cfg.status_summary(), "rules_total": len(ex), "rules_executable": sum(1 for v in ex.values() if v["executable"]),
            "rules_not_executable": cfg.unexecutable_rules(), "config_dir": cfg.path.name, "approval": cfg["approval"].get("approval")}


@router.get("/config/waiting", summary="Что ждёт данных (значения «ЖДЁМ», статусы waiting / verify)")
def waiting(user: M.User = Admin, cfg: Config = Depends(get_cfg)):
    items = cfg.waiting_items()
    return {"count": len(items), "items": items}


@router.get("/config/rules", summary="Правила и признак исполнимости")
def rules(user: M.User = Admin, cfg: Config = Depends(get_cfg)):
    out = []
    for kind, lst in (("alert", cfg.alert_rules), ("routing_mandatory", cfg.routing_mandatory), ("routing_desirable", cfg.routing_desirable)):
        for r in lst:
            rep = cfg.exec_report.get(r["id"], {"executable": True})
            out.append({"id": r["id"], "kind": kind, "title": r.get("title"), "level": r.get("level"), "status": r.get("status"),
                        "executable": rep["executable"], "why_not": rep.get("why"), "expr": cfg.rule_expr(r),
                        "overridden": r["id"] in cfg.bindings.get("rule_overrides", {})})
    return out


@router.get("/config/files", summary="Файлы конфигурации")
def files(user: M.User = Admin, cfg: Config = Depends(get_cfg)):
    return [{"name": n, "size": (cfg.path / (n + ".json")).stat().st_size} for n in CONFIG_FILES + EXTRA_FILES if (cfg.path / (n + ".json")).exists()]


@router.get("/config/files/{name}", summary="Содержимое файла конфигурации")
def get_file(name: str, user: M.User = Admin, cfg: Config = Depends(get_cfg)):
    if name not in CONFIG_FILES + EXTRA_FILES:
        raise HTTPException(404, "нет такого файла")
    return json.loads((cfg.path / (name + ".json")).read_text(encoding="utf-8"))


class ConfigPut(BaseModel):
    content: Dict[str, Any]
    comment: str = Field(min_length=3, max_length=300)


def _try_load(path: Path) -> Config:
    first = load_config(path, strict=False)
    return load_config(path, known_facts=F.fact_catalog(first), strict=True)


@router.put("/config/files/{name}", summary="Заменить файл конфигурации (проверяется целиком; при ошибке файл не меняется)")
def put_file(name: str, body: ConfigPut, user: M.User = Admin, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    if name not in CONFIG_FILES + EXTRA_FILES:
        raise HTTPException(404, "нет такого файла")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "cfg"
        shutil.copytree(cfg.path, tmp)
        (tmp / (name + ".json")).write_text(json.dumps(body.content, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            new = _try_load(tmp)
        except (ConfigError, KeyError, TypeError) as e:
            raise HTTPException(422, "конфигурация не прошла проверку, файл не изменён: %s" % e)
    target = cfg.path / (name + ".json")
    bak = cfg.path / ".backup"
    bak.mkdir(exist_ok=True)
    shutil.copy2(target, bak / ("%s.%s.json" % (name, clock.now().strftime("%Y%m%dT%H%M%S"))))
    target.write_text(json.dumps(body.content, ensure_ascii=False, indent=2), encoding="utf-8")
    new.path = cfg.path
    deps.set_cfg(_try_load(cfg.path))
    audit.log(db, user, "config.put", "config", name, None, comment=body.comment)
    return {"ok": True, "rules_executable": sum(1 for v in deps.get_cfg().exec_report.values() if v["executable"])}


@router.post("/config/reload", summary="Перечитать конфигурацию с диска")
def reload(user: M.User = Admin, db: Session = Depends(get_db, scope="function")):
    try:
        cfg = deps.reload_config()
    except ConfigError as e:
        raise HTTPException(422, str(e))
    audit.log(db, user, "config.reload", "config", None, None)
    return {"ok": True, "rules_total": len(cfg.exec_report)}


@router.get("/queue", summary="Очередь доставки: статусы и последние сбои (без клинического содержимого)")
def queue(user: M.User = Admin, db: Session = Depends(get_db, scope="function")):
    ov = Q.overview(db)
    dead = db.execute(select(M.Outbox).where(M.Outbox.status == "dead").order_by(M.Outbox.id.desc()).limit(20)).scalars().all()
    ov["dead_recent"] = [{"id": j.id, "kind": j.kind, "attempts": j.attempts, "error": j.last_error} for j in dead]
    ov["channels"] = {n: {"always_fail": c.always_fail, "fail_next": c.fail_next} for n, c in Q.CHANNELS.items()}
    return ov


@router.post("/queue/run", summary="Обработать очередь сейчас")
def run_queue(user: M.User = Admin, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    return Q.process_due(db, cfg)


@router.get("/audit", summary="Журнал аудита без клинического содержимого")
def audit_view(limit: int = 100, user: M.User = Admin, db: Session = Depends(get_db, scope="function")):
    rows = db.execute(select(M.AuditLog).order_by(M.AuditLog.id.desc()).limit(min(limit, 500))).scalars().all()
    return [{"id": r.id, "ts": r.ts.isoformat(), "actor_id": r.actor_id, "actor_role": r.actor_role, "action": r.action, "entity": r.entity} for r in rows]


class UserIn(BaseModel):
    login: str = Field(min_length=3, max_length=60)
    password: str = Field(min_length=8, max_length=100)
    role: str = Field(pattern="^(doctor|duty|psychiatrist|admin)$")
    name: str = Field(default="", max_length=120)
    duty_role: Optional[str] = Field(default=None, pattern="^(duty_doctor|clinic_admin_on_duty|responsible_staff)$")
    phone: Optional[str] = None


@router.get("/users", summary="Пользователи (без пациентов)")
def users(user: M.User = Admin, db: Session = Depends(get_db, scope="function")):
    return [{"id": u.id, "login": u.login, "role": u.role, "name": u.name, "duty_role": u.duty_role, "active": u.active}
            for u in db.execute(select(M.User).where(M.User.role != "patient").order_by(M.User.id)).scalars()]


@router.post("/users", summary="Создать пользователя")
def create_user(body: UserIn, user: M.User = Admin, db: Session = Depends(get_db, scope="function")):
    if db.execute(select(M.User).where(M.User.login == body.login)).first():
        raise HTTPException(409, "логин занят")
    u = M.User(login=body.login, password_hash=hash_password(body.password), role=body.role, name=body.name, duty_role=body.duty_role, phone=body.phone)
    db.add(u)
    db.flush()
    audit.log(db, user, "user.create", "user", u.id, None, role=body.role)
    return {"id": u.id}


@router.post("/users/{uid}/active", summary="Включить или отключить пользователя")
def set_active(uid: int, active: bool, user: M.User = Admin, db: Session = Depends(get_db, scope="function")):
    u = db.get(M.User, uid)
    if u is None or u.role == "patient":
        raise HTTPException(404, "пользователь не найден")
    u.active = active
    audit.log(db, user, "user.active", "user", u.id, None, active=active)
    return {"ok": True}
