"""Пациент: опросники (регулярные и справочные), «Моя цель», «Мои маленькие шаги», приём лекарства."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import ForeignKey, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import audit, clock, core, models as M, state_builder as SB
from ..config_loader import Config
from ..db import Base
from ..deps import get_cfg, get_db, own_patient

router = APIRouter(prefix="/api/patient", tags=["Пациент"])


class PatientPref(Base):
    __tablename__ = "patient_prefs"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    key: Mapped[str] = mapped_column(String(40))
    value: Mapped[str] = mapped_column(String(200), default="")


class GoalIn(BaseModel):
    text: str = Field(min_length=3, max_length=300)


class PrefIn(BaseModel):
    enabled: bool


class DoseIn(BaseModel):
    slot: str = Field(min_length=2, max_length=20)


def _today() -> date:
    return clock.now().date()


def touch_visit(db: Session, p: M.Patient) -> None:
    log = (
        db.query(M.AuditLog)
        .filter(
            M.AuditLog.action == "patient.visit",
            M.AuditLog.patient_id == p.id,
            M.AuditLog.ts >= datetime.combine(_today(), time.min)
        )
        .first()
    )
    if not log:
        audit.log(db, None, "patient.visit", "patient", p.id, p.id)


def _pref(db: Session, pid: int, key: str) -> Optional[str]:
    pref = db.query(PatientPref).filter(PatientPref.patient_id == pid, PatientPref.key == key).first()
    return pref.value if pref else None


def _set_pref(db: Session, pid: int, key: str, value: str) -> None:
    pref = db.query(PatientPref).filter(PatientPref.patient_id == pid, PatientPref.key == key).first()
    if pref:
        pref.value = value
    else:
        db.add(PatientPref(patient_id=pid, key=key, value=value))
    db.flush()


def _active_order(db: Session, pid: int) -> Optional[M.TherapyOrder]:
    return db.query(M.TherapyOrder).filter(
        M.TherapyOrder.patient_id == pid,
        M.TherapyOrder.stopped_at.is_(None)
    ).order_by(M.TherapyOrder.id.desc()).first()


def _cmp(earlier: Optional[int], later: Optional[int], need: int) -> str:
    if earlier is None or later is None:
        return "none"
    d = earlier - later
    if d >= need:
        return "better"
    if -d >= need:
        return "worse"
    return "same"


def _run(db: Session, pid: int) -> List[M.ScaleRun]:
    return db.query(M.ScaleRun).filter(
        M.ScaleRun.patient_id == pid,
        M.ScaleRun.complete.is_(True),
        M.ScaleRun.completed_at.is_not(None)
    ).order_by(M.ScaleRun.completed_at).all()


def _slots(cfg: Config, order: Optional[M.TherapyOrder]) -> List[dict]:
    if order and (order.regimen or {}).get("slots"):
        return order.regimen["slots"]
    return cfg.drug.get("dosing_reference", {}).get("slots", [])


def _taken_today(db: Session, pid: int) -> set:
    rows = db.query(M.AdherenceEvent).filter(M.AdherenceEvent.patient_id == pid, M.AdherenceEvent.day == _today(),
                                             M.AdherenceEvent.kind == "confirmed_taken").all()
    return set(r.reason for r in rows)


@router.get("/methods", summary="Опросники: регулярные и справочные")
def methods(p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    t = cfg["patient_texts"]["methods"]
    sr = cfg["monitoring"]["self_report"]
    interval = sr["interval_days"]
    hint = cfg["monitoring"]["dynamics_definitions"]["significant_change_ui_hint"]
    need = {"phq9": hint["phq9_points"], "gad7": hint["gad7_points"]}
    run = _run(db, p.id)
    regular = []
    for sid in sr["scales"]:
        if sid not in cfg.scales:
            continue
        done = [r for r in run if r.scale_id == sid]
        last = done[-1] if done else None
        next_on = last.completed_at.date() + timedelta(days=interval) if last else None
        due = last is None or _today() >= next_on
        vs_first = _cmp(done[0].total, done[-1].total, need.get(sid, 0)) if len(done) >= 2 else "none"
        vs_prev = _cmp(done[-2].total, done[-1].total, need.get(sid, 0)) if len(done) >= 2 else "none"
        regular.append({
            "id": sid,
            "title": cfg.scales[sid]["title"],
            "count": len(done),
            "last_at": last.completed_at.isoformat() if last else None,
            "next_on": next_on.isoformat() if next_on else None,
            "due": due,
            "vs_first": vs_first,
            "vs_prev": vs_prev,
            "vs_first_text": t["cmp"][vs_first],
            "vs_prev_text": t["cmp"][vs_prev]
        })
    hints = cfg.bindings.get("reference_scale_hints", {})
    intake = SB.intake(db, p.id)
    reference = []
    for sid in ("hcl33", "lsas", "rus_audit"):
        if sid not in cfg.scales or sid not in t["reference"]:
            continue
        h = hints.get(sid) or {}
        q = h.get("question")
        ans = intake.get(q)
        opts = h.get("options", [])
        suggested = (ans in opts) if isinstance(ans, str) else (any(a in opts for a in ans) if isinstance(ans, list) else False)
        reference.append({
            "id": sid,
            "title": t["reference"][sid]["title"],
            "text": t["reference"][sid]["text"],
            "by": t["extra_by_doctor"],
            "suggested": suggested,
            "suggested_text": t["extra_suggested"] if suggested else None,
            "why": t["extra_suggested_why"] if suggested else None
        })
    return {"texts": t, "interval_days": interval, "regular": regular, "source": sr.get("source"), "reference": reference}


@router.get("/goal", summary="«Моя цель»")
def goal_get(p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    g = db.query(M.Goal).filter(M.Goal.patient_id == p.id).order_by(M.Goal.id.desc()).first()
    return {
        "texts": cfg["patient_texts"]["goal"],
        "text": g.text if g else None,
        "by": ("patient" if g.set_by == p.user_id else "doctor") if g else None,
        "at": g.at.isoformat() if g else None
    }


@router.put("/goal", summary="Сформулировать или изменить свою цель")
def goal_put(body: GoalIn, p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    db.add(M.Goal(patient_id=p.id, text=body.text.strip(), set_by=p.user_id))
    audit.log(db, None, "goal.set", "patient", p.id, p.id)
    db.flush()
    return goal_get(p=p, db=db, cfg=cfg)


@router.get("/achievements", summary="«Мои маленькие шаги»")
def achievements(p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    from . import patient as P
    mot = cfg["patient_texts"]["motivation"]
    defs = mot["achievements"]["defs"]
    ui = cfg["patient_texts"]["achievements_ui"]
    phrases = mot.get("phrases", [])
    hidden = _pref(db, p.id, "achievements_hidden") == "1"
    cks = db.query(M.Checkin).filter(M.Checkin.patient_id == p.id).order_by(M.Checkin.day).all()
    ck_days = sorted(set(c.day for c in cks))
    last_ck = cks[-1] if cks else None
    # «не показывать достижения, если пациент отметил „мне тяжело“» (медики): красный экран поддержки,
    # открытый сигнал кнопки «Мне тяжело» или «да» в последнем чек-ине о мыслях о смерти
    need_open = db.query(M.Alert).filter(M.Alert.patient_id == p.id, M.Alert.rule_id == "PATIENT-NEED-SUPPORT",
                                         M.Alert.closed_at.is_(None)).first() is not None
    hard_day = P._support(db, cfg, p)["screen"] == "support_short" or need_open or \
        (last_ck is not None and (last_ck.answers or {}).get("c6") == "да")
    run = _run(db, p.id)
    repeat_scale = max(len([r for r in run if r.scale_id == "phq9"]), len([r for r in run if r.scale_id == "gad7"]))
    total_q = len(cfg["intake_questionnaire"]["questions"])
    intake_finished = 1 if len(SB.intake(db, p.id)) >= total_q else 0
    dates = [r.completed_at.date() for r in run] + ck_days + [p.created_at.date()]
    days_since_start = (_today() - min(dates)).days
    evs = db.query(M.AdherenceEvent).filter(M.AdherenceEvent.patient_id == p.id).all()
    dose_days = len(set([e.day for e in evs if e.kind == "confirmed_taken"] + [c.day for c in cks if (c.answers or {}).get("c4") == "всё принято"]))
    messages_sent = len(db.query(M.Message).filter(M.Message.patient_id == p.id, M.Message.sender_id == p.user_id).all())
    visits = db.query(M.AuditLog).filter(
        M.AuditLog.action == "patient.visit",
        M.AuditLog.patient_id == p.id
    ).all()
    visit_days = len(set(v.ts.date() for v in visits))
    values = {
        "intake_finished": intake_finished,
        "checkin_days": len(ck_days),
        "repeat_scale": repeat_scale,
        "days_since_start": days_since_start,
        "dose_days": dose_days,
        "messages_sent": messages_sent,
        "visit_days": visit_days
    }
    items = []
    for d in defs:
        if d["kind"] == "comeback":
            gap = d.get("gap_days", 3)
            gaps = [((ck_days[i + 1] - ck_days[i]).days > gap) for i in range(len(ck_days) - 1)]
            v = 1 if any(gaps) else 0
        else:
            v = values.get(d["kind"], 0)
        items.append({
            "id": d["id"],
            "title": d["title"],
            "text": d["text"],
            "need": d["need"],
            "done": min(v, d["need"]),
            "earned": v >= d["need"]
        })
    order = _active_order(db, p.id)
    today = {
        "checkin": _today() in ck_days,
        "visit": True,
        "doses": len(_taken_today(db, p.id)),
        "doses_need": len(_slots(cfg, order)) if order else 0
    }
    phrase = phrases[_today().toordinal() % len(phrases)] if phrases else None
    return {
        "enabled": not hidden,
        "visible": not hidden and not hard_day,
        "texts": ui,
        "items": items,
        "today": today,
        "phrase": phrase
    }


@router.put("/achievements", summary="Показать или скрыть раздел «Мои маленькие шаги»")
def achievements_put(body: PrefIn, p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    _set_pref(db, p.id, "achievements_hidden", "0" if body.enabled else "1")
    return achievements(p=p, db=db, cfg=cfg)


@router.get("/medication", summary="Приём лекарства по подтверждённому назначению")
def medication(p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    order = _active_order(db, p.id)
    if not order:
        return {"active": False, "texts": cfg["patient_texts"]["medication"]}
    reg = order.regimen or {}
    taken = _taken_today(db, p.id)
    return {
        "active": True,
        "texts": cfg["patient_texts"]["medication"],
        "drug": cfg.drug["trade_name"] + " (" + cfg.drug["inn"] + ")",
        "regimen": reg.get("regimen"),
        "route": reg.get("route"),
        "with_food": reg.get("with_food"),
        "swallow": reg.get("swallow"),
        "missed_dose": reg.get("missed_dose"),
        "duration": (reg.get("duration") or {}).get("gad"),
        "doctor_changes": reg.get("doctor_changes"),
        "started_on": order.started_on.isoformat(),
        "confirmed_at": order.confirmed_at.isoformat() if order.confirmed_at else None,
        "slots": [{"id": s["id"], "label": s["label"], "taken": s["id"] in taken} for s in _slots(cfg, order)],
        "source": "Назначение врача; схема приёма — ОХЛП, раздел 4.2",
    }


@router.post("/medication/dose", summary="Отметить приём (утро/вечер) по подтверждённому назначению")
def medication_dose(body: DoseIn, p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    order = _active_order(db, p.id)
    if not order:
        raise HTTPException(409, "нет подтверждённого назначения")
    ids = [s["id"] for s in _slots(cfg, order)]
    if body.slot not in ids:
        raise HTTPException(422, "неизвестное время приёма")
    if body.slot not in _taken_today(db, p.id):
        db.add(M.AdherenceEvent(patient_id=p.id, day=_today(), kind="confirmed_taken", reason=body.slot))
        audit.log(db, None, "adherence.dose_marked", "patient", p.id, p.id)
        db.flush()
        core.assess_patient(db, cfg, p, persist=True)
    return medication(p=p, db=db, cfg=cfg)