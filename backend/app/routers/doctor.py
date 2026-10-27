"""Кабинет врача: пациенты, карточка, клинический профиль, предложения системы и решения врача."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import segno
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import alerts_service as AL, audit, clock, core, facts as F, models as M, proposals as PR, state_builder as SB
from .. import intake_followups as IF
from ..config_loader import Config
from ..deps import get_cfg, get_db, patient_for_doctor, require_roles
from ..security import new_invite_code

router = APIRouter(prefix="/api/doctor", tags=["Врач"])
Doctor = Depends(require_roles("doctor"))


class PatientIn(BaseModel):
    code: str = Field(min_length=1, max_length=80, description="код или псевдоним пациента")
    sex: str = Field(pattern="^(м|ж)$")
    birth_date: str = Field(description="ГГГГ-ММ-ДД")
    origin: Optional[str] = Field(default=None, max_length=200, description="адрес приложения для QR-кода, например http://192.168.1.10:8000")


@router.post("/patients", summary="Создать пустую карточку пациента и приглашение (код + QR)")
def create_patient(body: PatientIn, user: M.User = Doctor, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    try:
        bd = date.fromisoformat(body.birth_date)
    except ValueError:
        raise HTTPException(422, "дата рождения в формате ГГГГ-ММ-ДД")
    if bd > clock.now().date():
        raise HTTPException(422, "дата рождения в будущем")
    if db.execute(select(M.Patient).where(M.Patient.doctor_id == user.id, M.Patient.code == body.code)).first():
        raise HTTPException(409, "пациент с таким кодом уже есть")
    p = M.Patient(code=body.code, sex=body.sex, birth_date=body.birth_date, doctor_id=user.id, status="invited")
    db.add(p)
    db.flush()
    inv = M.Invitation(patient_id=p.id, code=new_invite_code(), expires_at=clock.now() + timedelta(days=7))
    db.add(inv)
    audit.log(db, user, "patient.create", "patient", p.id, p.id)
    return {"patient_id": p.id, **_invite_payload(inv, body.origin)}


def _invite_payload(inv: M.Invitation, origin: Optional[str] = None) -> Dict[str, Any]:
    import re
    url = "/#/join/%s" % inv.code
    full = origin.rstrip("/") + url if origin and re.fullmatch(r"https?://[A-Za-z0-9.\-\[\]:]+/?", origin) else url
    qr = segno.make(full, error="m")
    return {"invite_code": inv.code, "invite_url_path": url, "expires_at": inv.expires_at.isoformat(), "qr_svg": qr.svg_inline(scale=4, border=1)}


@router.post("/patients/{patient_id}/invitation", summary="Выпустить приглашение заново")
def reissue(patient: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function")):
    if patient.user_id:
        raise HTTPException(409, "пациент уже принял приглашение")
    for old in db.execute(select(M.Invitation).where(M.Invitation.patient_id == patient.id, M.Invitation.accepted_at.is_(None))).scalars():
        old.expires_at = clock.now()
    inv = M.Invitation(patient_id=patient.id, code=new_invite_code(), expires_at=clock.now() + timedelta(days=7))
    db.add(inv)
    audit.log(db, user, "invitation.reissue", "patient", patient.id, patient.id)
    return _invite_payload(inv)


@router.get("/patients", summary="Мои пациенты: поиск, фильтры")
def list_patients(q: Optional[str] = None, level: Optional[str] = Query(None, pattern="^(red|orange|yellow|green)$"),
                  status: Optional[str] = None, user: M.User = Doctor, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    stmt = select(M.Patient).where(M.Patient.doctor_id == user.id)
    if q:
        stmt = stmt.where(M.Patient.code.ilike("%" + q.strip() + "%"))
    if status:
        stmt = stmt.where(M.Patient.status == status)
    rows = db.execute(stmt.order_by(M.Patient.id)).scalars().all()
    order = {"red": 3, "orange": 2, "yellow": 1}
    now = clock.now()
    out = []
    for p in rows:
        alerts = db.execute(select(M.Alert).where(M.Alert.patient_id == p.id, M.Alert.closed_at.is_(None))).scalars().all()
        top = max((a.level for a in alerts), key=lambda l: order.get(l, 0), default="green")
        if level and top != level:
            continue
        pend = db.execute(select(func.count()).select_from(M.Proposal).where(M.Proposal.patient_id == p.id, M.Proposal.status == "pending")).scalar()
        lead = max(alerts, key=lambda a: (order.get(a.level, 0), a.created_at), default=None)
        last_run = db.execute(select(func.max(M.ScaleRun.completed_at)).where(M.ScaleRun.patient_id == p.id)).scalar()
        last_msg = db.execute(select(func.max(M.Message.ts)).where(M.Message.patient_id == p.id, M.Message.sender_id == p.user_id)).scalar()
        last = max([t for t in (last_run, last_msg) if t], default=None)
        reason = lead.title if lead else ("Есть предложения системы, ждут вашего решения" if pend else "Без срочных сигналов")
        out.append({"id": p.id, "code": p.code, "sex": p.sex, "status": p.status, "level": top, "open_alerts": len(alerts), "pending_proposals": pend,
                    "reason": reason, "days_since_activity": (now - last).days if last else None})
    out.sort(key=lambda r: (-order.get(r["level"], 0), -r["pending_proposals"], -(r["days_since_activity"] if r["days_since_activity"] is not None else 999)))
    return out


def _fields_view(db: Session, cfg: Config, patient: M.Patient) -> List[Dict[str, Any]]:
    cur: Dict[str, M.ProfileFieldValue] = {}
    for r in db.execute(select(M.ProfileFieldValue).where(M.ProfileFieldValue.patient_id == patient.id).order_by(M.ProfileFieldValue.id)).scalars():
        cur[r.field_id] = r
    out = []
    for fid, f in cfg.profile_fields.items():
        r = cur.get(fid)
        out.append({"id": fid, "label": f["label"], "type": f["type"], "options": f.get("options"), "note": f.get("note"), "effect": f.get("effect"),
                    "by": f.get("by"), "value": json.loads(r.value) if r and r.value is not None else None,
                    "entered_by": r.entered_by if r else None, "entered_at": r.entered_at.isoformat() if r else None,
                    "state": ("known" if r and r.value not in (None, "unknown", "null", '"unknown"') else "unknown") if f["type"] != "system_generated" else "system"})
    return out


@router.get("/patients/{patient_id}/card", summary="Карточка пациента: сводка, предупреждения, предложения (одна сводка на экран)")
def card(patient: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    a = core.assess_patient(db, cfg, patient, persist=True)
    alerts = db.execute(select(M.Alert).where(M.Alert.patient_id == patient.id, M.Alert.closed_at.is_(None)).order_by(M.Alert.id.desc())).scalars().all()
    alerts_all = db.execute(select(M.Alert).where(M.Alert.patient_id == patient.id).order_by(M.Alert.id)).scalars().all()
    proposals = db.execute(select(M.Proposal).where(M.Proposal.patient_id == patient.id, M.Proposal.status == "pending").order_by(M.Proposal.id)).scalars().all()
    orders = db.execute(select(M.TherapyOrder).where(M.TherapyOrder.patient_id == patient.id)).scalars().all()
    refs = db.execute(select(M.Referral).where(M.Referral.patient_id == patient.id)).scalars().all()
    goal = db.execute(select(M.Goal).where(M.Goal.patient_id == patient.id).order_by(M.Goal.id.desc())).scalars().first()
    intake = SB.intake(db, patient.id)
    return {
        "patient": {"id": patient.id, "code": patient.code, "sex": patient.sex, "birth_date": patient.birth_date, "status": patient.status,
                    "age": a["facts"].get("profile.age"), "checkin_enabled_on": patient.checkin_enabled_on.isoformat() if patient.checkin_enabled_on else None,
                    "synthetic": patient.synthetic},
        "level": a["level"],
        "alerts": [{"id": x.id, "rule_id": x.rule_id, "level": x.level, "title": x.title, "status": x.status, "created_at": x.created_at.isoformat(),
                    "accepted": bool(x.accepted_at), "after_hours": x.after_hours, "basis": x.basis, "facts": x.facts} for x in alerts],
        "assessment": {"hypothesis": a["hypothesis"], "routing": a["routing"], "drug_check": a["drug_check"], "therapy_suggestion": a["therapy_suggestion"],
                       "status_suggestions": a["status_suggestions"], "amplifiers": a["amplifiers"], "unevaluated": a["unevaluated"]},
        "proposals": [_prop(x) for x in proposals],
        "dynamics": a["dynamics"],
        "timeline_events": ([{"at": datetime.combine(o.started_on, datetime.min.time()).isoformat(), "kind": "therapy", "label": "Начало терапии"} for o in orders]
                            + [{"at": x.created_at.isoformat(), "kind": "alert", "level": x.level, "label": x.title} for x in alerts_all]),
        "schedule": a["schedule"], "adherence": a["adherence"],
        "profile_fields": _fields_view(db, cfg, patient),
        "intake": _intake_view(cfg, intake),
        "orders": [{"id": o.id, "drug": o.drug_id, "regimen": o.regimen, "started_on": o.started_on.isoformat(), "stopped": bool(o.stopped_at)} for o in orders],
        "referrals": [{"id": r.id, "rule_id": r.rule_id, "kind": r.kind, "tier": r.tier, "status": r.status, "due_at": r.due_at.isoformat() if r.due_at else None} for r in refs],
        "goal": goal.text if goal else None,
        "scales_to_offer": __import__("app.scales", fromlist=["x"]).required_scales(cfg, intake),
    }


def _prop(x: M.Proposal) -> Dict[str, Any]:
    return {"id": x.id, "kind": x.kind, "key": x.key, "status": x.status, "payload": x.payload, "basis": x.basis, "state": "ожидает подтверждения врача",
            "created_at": x.created_at.isoformat()}


def _intake_view(cfg: Config, intake: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for q in cfg["intake_questionnaire"]["questions"]:
        if q["id"] not in intake:
            continue
        from .doctor_sections import answer_text  # noqa: E402 — общий текст ответа
        out.append({"id": q["id"], "text": q["text"], "answer": [answer_text(cfg, q["id"], intake[q["id"]]) or "—"],
                    "details": IF.details(cfg, intake, q["id"])})
    return out


class FieldIn(BaseModel):
    value: Any = None


@router.put("/patients/{patient_id}/profile/{field_id}", summary="Внести клинический факт (три состояния: да / нет / неизвестно)")
def set_field(field_id: str, body: FieldIn, patient: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor,
              db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    f = cfg.profile_fields.get(field_id)
    if f is None:
        raise HTTPException(404, "неизвестное поле профиля")
    if f["type"] == "system_generated":
        raise HTTPException(409, "поле формируется системой")
    v = body.value
    if f["type"] == "tri_state":
        if v not in ("yes", "no", "unknown", None):
            raise HTTPException(422, "значение: yes | no | unknown")
        v = v or "unknown"
    if f["type"] == "text":
        v = (str(v).strip()[:500] or None) if v is not None else None
    if f["type"] == "single" and f.get("options") and v not in f["options"] and v is not None:
        raise HTTPException(422, "допустимо: " + ", ".join(f["options"]))
    if field_id == "egfr_ml_min" and v is not None:
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise HTTPException(422, "СКФ — число")
        if not (0 < v < 250):
            raise HTTPException(422, "СКФ вне допустимого диапазона")
    if field_id == "dx_icd10" and v:
        import re
        if not re.match(r"^[A-Za-z]\d{2}(\.\d{1,2})?$", str(v).strip()):
            raise HTTPException(422, "код МКБ-10 в формате F41.1")
        v = str(v).strip().upper()
    if field_id == "maoi_last_dose_date" and v not in (None, "none"):
        try:
            date.fromisoformat(str(v))
        except ValueError:
            raise HTTPException(422, "дата ГГГГ-ММ-ДД или none (не принимал)")
    db.add(M.ProfileFieldValue(patient_id=patient.id, field_id=field_id, value=json.dumps(v, ensure_ascii=False), entered_by=user.id))
    audit.log(db, user, "profile.set", "profile_field", field_id, patient.id)
    db.flush()
    a = core.assess_patient(db, cfg, patient, persist=True)
    return {"ok": True, "level": a["level"], "drug_state": a["drug_check"]["state"]}


class SymptomIn(BaseModel):
    name: str
    present: str = Field(pattern="^(yes|no|unknown)$")
    duration_weeks: Optional[float] = Field(default=None, ge=0, le=2600)


@router.put("/patients/{patient_id}/symptoms", summary="Симптом и «как давно»")
def set_symptom(body: SymptomIn, patient: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function"),
                cfg: Config = Depends(get_cfg)):
    known = set(cfg["routing_rules"]["symptom_criteria"]["depressive_episode_possible"]["main"] + cfg["routing_rules"]["symptom_criteria"]["depressive_episode_possible"]["additional"]
                + cfg["routing_rules"]["symptom_criteria"]["gad_possible"]["at_least_one_autonomic"]
                + cfg.bindings["symptom_map"]["gad_symptom_pool"]["other"])
    if body.name not in known:
        raise HTTPException(422, "симптом отсутствует в справочнике критериев")
    db.add(M.SymptomEntry(patient_id=patient.id, name=body.name, present=body.present, duration_weeks=body.duration_weeks, entered_by=user.id))
    audit.log(db, user, "symptom.set", "symptom", body.name, patient.id)
    db.flush()
    core.assess_patient(db, cfg, patient, persist=True)
    return {"ok": True}


@router.get("/symptom-catalog", summary="Справочник симптомов для профиля")
def symptom_catalog(user: M.User = Doctor, cfg: Config = Depends(get_cfg)):
    c = cfg["routing_rules"]["symptom_criteria"]
    return {"depressive": {"main": c["depressive_episode_possible"]["main"], "additional": c["depressive_episode_possible"]["additional"]},
            "gad": {"autonomic": c["gad_possible"]["at_least_one_autonomic"], "other": cfg.bindings["symptom_map"]["gad_symptom_pool"]["other"],
                    "status": cfg.bindings["symptom_map"]["gad_symptom_pool"]["status"]}}


class MedIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    dose: Optional[str] = None


@router.post("/patients/{patient_id}/meds", summary="Добавить принимаемый препарат (врач подтверждает список)")
def add_med(body: MedIn, patient: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    m = M.MedItem(patient_id=patient.id, name=body.name.strip(), dose=body.dose, source="doctor", confirmed_by_doctor=False)
    db.add(m)
    # изменение списка сбрасывает «список проверен врачом»
    db.add(M.ProfileFieldValue(patient_id=patient.id, field_id="meds_confirmed", value=json.dumps("unknown"), entered_by=user.id))
    audit.log(db, user, "med.add", "med", body.name, patient.id)
    db.flush()
    core.assess_patient(db, cfg, patient, persist=True)
    return {"ok": True, "id": m.id, "note": "Список препаратов изменён: подтвердите его (поле «Список принимаемых препаратов проверен врачом»)."}


@router.delete("/patients/{patient_id}/meds/{med_id}", summary="Убрать препарат из списка")
def del_med(med_id: int, patient: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    m = db.get(M.MedItem, med_id)
    if not m or m.patient_id != patient.id:
        raise HTTPException(404, "не найдено")
    m.active = False
    db.add(M.ProfileFieldValue(patient_id=patient.id, field_id="meds_confirmed", value=json.dumps("unknown"), entered_by=user.id))
    audit.log(db, user, "med.remove", "med", m.name, patient.id)
    db.flush()
    core.assess_patient(db, cfg, patient, persist=True)
    return {"ok": True}


@router.get("/patients/{patient_id}/meds", summary="Список препаратов пациента")
def list_meds(patient: M.Patient = Depends(patient_for_doctor), db: Session = Depends(get_db, scope="function")):
    return [{"id": m.id, "name": m.name, "dose": m.dose, "source": m.source} for m in
            db.execute(select(M.MedItem).where(M.MedItem.patient_id == patient.id, M.MedItem.active.is_(True))).scalars()]


class FlagIn(BaseModel):
    value: bool


@router.put("/patients/{patient_id}/flags/{flag}", summary="Клинический флаг врача (непосредственная угроза / подозрение на вторичную причину)")
def set_flag(flag: str, body: FlagIn, patient: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    if flag not in ("immediate_threat", "secondary_cause_suspected"):
        raise HTTPException(404, "неизвестный флаг")
    db.add(M.ClinicianFlag(patient_id=patient.id, flag=flag, value=body.value, set_by=user.id))
    audit.log(db, user, "flag.set", "flag", flag, patient.id, value=body.value)
    db.flush()
    a = core.assess_patient(db, cfg, patient, persist=True)
    return {"ok": True, "level": a["level"]}


class AEIn(BaseModel):
    severity: str = Field(pattern="^(mild|moderate|moderate_to_severe)$")
    urgent_flag: bool = False
    persists: Optional[bool] = None
    worsening: Optional[bool] = None
    symptoms: List[str] = []
    note: Optional[str] = None


@router.post("/patients/{patient_id}/ae", summary="Зафиксировать нежелательное явление")
def add_ae(body: AEIn, patient: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    db.add(M.AEReport(patient_id=patient.id, severity=body.severity, urgent_flag=body.urgent_flag, persists=body.persists, worsening=body.worsening,
                      details={"symptoms": body.symptoms, "symptom": (body.symptoms or [None])[0], "note": body.note, "by": "doctor"}))
    audit.log(db, user, "ae.add", "ae", None, patient.id, severity=body.severity, urgent=body.urgent_flag)
    db.flush()
    a = core.assess_patient(db, cfg, patient, persist=True)
    return {"ok": True, "level": a["level"]}


@router.get("/ae-catalog", summary="Справочник нежелательных явлений препарата")
def ae_catalog(user: M.User = Doctor, cfg: Config = Depends(get_cfg)):
    ae = cfg.drug["adverse_events"]
    return {"standard_questions": ae["questions_for_checkin_standard"], "extended": ae["extended"], "severity": ae["severity"],
            "tell_doctor_immediately": ae["frequency_scheme"]["uncommon_tell_doctor_immediately"], "reporting": ae["reporting"],
            "status": ae["status"]}


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(confirm|modify|reject)$")
    reason: Optional[str] = None
    changes: Optional[Dict[str, Any]] = None


@router.get("/patients/{patient_id}/proposals", summary="Предложения системы по пациенту")
def proposals(patient: M.Patient = Depends(patient_for_doctor), status: Optional[str] = None, db: Session = Depends(get_db, scope="function")):
    stmt = select(M.Proposal).where(M.Proposal.patient_id == patient.id)
    if status:
        stmt = stmt.where(M.Proposal.status == status)
    return [dict(_prop(x), status=x.status, reason=x.reason) for x in db.execute(stmt.order_by(M.Proposal.id)).scalars()]


class AEUpdateIn(BaseModel):
    persists: bool


@router.put("/patients/{patient_id}/ae/{ae_id}", summary="Изменить нежелательное явление: сохраняется или прошло")
def update_ae(ae_id: int, body: AEUpdateIn, patient: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor,
              db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    r = db.get(M.AEReport, ae_id)
    if r is None or r.patient_id != patient.id:
        raise HTTPException(404, "нежелательное явление не найдено")
    r.persists = body.persists
    audit.log(db, user, "ae.update", "ae", r.id, patient.id, persists=body.persists)
    db.flush()
    core.assess_patient(db, cfg, patient, persist=True)
    return {"ok": True}


@router.post("/proposals/{proposal_id}/decision", summary="Решение врача по предложению: подтвердить / изменить / отклонить (причина обязательна)")
def decide(proposal_id: int, body: DecisionIn, user: M.User = Doctor, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    p = db.get(M.Proposal, proposal_id)
    if p is None:
        raise HTTPException(404, "предложение не найдено")
    try:
        PR.decide(db, cfg, p, user, body.decision, body.reason, body.changes)
    except PR.ProposalError as e:
        raise HTTPException(e.status, str(e))
    return {"ok": True, "status": p.status}


class CheckinIn(BaseModel):
    enabled: bool


@router.put("/patients/{patient_id}/checkin", summary="Включить или выключить ежедневный чек-ин")
def checkin_toggle(body: CheckinIn, patient: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function")):
    patient.checkin_enabled_on = clock.now().date() if body.enabled else None
    audit.log(db, user, "checkin.toggle", "patient", patient.id, patient.id, enabled=body.enabled)
    return {"ok": True, "enabled_on": patient.checkin_enabled_on.isoformat() if patient.checkin_enabled_on else None}


class GoalIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@router.put("/patients/{patient_id}/goal", summary="«Моя цель»: задаёт врач вместе с пациентом")
def set_goal(body: GoalIn, patient: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function")):
    db.add(M.Goal(patient_id=patient.id, text=body.text, set_by=user.id))
    audit.log(db, user, "goal.set", "patient", patient.id, patient.id)
    return {"ok": True}


@router.get("/patients/{patient_id}/summary", summary="Сводка для психиатра (JSON) по текущим данным")
def summary(patient: M.Patient = Depends(patient_for_doctor), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    from ..summary import build_summary
    a = core.assess_patient(db, cfg, patient, persist=False)
    return build_summary(db, cfg, patient, a)


@router.get("/inbox", summary="Что требует внимания: алерты и предложения по всем моим пациентам")
def inbox(user: M.User = Doctor, db: Session = Depends(get_db, scope="function")):
    pats = {p.id: p for p in db.execute(select(M.Patient).where(M.Patient.doctor_id == user.id)).scalars()}
    alerts = db.execute(select(M.Alert).where(M.Alert.patient_id.in_(list(pats) or [0]), M.Alert.closed_at.is_(None)).order_by(M.Alert.id.desc())).scalars().all()
    order = {"red": 0, "orange": 1, "yellow": 2}
    alerts.sort(key=lambda a: (order.get(a.level, 9), -a.id))
    props = db.execute(select(M.Proposal).where(M.Proposal.patient_id.in_(list(pats) or [0]), M.Proposal.status == "pending")).scalars().all()
    return {"alerts": [{"id": a.id, "patient_id": a.patient_id, "patient": pats[a.patient_id].code, "level": a.level, "title": a.title, "status": a.status,
                        "created_at": a.created_at.isoformat(), "accepted": bool(a.accepted_at)} for a in alerts],
            "pending_proposals": [{"id": p.id, "patient_id": p.patient_id, "patient": pats[p.patient_id].code, "kind": p.kind, "key": p.key} for p in props]}
