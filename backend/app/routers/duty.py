"""Дежурный: центр оповещений, контекст сигнала с хронологией, маршрутизация и эскалация, протоколы, передача смены."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, clock, models as M, state_builder as SB
from ..config_loader import Config
from ..deps import get_cfg, get_db, require_roles
from .doctor_sections import _fact_label, _source_info

router = APIRouter(prefix="/api/duty", tags=["Дежурный"])
Staff = Depends(require_roles("duty", "doctor"))
Duty = Depends(require_roles("duty"))

STATUS_RU = {"new": "Новый", "accepted": "Принят", "contact_established_assessed": "Связь установлена, оценка проведена",
             "handed_over_awaiting_confirmation": "Передан, ждёт подтверждения", "emergency_help_arranged": "Экстренная помощь организована",
             "closed_with_documented_result": "Закрыт с результатом"}
ACTION_KINDS = ("contact_attempt", "status", "closed", "assigned", "handover_confirmed", "escalated_manual")


def _visible_alerts(db: Session, user: M.User, open_only: bool = True) -> List[M.Alert]:
    stmt = select(M.Alert)
    if open_only:
        stmt = stmt.where(M.Alert.closed_at.is_(None))
    stmt = stmt.order_by(M.Alert.id.desc())
    rows = db.execute(stmt).scalars().all()
    if user.role == "doctor":
        rows = [a for a in rows if db.get(M.Patient, a.patient_id).doctor_id == user.id]
    return rows


def _events(db: Session, a: M.Alert) -> List[M.AlertEvent]:
    stmt = select(M.AlertEvent).where(M.AlertEvent.alert_id == a.id).order_by(M.AlertEvent.id)
    return db.execute(stmt).scalars().all()


def _level_cfg(cfg: Config, level: str) -> Dict[str, Any]:
    return next((l for l in cfg["alert_rules"]["levels"] if l["id"] == level), {})


def _ack_minutes(cfg: Config, level: str) -> Optional[int]:
    v = _level_cfg(cfg, level).get("ack_deadline_minutes")
    if isinstance(v, dict):
        return v.get("value")
    esc = _level_cfg(cfg, level).get("escalation") or []
    return esc[0]["after_minutes"] if esc else None


def _responsible(db: Session, a: M.Alert, evs: List[M.AlertEvent]) -> Dict[str, Any]:
    asg = [e for e in evs if e.kind == "assigned"]
    if asg:
        u = db.get(M.User, asg[-1].data.get("user_id"))
        return {"user_id": u.id if u else None, "name": u.name if u else asg[-1].data.get("name"), "how": "назначен"}
    if a.accepted_by:
        u = db.get(M.User, a.accepted_by)
        return {"user_id": u.id, "name": u.name, "how": "принял сигнал"}
    p = db.get(M.Patient, a.patient_id)
    u = db.get(M.User, p.doctor_id)
    return {"user_id": u.id, "name": u.name, "how": "лечащий врач"} if u else {"user_id": None, "name": "Неизвестно", "how": None}


def _sla(cfg: Config, a: M.Alert) -> Dict[str, Any]:
    m = _ack_minutes(cfg, a.level)
    if m is None or a.closed_at:
        return {"deadline": None, "overdue": False, "minutes_left": None, "minutes": m}
    deadline = a.created_at + timedelta(minutes=m)
    now = clock.now()
    if a.accepted_at:
        return {"deadline": deadline.isoformat(), "overdue": a.accepted_at > deadline, "minutes_left": None, "minutes": m, "met": a.accepted_at <= deadline}
    left = int((deadline - now).total_seconds() // 60)
    return {"deadline": deadline.isoformat(), "overdue": left < 0, "minutes_left": left, "minutes": m}


def _timeline(a: M.Alert, evs: List[M.AlertEvent]) -> List[Dict[str, Any]]:
    def first(kinds, cond=None):
        for e in evs:
            if e.kind in kinds and (cond is None or cond(e)):
                return e.ts.isoformat()
        return None
    created = a.created_at.isoformat()
    notified = first(("notified",))
    accepted = a.accepted_at.isoformat() if a.accepted_at else None
    actions = first(("contact_attempt", "status"))
    handed = first(("status",), lambda e: (e.data or {}).get("status") in ("handed_over_awaiting_confirmation", "emergency_help_arranged")) \
        or first(("handover_confirmed",)) or (a.closed_at.isoformat() if a.closed_at else None)
    steps = [("created", "Сигнал создан", created), ("notified", "Уведомление доставлено", notified), ("accepted", "Сотрудник подтвердил", accepted), ("actions", "Действия зафиксированы", actions), ("handed", "Случай передан или закрыт", handed)]
    return [{"step": k, "label": l, "at": t, "done": t is not None} for k, l, t in steps]


def _card(cfg: Config, db: Session, a: M.Alert) -> Dict[str, Any]:
    p = db.get(M.Patient, a.patient_id)
    evs = _events(db, a)
    intake = SB.intake(db, p.id)
    return {"id": a.id, "patient_id": p.id, "patient": p.code, "rule_id": a.rule_id, "level": a.level, "title": a.title,
            "status": a.status, "status_label": STATUS_RU.get(a.status, a.status), "created_at": a.created_at.isoformat(),
            "accepted": a.accepted_at is not None, "basis": [_fact_label(cfg, k, v, intake) for k, v in (a.facts or {}).items()],
            "responsible": _responsible(db, a, evs), "sla": _sla(cfg, a), "after_hours": a.after_hours}


@router.get("/center", summary="Центр оповещений: категории сигналов")
def center(user: M.User = Staff, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    rows = _visible_alerts(db, user)
    cards = {a.id: _card(cfg, db, a) for a in rows}
    def ids(pred): return [cards[a.id] for a in rows if pred(a)]
    def no_action(a): evs = _events(db, a); return a.accepted_at is not None and not any(e.kind in ACTION_KINDS for e in evs)
    return {"categories": [
        {"id": "critical", "title": "Критические алерты", "items": ids(lambda a: a.level == "red")},
        {"id": "urgent_requests", "title": "Срочные обращения", "items": ids(lambda a: a.rule_id in cfg.bindings.get("duty_categories", {}).get("urgent_requests", []))},
        {"id": "deterioration", "title": "Ухудшение состояния", "items": ids(lambda a: a.rule_id in cfg.bindings.get("duty_categories", {}).get("deterioration", []))},
        {"id": "adverse_events", "title": "Сообщения о нежелательных явлениях", "items": ids(lambda a: a.rule_id in cfg.bindings.get("duty_categories", {}).get("adverse_events", []))},
        {"id": "unconfirmed", "title": "Новые сигналы, не подтверждённые сотрудником", "items": ids(lambda a: a.accepted_at is None)},
        {"id": "no_action", "title": "Нет зафиксированного дальнейшего действия", "items": ids(no_action)}]}


@router.get("/new-patients", summary="Новые пациенты, зарегистрированные по ссылке-приглашению (без медицинских данных)")
def new_patients(user: M.User = Staff, db: Session = Depends(get_db, scope="function")):
    from .demo_invite import STATUS_LABEL
    rows = db.execute(select(M.Patient).where(M.Patient.status == "new").order_by(M.Patient.created_at.desc())).scalars().all()
    if user.role == "doctor":
        rows = [p for p in rows if p.doctor_id == user.id]
    out = []
    for p in rows:
        inv = db.execute(select(M.Invitation).where(M.Invitation.patient_id == p.id, M.Invitation.accepted_at.is_not(None))).scalars().first()
        doc = db.get(M.User, p.doctor_id)
        out.append({"patient_id": p.id, "patient": p.code, "status_label": STATUS_LABEL,
                    "registered_at": (inv.accepted_at if inv else p.created_at).isoformat(), "doctor": doc.name if doc else None})
    return out


@router.get("/alerts/{alert_id}/context", summary="Сигнал: что сообщил пациент, основание, данные, прошлые события, приоритет, инструкции, хронология")
def context(alert_id: int, user: M.User = Staff, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    a = db.get(M.Alert, alert_id)
    if not a:
        raise HTTPException(404, "алерт не найден")
    p = db.get(M.Patient, a.patient_id)
    if user.role == "doctor" and p.doctor_id != user.id:
        raise HTTPException(404, "алерт не найден")
    evs = _events(db, a)
    intake = SB.intake(db, p.id)
    reported = [_fact_label(cfg, k, v, intake) for k, v in (a.facts or {}).items()]
    last_run = db.execute(select(M.ScaleRun).where(M.ScaleRun.patient_id == p.id, M.ScaleRun.complete.is_(True)).order_by(M.ScaleRun.completed_at.desc())).scalars().first()
    last_ck = db.execute(select(M.Checkin).where(M.Checkin.patient_id == p.id).order_by(M.Checkin.day.desc())).scalars().first()
    data = {"last_scale": ({"scale": last_run.scale_id, "total": last_run.total, "at": last_run.completed_at.isoformat()} if last_run else None),
            "last_checkin": last_ck.day.isoformat() if last_ck else None, "intake_answers": len(intake)}
    prev = db.execute(select(M.Alert).where(M.Alert.patient_id == p.id, M.Alert.id != a.id).order_by(M.Alert.id.desc())).scalars().all()[:6]
    previous = [{"id": x.id, "level": x.level, "title": x.title, "created_at": x.created_at.isoformat(), "closed": x.closed_at is not None, "status_label": STATUS_RU.get(x.status, x.status)} for x in prev]
    lv = _level_cfg(cfg, a.level)
    protos = cfg["alert_rules"].get("response_protocols", {}).get("protocols", [])
    proto = next((x for x in protos if a.rule_id in x.get("rules", [])), None)
    return {"alert": _card(cfg, db, a), "reported": reported, "source": _source_info(cfg, (a.basis or {}).get("source")),
            "data": data, "previous": previous,
            "priority": {"level": a.level, "label": lv.get("label"), "ack_minutes": _ack_minutes(cfg, a.level),
                         "escalation": [{"after_minutes": e["after_minutes"], "to": e["to"]} for e in lv.get("escalation", [])]},
            "protocol": proto, "timeline": _timeline(a, evs), "system_note": "Система скорую не вызывает. Решение о помощи принимает врач."}

# ---------------------------------------------------------------- маршрутизация, эскалация, протоколы, передача смены

ROLE_RU = {"duty_doctor": "Дежурный врач", "clinic_admin_on_duty": "Администратор смены", "responsible_staff": "Ответственный сотрудник"}
ROLE_BASE = {"doctor": "Врач", "psychiatrist": "Психиатр", "duty": "Дежурный"}


def _alert(db: Session, user: M.User, alert_id: int) -> M.Alert:
    a = db.get(M.Alert, alert_id)
    if a is None:
        raise HTTPException(404, "алерт не найден")
    if user.role == "doctor" and db.get(M.Patient, a.patient_id).doctor_id != user.id:
        raise HTTPException(404, "алерт не найден")
    if a.closed_at:
        raise HTTPException(409, "алерт уже закрыт")
    return a


def _ev(db: Session, a: M.Alert, kind: str, user: M.User, **data: Any) -> None:
    db.add(M.AlertEvent(alert_id=a.id, kind=kind, actor_id=user.id, data=data, ts=clock.now()))


@router.get("/staff", summary="Кому можно назначить сигнал или передать случай")
def staff(user: M.User = Staff, db: Session = Depends(get_db, scope="function")):
    rows = db.execute(select(M.User).where(M.User.active.is_(True), M.User.role.in_(("duty", "doctor", "psychiatrist"))).order_by(M.User.id)).scalars().all()
    return [{"id": u.id, "name": u.name, "role": u.role, "role_label": ROLE_RU.get(u.duty_role or "", ROLE_BASE.get(u.role, u.role))} for u in rows]


@router.get("/routing", summary="Маршрутизация и эскалация: открытые сигналы трёх уровней")
def routing(user: M.User = Staff, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    out = {"red": [], "orange": [], "yellow": []}
    for a in _visible_alerts(db, user):
        if a.level not in out:
            continue
        evs = _events(db, a)
        c = _card(cfg, db, a)
        handed = next((e for e in reversed(evs) if e.kind == "status" and (e.data or {}).get("status") == "handed_over_awaiting_confirmation"), None)
        conf = next((e for e in reversed(evs) if e.kind == "handover_confirmed"), None)
        c["handover"] = {"to": (handed.data or {}).get("handed_to") if handed else None, "at": handed.ts.isoformat() if handed else None,
                         "confirmed_at": conf.ts.isoformat() if conf else None, "confirmed_by": (conf.data or {}).get("by") if conf else None}
        c["escalations"] = [{"at": e.ts.isoformat(), "to": (e.data or {}).get("to"), "to_label": ROLE_RU.get((e.data or {}).get("to"), (e.data or {}).get("to")),
                             "manual": e.kind == "escalated_manual", "note": (e.data or {}).get("note")} for e in evs if e.kind in ("escalated", "escalated_manual")]
        c["chain"] = [{"after_minutes": x["after_minutes"], "to": x["to"], "to_label": ROLE_RU.get(x["to"], x["to"])} for x in _level_cfg(cfg, a.level).get("escalation", [])]
        out[a.level].append(c)
    return {"levels": [{"id": k, "label": _level_cfg(cfg, k).get("label", k), "items": v} for k, v in out.items()]}


class AssignIn(BaseModel):
    user_id: int


@router.post("/alerts/{alert_id}/assign", summary="Назначить ответственного сотрудника")
def assign(alert_id: int, body: AssignIn, user: M.User = Staff, db: Session = Depends(get_db, scope="function")):
    a = _alert(db, user, alert_id)
    u = db.get(M.User, body.user_id)
    if u is None or u.role not in ("duty", "doctor", "psychiatrist"):
        raise HTTPException(422, "сотрудник не найден")
    _ev(db, a, "assigned", user, user_id=u.id, name=u.name)
    audit.log(db, user, "alert.assign", "alert", a.id, a.patient_id, to=u.id)
    db.flush()
    return {"ok": True, "responsible": _responsible(db, a, _events(db, a))}


class ConfirmIn(BaseModel):
    by: str = Field(min_length=2, max_length=120)
    note: str = Field(default="", max_length=500)


@router.post("/alerts/{alert_id}/handover-confirm", summary="Принимающий специалист подтвердил получение случая")
def handover_confirm(alert_id: int, body: ConfirmIn, user: M.User = Staff, db: Session = Depends(get_db, scope="function")):
    a = _alert(db, user, alert_id)
    if a.status != "handed_over_awaiting_confirmation":
        raise HTTPException(409, "случай ещё не передан: сначала смените статус на «передан, ждёт подтверждения»")
    _ev(db, a, "handover_confirmed", user, by=body.by.strip(), note=body.note.strip())
    audit.log(db, user, "alert.handover_confirmed", "alert", a.id, a.patient_id)
    db.flush()
    return {"ok": True}


class EscalateIn(BaseModel):
    to: str = Field(pattern="^(duty_doctor|clinic_admin_on_duty)$")
    note: str = Field(default="", max_length=500)


@router.post("/alerts/{alert_id}/escalate", summary="Эскалация вручную: ответственный не реагирует")
def escalate(alert_id: int, body: EscalateIn, user: M.User = Staff, db: Session = Depends(get_db, scope="function")):
    a = _alert(db, user, alert_id)
    _ev(db, a, "escalated_manual", user, to=body.to, note=body.note.strip())
    audit.log(db, user, "alert.escalate_manual", "alert", a.id, a.patient_id, to=body.to)
    db.flush()
    return {"ok": True, "to_label": ROLE_RU.get(body.to, body.to)}


@router.get("/protocols", summary="Протоколы реагирования")
def protocols(user: M.User = Staff, cfg: Config = Depends(get_cfg)):
    rp = cfg["alert_rules"].get("response_protocols", {})
    return {"meta": rp.get("_meta", {}), "protocols": rp.get("protocols", [])}


def _handover_row(db: Session, h: M.ShiftHandover) -> Dict[str, Any]:
    a = db.get(M.User, h.author_id)
    n = db.get(M.User, h.next_responsible_id) if h.next_responsible_id else None
    c = db.get(M.User, h.confirmed_by) if h.confirmed_by else None
    return {"id": h.id, "author": a.name if a else None, "author_id": h.author_id, "created_at": h.created_at.isoformat(), "data": h.data or {},
            "next_responsible": n.name if n else None, "next_responsible_id": h.next_responsible_id,
            "confirmed_by": c.name if c else None, "confirmed_at": h.confirmed_at.isoformat() if h.confirmed_at else None}


@router.get("/handover/draft", summary="Черновик передачи смены: незакрытые случаи и ожидающие ответа")
def handover_draft(user: M.User = Duty, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    rows = _visible_alerts(db, user)
    code = lambda pid: db.get(M.Patient, pid).code
    open_cases = [{"id": a.id, "patient": code(a.patient_id), "level": a.level, "title": a.title, "status_label": STATUS_RU.get(a.status, a.status)}
                  for a in rows if a.level in ("red", "orange")]
    waiting = [{"id": a.id, "patient": code(a.patient_id), "title": a.title} for a in rows
               if a.status == "handed_over_awaiting_confirmation" and not any(e.kind == "handover_confirmed" for e in _events(db, a))]
    for r in db.execute(select(M.Referral).where(M.Referral.status == "awaiting_acceptance")).scalars():
        waiting.append({"id": None, "patient": code(r.patient_id), "title": "направление к психиатру " + r.rule_id + " ждёт получения"})
    since = clock.now() - timedelta(hours=12)
    KIND = {"accepted": "принят сигнал", "contact_attempt": "попытка связи", "status": "смена статуса", "closed": "закрыт сигнал",
            "assigned": "назначен ответственный", "handover_confirmed": "подтверждена передача", "escalated_manual": "эскалация вручную"}
    done = []
    for e in db.execute(select(M.AlertEvent).where(M.AlertEvent.actor_id == user.id, M.AlertEvent.ts >= since).order_by(M.AlertEvent.ts)).scalars():
        if e.kind in KIND:
            st = STATUS_RU.get((e.data or {}).get("status"), "") if e.kind == "status" else ""
            done.append("сигнал #%s: %s%s" % (e.alert_id, KIND[e.kind], (" — " + st) if st else ""))
    return {"open_cases": open_cases, "waiting": waiting, "done": done}


class HandoverIn(BaseModel):
    open_cases_note: str = Field(default="", max_length=3000)
    waiting_note: str = Field(default="", max_length=3000)
    done_actions: str = Field(default="", max_length=3000)
    next_steps: str = Field(min_length=3, max_length=3000)
    next_responsible_id: int


@router.post("/handover", summary="Заполнить передачу смены")
def handover_create(body: HandoverIn, user: M.User = Duty, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    n = db.get(M.User, body.next_responsible_id)
    if n is None or n.id == user.id or n.role not in ("duty", "doctor"):
        raise HTTPException(422, "укажите сотрудника, который принимает смену")
    draft = handover_draft(user=user, db=db, cfg=cfg)
    h = M.ShiftHandover(author_id=user.id, next_responsible_id=n.id,
                        data={"open_cases": draft["open_cases"], "waiting": draft["waiting"], "auto_done": draft["done"],
                              "open_cases_note": body.open_cases_note.strip(), "waiting_note": body.waiting_note.strip(),
                              "done_actions": body.done_actions.strip(), "next_steps": body.next_steps.strip()})
    db.add(h)
    db.flush()
    audit.log(db, user, "shift.handover", "shift_handover", h.id, None, to=n.id)
    return _handover_row(db, h)


@router.post("/handover/{hid}/confirm", summary="Принимающий подтверждает приём смены")
def handover_confirm_shift(hid: int, user: M.User = Staff, db: Session = Depends(get_db, scope="function")):
    h = db.get(M.ShiftHandover, hid)
    if h is None:
        raise HTTPException(404, "передача смены не найдена")
    if h.author_id == user.id:
        raise HTTPException(422, "смену подтверждает принимающий сотрудник, а не тот, кто её передаёт")
    if h.confirmed_at:
        raise HTTPException(409, "передача уже подтверждена")
    h.confirmed_by, h.confirmed_at = user.id, clock.now()
    audit.log(db, user, "shift.handover_confirmed", "shift_handover", h.id, None)
    db.flush()
    return _handover_row(db, h)


@router.get("/handovers", summary="Журнал передач смены")
def handovers(user: M.User = Staff, db: Session = Depends(get_db, scope="function")):
    rows = db.execute(select(M.ShiftHandover).order_by(M.ShiftHandover.id.desc()).limit(20)).scalars().all()
    return [_handover_row(db, h) for h in rows]
