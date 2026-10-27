"""Приложение пациента: приглашение и согласие, анкета (один вопрос на экран), шкалы, уточняющие вопросы безопасности,
ежедневный чек-ин, кнопка «Мне тяжело», «Мой план», сообщения врачу.

Пациент НИКОГДА не получает названий уровней опасности, номеров правил и красного цвета: только спокойные тексты из patient_texts.json.
До принятия согласия данные не вводятся (deps.own_patient).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import alerts_service as AL, audit, clock, core, models as M, scales as SC, state_builder as SB
from .. import intake_followups as IF
from ..config_loader import Config
from ..deps import TOKEN_TTL_HOURS, get_cfg, get_db, own_patient, require_roles
from ..security import hash_password, new_token, token_hash

public = APIRouter(prefix="/api/public", tags=["Публичное"])
router = APIRouter(prefix="/api/patient", tags=["Пациент"])

CONSENT_VERSION = "stub-0"
SF_VALUES = {"yes", "no", "unsure"}


# ----------------------------------------------------------------------------- приглашение и согласие

def _invitation(db: Session, code: str) -> M.Invitation:
    inv = db.execute(select(M.Invitation).where(M.Invitation.code == code.strip().upper())).scalar_one_or_none()
    if inv is None or inv.accepted_at is not None or inv.expires_at < clock.now():
        raise HTTPException(404, "приглашение недействительно или истекло: попросите врача выпустить новое")
    return inv


@public.get("/invitation/{code}", summary="Экран приглашения: приветствие, зачем опросник, прозрачность данных, текст согласия")
def invitation_info(code: str, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    _invitation(db, code)
    t = cfg["patient_texts"]
    return {"greeting": t["patient_greeting"], "why": t["why_questionnaire"], "privacy": t["privacy_transparency"],
            "consent_text_status": "заглушка: текст согласия на обработку ПДн готовит юридическая часть",
            "consent_version": CONSENT_VERSION}


class AcceptIn(BaseModel):
    consent: bool
    login: str = Field(min_length=3, max_length=60)
    password: str = Field(min_length=8, max_length=100)


@public.post("/invitation/{code}/accept", summary="Принять приглашение: согласие обязательно, затем создаётся учётная запись")
def accept_invitation(code: str, body: AcceptIn, db: Session = Depends(get_db, scope="function")):
    inv = _invitation(db, code)
    if not body.consent:
        raise HTTPException(422, "без согласия на обработку персональных данных продолжить нельзя")
    if db.execute(select(M.User).where(M.User.login == body.login.strip())).first():
        raise HTTPException(409, "логин занят")
    p = db.get(M.Patient, inv.patient_id)
    u = M.User(login=body.login.strip(), password_hash=hash_password(body.password), role="patient", name=p.code)
    db.add(u)
    db.flush()
    p.user_id, p.status = u.id, "active"
    inv.accepted_at = clock.now()
    db.add(M.Consent(patient_id=p.id, version=CONSENT_VERSION, text_status="stub_pending_legal"))
    tok = new_token()
    db.add(M.Token(user_id=u.id, token_hash=token_hash(tok), expires_at=clock.now() + timedelta(hours=TOKEN_TTL_HOURS)))
    audit.log(db, u, "consent.accepted", "patient", p.id, p.id, version=CONSENT_VERSION)
    return {"token": tok, "role": "patient", "patient_id": p.id}


@router.post("/consent/revoke", summary="Отозвать согласие")
def revoke(user: M.User = Depends(require_roles("patient")), db: Session = Depends(get_db, scope="function")):
    p = db.execute(select(M.Patient).where(M.Patient.user_id == user.id)).scalar_one()
    for c in db.execute(select(M.Consent).where(M.Consent.patient_id == p.id, M.Consent.revoked_at.is_(None))).scalars():
        c.revoked_at = clock.now()
    audit.log(db, user, "consent.revoked", "patient", p.id, p.id)
    return {"ok": True}


# ----------------------------------------------------------------------------- главная

def _support(db: Session, cfg: Config, p: M.Patient) -> Dict[str, Any]:
    return AL.patient_support_state(db, cfg, p)


def _needs_safety_followup(db: Session, cfg: Config, p: M.Patient) -> bool:
    a = core.assess_patient(db, cfg, p, persist=False)
    f = a["facts"]
    sf = db.execute(select(M.SafetyFollowup).where(M.SafetyFollowup.patient_id == p.id).order_by(M.SafetyFollowup.id.desc())).scalars().first()
    if sf and sf.complete and sf.completed_at and sf.completed_at.date() == clock.now().date():
        return False
    trig = f.get("intake.q12") in ("recent", "current", "unresolved") or (f.get("phq9_item9") or 0) >= 1 or f.get("phq9_item9_unresolved") is True \
        or f.get("checkin.c6") in ("да", "затрудняюсь ответить")
    return bool(trig)


@router.get("/home", summary="Главный экран пациента")
def home(p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    t = cfg["patient_texts"]
    from .patient_extra import touch_visit
    touch_visit(db, p)  # для «Моих маленьких шагов»: отметка «зашли в приложение», не чаще раза в день
    intake = SB.intake(db, p.id)
    done_q = [q["id"] for q in cfg["intake_questionnaire"]["questions"] if q["id"] in intake]
    all_q = [q["id"] for q in cfg["intake_questionnaire"]["questions"]]
    scales = SC.required_scales(cfg, intake) if len(done_q) == len(all_q) else []
    runs = {r.scale_id: r for r in db.execute(select(M.ScaleRun).where(M.ScaleRun.patient_id == p.id, M.ScaleRun.complete.is_(True))).scalars()}
    goal = db.execute(select(M.Goal).where(M.Goal.patient_id == p.id).order_by(M.Goal.id.desc())).scalars().first()
    unread = db.execute(select(M.Message).where(M.Message.patient_id == p.id, M.Message.sender_id != p.user_id, M.Message.read_at.is_(None))).scalars().all()
    return {
        "support": _support(db, cfg, p),
        "intake": {"answered": len(done_q), "total": len(all_q), "finished": len(done_q) == len(all_q)},
        "scales_to_fill": [s for s in scales if s not in runs],
        "safety_followup_needed": _needs_safety_followup(db, cfg, p) if len(done_q) == len(all_q) else False,
        "checkin_enabled": bool(p.checkin_enabled_on),
        "goal": goal.text if goal else None,
        "unread_messages": len(unread),
        "need_support_button": {"label": cfg["daily_checkin"]["extra_buttons"][0]["label"]},
        "reminder": t["reminders"]["started_not_finished"] if 0 < len(done_q) < len(all_q) else None,
        "disclaimer": t["red_support_screen"]["disclaimer"],
    }


# ----------------------------------------------------------------------------- анкета

@router.get("/intake", summary="Анкета: вопросы и уже данные ответы (один вопрос на экран)")
def intake_get(p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    ans = SB.intake(db, p.id)
    qs = []
    for q in cfg["intake_questionnaire"]["questions"]:
        qs.append({"id": q["id"], "text": q["text"], "type": q["type"], "options": [{"id": o["id"], "label": o["label"]} for o in q.get("options", [])],
                   "exclusive_options": q.get("exclusive_options", []), "free_text_option": q.get("free_text_option"),
                   "fields": q.get("fields"), "answer": ans.get(q["id"]),
                   "followups": [{**f, "answer": ans.get(f["id"])} for f in IF.followups(q)]})
    return {"questions": qs, "ui_rules": cfg["intake_questionnaire"]["_meta"]["ui_rules"]}


class AnswerIn(BaseModel):
    answer: Any


@router.put("/intake/{qid}", summary="Ответ на вопрос анкеты")
def intake_put(qid: str, body: AnswerIn, p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    q = next((x for x in cfg["intake_questionnaire"]["questions"] if x["id"] == qid), None)
    fu = IF.all_followups(cfg).get(qid) if q is None else None
    if fu is not None:  # уточнение к вопросу анкеты (необязательное)
        v = IF.validate(fu, body.answer)
        row = db.execute(select(M.IntakeAnswer).where(M.IntakeAnswer.patient_id == p.id, M.IntakeAnswer.question_id == qid)).scalar_one_or_none()
        if v is None:
            if row:
                db.delete(row)
        elif row:
            row.answer = json.dumps(v, ensure_ascii=False)
        else:
            db.add(M.IntakeAnswer(patient_id=p.id, question_id=qid, answer=json.dumps(v, ensure_ascii=False)))
        audit.log(db, None, "intake.followup", "intake", qid, p.id)
        db.flush()
        core.assess_patient(db, cfg, p, persist=True)
        return {"ok": True, "support": _support(db, cfg, p)}
    if q is None:
        raise HTTPException(404, "нет такого вопроса")
    v = body.answer
    ids = {o["id"] for o in q.get("options", [])}
    if q["type"] == "multi":
        if not isinstance(v, list) or not v or any(x not in ids for x in v):
            raise HTTPException(422, "выберите один или несколько вариантов из списка")
        ex = set(q.get("exclusive_options", []))
        if ex & set(v) and len(set(v)) > 1:
            raise HTTPException(422, "вариант «ничего из перечисленного» нельзя сочетать с другими")
        v = sorted(set(v))
    elif q["type"] == "single":
        if v not in ids:
            raise HTTPException(422, "выберите вариант из списка")
    elif q["type"] in ("single_plus_structured",):
        choice = v.get("choice") if isinstance(v, dict) else v
        if choice not in ids:
            raise HTTPException(422, "выберите вариант из списка")
    elif q["type"] == "structured_list":
        if not isinstance(v, (list, dict)):
            raise HTTPException(422, "ожидается структурированный список")
        if isinstance(v, list):
            for it in v:
                if isinstance(it, dict) and it.get("name"):
                    db.add(M.MedItem(patient_id=p.id, name=str(it["name"])[:160], dose=str(it.get("dose") or "")[:80] or None, source="patient"))
    row = db.execute(select(M.IntakeAnswer).where(M.IntakeAnswer.patient_id == p.id, M.IntakeAnswer.question_id == qid)).scalar_one_or_none()
    if row:
        row.answer = json.dumps(v, ensure_ascii=False)
    else:
        db.add(M.IntakeAnswer(patient_id=p.id, question_id=qid, answer=json.dumps(v, ensure_ascii=False)))
    audit.log(db, None, "intake.answer", "intake", qid, p.id)
    db.flush()
    core.assess_patient(db, cfg, p, persist=True)
    return {"ok": True, "support": _support(db, cfg, p)}


# ----------------------------------------------------------------------------- шкалы

def _scale_public(cfg: Config, sid: str) -> Dict[str, Any]:
    s = cfg.scales.get(sid)
    if not s or s.get("enabled") is False or s.get("administered_by") not in ("patient", None):
        raise HTTPException(404, "шкала недоступна")
    return s


@router.get("/scales/{sid}", summary="Опросник для пациента (без интерпретации и баллов)")
def scale_get(sid: str, p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    s = _scale_public(cfg, sid)
    run = db.execute(select(M.ScaleRun).where(M.ScaleRun.patient_id == p.id, M.ScaleRun.scale_id == sid, M.ScaleRun.complete.is_(False))
                     .order_by(M.ScaleRun.id.desc())).scalars().first()
    return {"id": sid, "title": s["title"], "stem": s.get("stem"), "recall_period": s.get("recall_period"), "answers": s.get("answers"),
            "items": [{k: v for k, v in it.items()} for it in s["items"]], "saved": run.answers if run else {},
            "status": s.get("status"), "license_status": s.get("license_status")}


class ScaleIn(BaseModel):
    answers: Dict[str, Any]
    finish: bool = True


@router.post("/scales/{sid}", summary="Сохранить ответы по шкале (частичные сохраняются без итога)")
def scale_post(sid: str, body: ScaleIn, p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    _scale_public(cfg, sid)
    run = db.execute(select(M.ScaleRun).where(M.ScaleRun.patient_id == p.id, M.ScaleRun.scale_id == sid, M.ScaleRun.complete.is_(False))
                     .order_by(M.ScaleRun.id.desc())).scalars().first()
    merged = dict(run.answers) if run else {}
    merged.update(body.answers)
    try:
        res = SC.score(cfg, sid, merged)
    except SC.ScaleError as e:
        raise HTTPException(422, str(e))
    if run is None:
        run = M.ScaleRun(patient_id=p.id, scale_id=sid)
        db.add(run)
    run.answers = res["answers"]
    run.complete = bool(res["complete"] and body.finish)
    run.total = res["total"] if run.complete else None
    if run.complete:
        run.completed_at = clock.now()
    db.flush()
    audit.log(db, None, "scale.saved", "scale", sid, p.id, complete=run.complete)
    a = core.assess_patient(db, cfg, p, persist=True)
    out = {"ok": True, "complete": run.complete, "answered": res["answered"], "of": res["of"], "support": _support(db, cfg, p),
           "safety_followup_needed": _needs_safety_followup(db, cfg, p)}
    if not res["complete"]:
        out["note"] = cfg["patient_texts"]["reminders"]["started_not_finished"]
    elif run.complete:
        rx = cfg["patient_texts"]["result_explained"]
        out["result"] = {"title": rx["title"], "body": rx["body"], "next_steps_title": rx["next_steps_title"], "next_steps": rx["next_steps"], "closing": rx["closing"]}
    return out


# ----------------------------------------------------------------------------- уточняющие вопросы безопасности

@router.get("/safety-followup", summary="Прямые уточняющие вопросы безопасности (не шкала)")
def sf_get(p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    qs = cfg["alert_rules"]["safety_followup"]["questions"]
    return {"questions": [{"id": q["id"], "text": q["text"], "options": [{"value": v, "label": l} for v, l in zip(("yes", "no", "unsure"), q["options"])]} for q in qs],
            "sf6_when_hint": "если «Да» на вопрос о подготовке, укажите, сколько дней назад это было"}


class SFIn(BaseModel):
    answers: Dict[str, str]
    sf6_days_ago: Optional[int] = Field(default=None, ge=0, le=36500)
    finished: bool = True


@router.post("/safety-followup", summary="Ответы на уточняющие вопросы безопасности")
def sf_post(body: SFIn, p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    ids = {q["id"] for q in cfg["alert_rules"]["safety_followup"]["questions"]}
    for k, v in body.answers.items():
        if k not in ids or v not in SF_VALUES:
            raise HTTPException(422, "ответы: sf1..sf9 со значениями yes | no | unsure")
    row = db.execute(select(M.SafetyFollowup).where(M.SafetyFollowup.patient_id == p.id, M.SafetyFollowup.complete.is_(False))
                     .order_by(M.SafetyFollowup.id.desc())).scalars().first()
    if row is None:
        row = M.SafetyFollowup(patient_id=p.id)
        db.add(row)
    ans = dict(row.answers or {})
    ans.update(body.answers)
    row.answers = ans
    if body.sf6_days_ago is not None:
        row.sf6_days_ago = body.sf6_days_ago
    # блок считается завершённым, только если пациент закончил и ответил на все вопросы
    row.complete = bool(body.finished and ids <= set(ans))
    if row.complete:
        row.completed_at = clock.now()
    db.flush()
    audit.log(db, None, "safety_followup.saved", "safety_followup", row.id, p.id, complete=row.complete)
    core.assess_patient(db, cfg, p, persist=True)
    return {"ok": True, "complete": row.complete, "support": _support(db, cfg, p)}


# ----------------------------------------------------------------------------- чек-ин

@router.get("/checkin", summary="Ежедневный чек-ин")
def checkin_get(p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    if not p.checkin_enabled_on:
        raise HTTPException(409, "чек-ин включает врач")
    today = clock.now().date()
    row = db.execute(select(M.Checkin).where(M.Checkin.patient_id == p.id, M.Checkin.day == today)).scalar_one_or_none()
    dc = cfg["daily_checkin"]
    return {"day": today.isoformat(), "questions": dc["questions"], "saved": row.answers if row else {}, "complete": bool(row and row.complete),
            "can_skip_day": True, "unfinished_text": dc["unfinished"], "extra_buttons": [{"id": b["id"], "label": b["label"]} for b in dc["extra_buttons"]]}


class CheckinIn(BaseModel):
    answers: Dict[str, Any]
    finish: bool = True


@router.post("/checkin", summary="Сохранить чек-ин (можно частично)")
def checkin_post(body: CheckinIn, p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    if not p.checkin_enabled_on:
        raise HTTPException(409, "чек-ин включает врач")
    qs = {q["id"]: q for q in cfg["daily_checkin"]["questions"]}
    for k, v in body.answers.items():
        q = qs.get(k)
        if q is None:
            raise HTTPException(422, "неизвестный вопрос " + k)
        if q["type"] == "scale" and not (isinstance(v, int) and q["min"] <= v <= q["max"]):
            raise HTTPException(422, "%s: число от %d до %d" % (k, q["min"], q["max"]))
        if q["type"] == "single" and v not in q["options"]:
            raise HTTPException(422, "%s: выберите вариант из списка" % k)
    today = clock.now().date()
    row = db.execute(select(M.Checkin).where(M.Checkin.patient_id == p.id, M.Checkin.day == today)).scalar_one_or_none()
    if row is None:
        row = M.Checkin(patient_id=p.id, day=today, answers={})
        db.add(row)
    ans = dict(row.answers or {})
    ans.update(body.answers)
    row.answers = ans
    row.complete = bool(body.finish and set(qs) <= set(ans))
    # приверженность: только подтверждённые ответы пациента
    c4 = body.answers.get("c4")
    if c4:
        kind = qs["c4"]["adherence_fact_mapping"].get(c4)
        if kind in ("confirmed_taken", "confirmed_missed", "confirmed_missed_partial"):
            ex = db.execute(select(M.AdherenceEvent).where(M.AdherenceEvent.patient_id == p.id, M.AdherenceEvent.day == today)).scalars().first()
            if ex:
                ex.kind = kind
            else:
                db.add(M.AdherenceEvent(patient_id=p.id, day=today, kind=kind))
    c5 = body.answers.get("c5")
    if c5 and c5 in qs["c5"]["severity_mapping"]:
        db.add(M.AEReport(patient_id=p.id, severity=qs["c5"]["severity_mapping"][c5], urgent_flag=False, details={"by": "patient", "day": today.isoformat()}))
    db.flush()
    audit.log(db, None, "checkin.saved", "checkin", today.isoformat(), p.id, complete=row.complete)
    core.assess_patient(db, cfg, p, persist=True)
    return {"ok": True, "complete": row.complete, "support": _support(db, cfg, p), "safety_followup_needed": _needs_safety_followup(db, cfg, p),
            "note": None if row.complete else cfg["daily_checkin"]["unfinished"]}


class AdherenceIn(BaseModel):
    kind: str = Field(pattern="^(self_discontinuation|confirmed_missed|confirmed_taken)$")
    reason: Optional[str] = Field(default=None, max_length=500)


@router.post("/adherence", summary="Сообщить о пропуске или самостоятельной отмене препарата")
def adherence(body: AdherenceIn, p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    db.add(M.AdherenceEvent(patient_id=p.id, day=clock.now().date(), kind=body.kind, reason=body.reason))
    audit.log(db, None, "adherence.reported", "patient", p.id, p.id, kind=body.kind)
    db.flush()
    core.assess_patient(db, cfg, p, persist=True)
    return {"ok": True}


# ----------------------------------------------------------------------------- «Мне тяжело»

@router.post("/need-support", summary="Кнопка «Мне тяжело, нужна поддержка»: экран поддержки и оранжевый сигнал врачу")
def need_support(p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    card = {"rule_id": "PATIENT-NEED-SUPPORT", "level": "orange", "title": "Пациент нажал «Мне тяжело, нужна поддержка»",
            "facts_used": {"patient_button": "need_support"},
            "basis": {"source": "daily_checkin.json#extra_buttons.need_support", "status": "approved_by_physician"}}
    AL.sync_alerts(db, cfg, p, {"alerts": [card]})
    audit.log(db, None, "patient.need_support", "patient", p.id, p.id)
    db.flush()
    st = _support(db, cfg, p)
    if st["screen"] == "none":
        st = {"screen": "neutral_support", "text": cfg["patient_texts"]["orange_neutral_screen"]["text"],
              "buttons": [{"id": "call_112", "label": "Позвонить 112", "tel": "112"}, {"id": "call_103", "label": "Позвонить 103", "tel": "103"}],
              "after_hours_notice": None}
    return st


@router.get("/support", summary="Экран поддержки (если он нужен сейчас)")
def support(p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    return _support(db, cfg, p)


@router.get("/support/details", summary="Подробный текст экрана поддержки («Подробнее»)")
def support_details(p: M.Patient = Depends(own_patient), cfg: Config = Depends(get_cfg)):
    t = cfg["patient_texts"]["red_support_screen"]
    return {k: t[k] for k in ("title", "lead", "instructions_title", "instructions", "help_to_call", "closing", "doctor_notified_line", "disclaimer")}


# ----------------------------------------------------------------------------- динамика (мягкие формулировки)

@router.get("/trend", summary="Динамика самочувствия простыми словами, без баллов")
def trend(p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    a = core.assess_patient(db, cfg, p, persist=False)
    tm = cfg["patient_texts"]["trend_messages"]
    ser = a["dynamics"]["series"].get("phq9") or {}
    if len(ser.get("points", [])) < 2:
        return {"message": None, "points_count": len(ser.get("points", []))}
    if ser.get("significant_improvement_hint"):
        msg = tm["improved"]
    elif ser.get("significant_worsening_hint"):
        msg = tm["worse"]
    else:
        msg = tm["unchanged"]
    return {"message": msg, "points_count": len(ser["points"])}


# ----------------------------------------------------------------------------- «Мой план», цель, контакт, сообщения

@router.get("/plan", summary="«Мой план действий»")
def plan_get(p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    return plan_view(db, cfg, p)


def plan_view(db: Session, cfg: Config, p: M.Patient) -> Dict[str, Any]:
    row = db.execute(select(M.MyPlan).where(M.MyPlan.patient_id == p.id).order_by(M.MyPlan.id.desc())).scalars().first()
    secs = json.loads(row.sections) if row and row.sections else {}
    return {"sections": [{"id": s["id"], "label": s["label"], "text": secs.get(s["id"], "")} for s in cfg["my_plan"]["sections"]],
            "version": row.version if row else 0, "confirmed_by_doctor": bool(row and row.confirmed_at),
            "edited_by": row.edited_by if row else None, "rules": cfg["my_plan"]["rules"]}


def plan_save(db: Session, cfg: Config, p: M.Patient, editor: M.User, sections: Dict[str, str]) -> None:
    ids = {s["id"] for s in cfg["my_plan"]["sections"]}
    if any(k not in ids for k in sections):
        raise HTTPException(422, "неизвестный раздел плана")
    row = db.execute(select(M.MyPlan).where(M.MyPlan.patient_id == p.id).order_by(M.MyPlan.id.desc())).scalars().first()
    cur = json.loads(row.sections) if row and row.sections else {}
    cur.update({k: str(v)[:2000] for k, v in sections.items()})
    db.add(M.MyPlan(patient_id=p.id, sections=json.dumps(cur, ensure_ascii=False), version=(row.version + 1) if row else 1, edited_by=editor.id))
    audit.log(db, editor, "plan.edit", "patient", p.id, p.id)


class PlanIn(BaseModel):
    sections: Dict[str, str]


@router.put("/plan", summary="Изменить свой план (врач увидит изменения и подтвердит)")
def plan_put(body: PlanIn, p: M.Patient = Depends(own_patient), user: M.User = Depends(require_roles("patient")),
             db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    plan_save(db, cfg, p, user, body.sections)
    return {"ok": True}


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=3, max_length=40)
    consent: bool


@router.put("/trusted-contact", summary="Доверенный человек для срочной ситуации (по желанию, с согласием)")
def trusted(body: ContactIn, p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function")):
    if not body.consent:
        raise HTTPException(422, "нужно согласие на связь с этим человеком в срочной ситуации")
    row = db.execute(select(M.TrustedContact).where(M.TrustedContact.patient_id == p.id)).scalar_one_or_none()
    if row:
        row.name, row.phone, row.consent = body.name, body.phone, True
    else:
        db.add(M.TrustedContact(patient_id=p.id, name=body.name, phone=body.phone, consent=True))
    audit.log(db, None, "trusted_contact.set", "patient", p.id, p.id)
    return {"ok": True, "note": "Решение о связи с этим человеком принимает врач или дежурный, не система."}


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


@router.get("/messages", summary="Переписка с врачом")
def messages(p: M.Patient = Depends(own_patient), db: Session = Depends(get_db, scope="function")):
    rows = db.execute(select(M.Message).where(M.Message.patient_id == p.id).order_by(M.Message.id)).scalars().all()
    for m in rows:
        if m.sender_id != p.user_id and m.read_at is None:
            m.read_at = clock.now()
    return [{"id": m.id, "mine": m.sender_id == p.user_id, "body": m.body, "kind": m.kind, "ts": m.ts.isoformat()} for m in rows]


@router.post("/messages", summary="Написать врачу (не для срочной помощи: срочное — 112 / 103)")
def send_message(body: MessageIn, p: M.Patient = Depends(own_patient), user: M.User = Depends(require_roles("patient")), db: Session = Depends(get_db, scope="function")):
    db.add(M.Message(patient_id=p.id, sender_id=user.id, body=body.body))
    audit.log(db, None, "message.sent", "patient", p.id, p.id)
    return {"ok": True, "note": "Сообщение не для срочной помощи. Если нужна помощь прямо сейчас, позвоните 112 или 103."}


@router.post("/appointment-request", summary="Запросить приём")
def appointment(body: MessageIn, p: M.Patient = Depends(own_patient), user: M.User = Depends(require_roles("patient")), db: Session = Depends(get_db, scope="function")):
    db.add(M.Message(patient_id=p.id, sender_id=user.id, body=body.body, kind="appointment_request"))
    audit.log(db, None, "appointment.requested", "patient", p.id, p.id)
    return {"ok": True}
