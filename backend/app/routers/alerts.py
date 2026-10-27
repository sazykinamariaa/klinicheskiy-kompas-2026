"""Алерты для врача и дежурных: список, принятие, попытка связи, смена статуса, закрытие с обязательными полями."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import alerts_service as AL, audit, models as M
from ..config_loader import Config
from ..deps import get_cfg, get_db, require_roles

router = APIRouter(prefix="/api/alerts", tags=["Алерты"])
Staff = Depends(require_roles("doctor", "duty"))


def _visible(db: Session, user: M.User, alert: M.Alert) -> M.Patient:
    p = db.get(M.Patient, alert.patient_id)
    # лечащий врач видит свои; дежурные — все (красный алерт не должен ждать лечащего врача)
    if user.role == "doctor" and p.doctor_id != user.id:
        raise HTTPException(404, "алерт не найден")
    return p


def _get(db: Session, user: M.User, alert_id: int):
    a = db.get(M.Alert, alert_id)
    if a is None:
        raise HTTPException(404, "алерт не найден")
    return a, _visible(db, user, a)


def sla_due_at(db, alert_id: int) -> Optional[str]:
    v = db.execute(
        select(func.min(M.Outbox.next_attempt_at))
        .where(
            M.Outbox.alert_id == alert_id,
            M.Outbox.kind == "escalate",
            M.Outbox.status == "pending"
        )
    ).scalar()
    return v.isoformat() if v else None



def _brief(a: M.Alert, p: M.Patient) -> Dict[str, Any]:
    return {"id": a.id, "patient_id": p.id, "patient": p.code, "rule_id": a.rule_id, "level": a.level, "title": a.title, "status": a.status,
            "created_at": a.created_at.isoformat(), "accepted_at": a.accepted_at.isoformat() if a.accepted_at else None,
            "closed_at": a.closed_at.isoformat() if a.closed_at else None, "after_hours": a.after_hours}


@router.get("", summary="Список алертов (по умолчанию открытые)")
def list_alerts(open_only: bool = True, level: Optional[str] = Query(None, pattern="^(red|orange|yellow)$"),
                user: M.User = Staff, db: Session = Depends(get_db, scope="function")):
    stmt = select(M.Alert)
    if open_only:
        stmt = stmt.where(M.Alert.closed_at.is_(None))
    if level:
        stmt = stmt.where(M.Alert.level == level)
    rows = db.execute(stmt.order_by(M.Alert.id.desc())).scalars().all()
    order = {"red": 0, "orange": 1, "yellow": 2}
    out = []
    for a in rows:
        p = db.get(M.Patient, a.patient_id)
        if user.role == "doctor" and p.doctor_id != user.id:
            continue
        out.append(dict(_brief(a, p), sla_due_at=sla_due_at(db, a.id) if a.closed_at is None and a.accepted_at is None else None))
    out.sort(key=lambda r: (order.get(r["level"], 9), -r["id"]))
    return out


@router.get("/{alert_id}", summary="Карточка алерта: основание, данные, журнал, что нужно для закрытия")
def get_alert(alert_id: int, user: M.User = Staff, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    a, p = _get(db, user, alert_id)
    audit.log(db, user, "alert.view", "alert", a.id, p.id)
    evs = db.execute(select(M.AlertEvent).where(M.AlertEvent.alert_id == a.id).order_by(M.AlertEvent.id)).scalars().all()
    lc = cfg["alert_rules"]["alert_lifecycle"]
    return dict(_brief(a, p), sla_due_at=sla_due_at(db, a.id) if a.closed_at is None and a.accepted_at is None else None, basis=a.basis, facts=a.facts, close_data=a.close_data,
                events=[{"ts": e.ts.isoformat(), "kind": e.kind, "actor_id": e.actor_id, "data": e.data} for e in evs],
                lifecycle={"statuses": lc["statuses"], "close_reasons": lc["close_reasons"], "checklist_hint": lc["doctor_checklist_hint"],
                           "checklist_status": lc["doctor_checklist_status"], "close_fields": cfg.bindings["alert_close_fields"]["fields"],
                           "relaxed_reasons": cfg.bindings["alert_close_fields"]["relaxed_reasons"]},
                system_note="Система скорую не вызывает. Решение о помощи принимает врач.")


def _wrap(fn):
    try:
        return fn()
    except AL.AlertError as e:
        raise HTTPException(e.status, str(e))


@router.post("/{alert_id}/accept", summary="Принять алерт (подтверждение получения)")
def accept(alert_id: int, user: M.User = Staff, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    a, _ = _get(db, user, alert_id)
    _wrap(lambda: AL.accept(db, cfg, a, user))
    return {"ok": True, "status": a.status}


class ContactIn(BaseModel):
    result: str  # reached | unreachable
    method: str
    note: str = ""


@router.post("/{alert_id}/contact", summary="Записать попытку связи. «Не удалось связаться» не закрывает красный алерт")
def contact(alert_id: int, body: ContactIn, user: M.User = Staff, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    if body.result not in ("reached", "unreachable"):
        raise HTTPException(422, "result: reached | unreachable")
    a, _ = _get(db, user, alert_id)
    _wrap(lambda: AL.contact_attempt(db, cfg, a, user, body.result, body.method, body.note))
    return {"ok": True, "status": a.status, "still_open": a.closed_at is None}


class StatusIn(BaseModel):
    status: str
    handed_to: Optional[str] = None
    note: Optional[str] = None


@router.post("/{alert_id}/status", summary="Сменить статус (передача, экстренная помощь организована и т.д.)")
def status(alert_id: int, body: StatusIn, user: M.User = Staff, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    a, _ = _get(db, user, alert_id)
    _wrap(lambda: AL.transition(db, cfg, a, user, body.status, {"handed_to": body.handed_to, "note": body.note}))
    return {"ok": True, "status": a.status}


class CloseIn(BaseModel):
    close_reason: str
    data: Dict[str, Any]


@router.post("/{alert_id}/close", summary="Закрыть алерт: обязательные поля (кто и когда оценивал, способ контакта, основание, решение, кому передан, срок контакта, комментарий)")
def close(alert_id: int, body: CloseIn, user: M.User = Staff, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    a, _ = _get(db, user, alert_id)
    _wrap(lambda: AL.close(db, cfg, a, user, body.close_reason, body.data))
    return {"ok": True, "status": a.status}
