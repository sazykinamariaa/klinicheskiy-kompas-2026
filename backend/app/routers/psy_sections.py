"""Психиатр: «Мои пациенты» по категориям, карточка, динамика с «Что изменилось?», клинические рекомендации с решением,
план лечения и наблюдения, сообщения от пациентов. Доступ — только к пациентам с действующим направлением."""
from __future__ import annotations

import json

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, clock, core, models as M, state_builder as SB
from ..config_loader import Config
from ..deps import get_cfg, get_db, require_roles
from .doctor_sections import answer_full, answer_text, brief_data, patient_hints, _active_order

router = APIRouter(prefix="/api/psychiatrist", tags=["Психиатр: разделы"])
Psy = Depends(require_roles("psychiatrist"))

RISK_RULES = {"R-RED-01", "R-RED-02", "R-RED-03", "R-RED-04", "R-ORANGE-01", "PATIENT-NEED-SUPPORT"}
AE_RULES = {"R-RED-05", "R-ORANGE-02", "R-YELLOW-04"}
REF_RU = {"awaiting_acceptance": "ждёт принятия", "accepted": "подтверждён психиатром", "completed": "завершено"}
LEVELS = ("red", "orange", "yellow", "green")
SCALE_RU = {"phq9": "PHQ-9", "gad7": "GAD-7"}
SEV_RU = {"mild": "лёгкое", "moderate": "умеренное", "moderate_to_severe": "выраженное"}
DECISION_RU = {"confirm": "Подтверждено", "modify": "Изменено", "reject": "Отклонено"}


# ---------------------------------------------------------------- доступ

def _referral(db: Session, pid: int) -> Optional[M.Referral]:
    return db.execute(select(M.Referral).where(M.Referral.patient_id == pid, M.Referral.status != "cancelled")
                      .order_by(M.Referral.id.desc())).scalars().first()


def _patients(db: Session) -> List[M.Patient]:
    ids = sorted(set(db.execute(select(M.Referral.patient_id).where(M.Referral.status != "cancelled")).scalars().all()))
    return [db.get(M.Patient, i) for i in ids]


def _patient(db: Session, pid: int) -> M.Patient:
    p = db.get(M.Patient, pid)
    if p is None or _referral(db, pid) is None:
        raise HTTPException(404, "пациент не направлен к психиатру")
    return p


def _open_alerts(db: Session, pid: int) -> List[M.Alert]:
    return db.execute(select(M.Alert).where(M.Alert.patient_id == pid, M.Alert.closed_at.is_(None)).order_by(M.Alert.id.desc())).scalars().all()


def _runs(db: Session, pid: int) -> List[M.ScaleRun]:
    return db.execute(select(M.ScaleRun).where(M.ScaleRun.patient_id == pid, M.ScaleRun.complete.is_(True), M.ScaleRun.completed_at.is_not(None))
                      .order_by(M.ScaleRun.completed_at)).scalars().all()


DX_RU = {"F41.1": "генерализованное тревожное расстройство", "F41.0": "паническое расстройство", "F41.2": "смешанное тревожное и депрессивное расстройство",
         "F32.0": "депрессивный эпизод лёгкой степени", "F32.1": "депрессивный эпизод средней степени", "F33.1": "рекуррентное депрессивное расстройство",
         "F40.1": "социальные фобии", "F41.9": "тревожное расстройство неуточнённое", "F43.9": "реакция на тяжёлый стресс неуточнённая"}


def _dx(db: Session, pid: int) -> Optional[Dict[str, Any]]:
    v = db.execute(select(M.ProfileFieldValue).where(M.ProfileFieldValue.patient_id == pid, M.ProfileFieldValue.field_id == "dx_icd10")
                   .order_by(M.ProfileFieldValue.id.desc())).scalars().first()
    try:
        code = json.loads(v.value) if v and v.value else None
    except (TypeError, ValueError):
        code = v.value if v else None
    return {"code": code, "title": DX_RU.get(code)} if code else None


def _accepted_at(db: Session, rid: int) -> Optional[datetime]:
    e = db.execute(select(M.ReferralEvent).where(M.ReferralEvent.referral_id == rid, M.ReferralEvent.kind == "accepted")
                   .order_by(M.ReferralEvent.at.desc())).scalars().first()
    return e.at if e else None


def _row(p: M.Patient, note: str, at: Optional[datetime] = None) -> Dict[str, Any]:
    return {"patient_id": p.id, "code": p.code, "note": note, "at": at.isoformat() if at else None}


def _level(als: List[M.Alert]) -> str:
    return LEVELS[min([LEVELS.index(a.level) for a in als if a.level in LEVELS] + [3])]


# ---------------------------------------------------------------- «Мои пациенты»

@router.get("/patients", summary="Пациенты психиатра (по направлениям)")
def patients(user: M.User = Psy, db: Session = Depends(get_db, scope="function")):
    out = []
    for p in _patients(db):
        r = _referral(db, p.id)
        out.append({"patient_id": p.id, "code": p.code, "sex": p.sex, "referral_status": REF_RU.get(r.status, r.status),
                    "rule_id": r.rule_id, "level": _level(_open_alerts(db, p.id))})
    out.sort(key=lambda x: LEVELS.index(x["level"]))
    return out


@router.get("/overview", summary="«Мои пациенты»: шесть категорий")
def overview(user: M.User = Psy, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    now = clock.now()
    interval = cfg["monitoring"]["self_report"]["interval_days"]
    new, worse, ae, risk, reassess, overdue, confirmed = [], [], [], [], [], [], []
    for p in _patients(db):
        r = _referral(db, p.id)
        als = _open_alerts(db, p.id)
        if r.status == "awaiting_acceptance":
            new.append(dict(_row(p, "направлен лечащим врачом: " + r.rule_id, r.confirmed_at), referral_id=r.id))
            if r.due_at and r.due_at < now:
                overdue.append(_row(p, "направление не принято в срок", r.due_at))
        if r.status in ("accepted", "completed", "done"):
            dx, o, acc = _dx(db, p.id), _active_order(db, p.id), _accepted_at(db, r.id)
            confirmed.append(_row(p, " · ".join([("диагноз " + dx["code"]) if dx else "диагноз не внесён",
                                                 ("Авиандр с " + o.started_on.strftime("%d.%m.%Y")) if o else "препарат не назначен",
                                                 ("подтверждён " + acc.strftime("%d.%m.%Y")) if acc else "подтверждён"]), acc))
        bad = [a for a in als if a.level in ("red", "orange")]
        if bad:
            worse.append(_row(p, bad[0].title, bad[0].created_at))
        else:
            ser = core.assess_patient(db, cfg, p, persist=False)["dynamics"]["series"]
            if any(s.get("significant_worsening_hint") for s in ser.values()):
                worse.append(_row(p, "по шкалам — заметное ухудшение"))
        aes = db.execute(select(M.AEReport).where(M.AEReport.patient_id == p.id, M.AEReport.created_at >= now - timedelta(days=30))
                         .order_by(M.AEReport.created_at.desc())).scalars().all()
        ae_al = [a for a in als if a.rule_id in AE_RULES]
        if aes:
            ae.append(_row(p, "нежелательное явление: " + ((aes[0].details or {}).get("symptom") or SEV_RU.get(aes[0].severity, aes[0].severity)), aes[0].created_at))
        elif ae_al:
            ae.append(_row(p, ae_al[0].title, ae_al[0].created_at))
        rk = [a for a in als if a.rule_id in RISK_RULES]
        if rk:
            risk.append(_row(p, rk[0].title, rk[0].created_at))
        runs = _runs(db, p.id)
        if not runs or (now - runs[-1].completed_at).days >= interval:
            reassess.append(_row(p, "повторить PHQ-9 и GAD-7: последняя оценка " + (runs[-1].completed_at.strftime("%d.%m.%Y") if runs else "не проводилась")))
        gap = [a for a in als if a.rule_id in ("R-YELLOW-02", "R-YELLOW-03")]
        if gap:
            overdue.append(_row(p, gap[0].title, gap[0].created_at))
    return {"buckets": [
        {"id": "new", "title": "Новые пациенты, направленные терапевтом", "patients": new},
        {"id": "worsening", "title": "Ухудшение симптомов", "patients": worse},
        {"id": "adverse_events", "title": "Новые сообщения о нежелательных явлениях", "patients": ae},
        {"id": "confirmed", "title": "Подтверждённые психиатром / на лечении", "patients": confirmed},
        {"id": "risks", "title": "Сигналы о суицидальных мыслях и других рисках", "patients": risk},
        {"id": "reassessment", "title": "Требуется повторная оценка", "patients": reassess},
        {"id": "overdue", "title": "Просроченные задачи наблюдения", "patients": overdue}]}


@router.get("/patients/{pid}/card", summary="Карточка для психиатра: анамнез, функционирование, лечение, риски, обследования")
def card(pid: int, user: M.User = Psy, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    p = _patient(db, pid)
    b = brief_data(cfg, db, p)
    intake = SB.intake(db, p.id)
    r = _referral(db, p.id)
    cks = db.execute(select(M.Checkin).where(M.Checkin.patient_id == p.id).order_by(M.Checkin.day.desc()).limit(7)).scalars().all()
    sleep = [c.answers.get("c3") for c in cks if (c.answers or {}).get("c3")]
    sf = db.execute(select(M.SafetyFollowup).where(M.SafetyFollowup.patient_id == p.id).order_by(M.SafetyFollowup.id.desc())).scalars().first()
    aes = db.execute(select(M.AEReport).where(M.AEReport.patient_id == p.id).order_by(M.AEReport.created_at.desc())).scalars().all()
    sfq = {q["id"]: q.get("topic") or q["text"] for q in cfg["alert_rules"]["safety_followup"]["questions"]}
    audit.log(db, user, "psy.patient_view", "patient", p.id, p.id)
    return {
        "patient": b["patient"],
        "referral": {"id": r.id, "rule_id": r.rule_id, "status": REF_RU.get(r.status, r.status), "tier": r.tier,
                     "confirmed_at": r.confirmed_at.isoformat(), "due_at": r.due_at.isoformat() if r.due_at else None,
                     "accepted_at": (lambda x: x.isoformat() if x else None)(_accepted_at(db, r.id))},
        "diagnosis": _dx(db, p.id),
        "anamnesis": {"onset": answer_full(cfg, intake, "q2"), "episodes": answer_full(cfg, intake, "q7"),
                      "symptoms": answer_full(cfg, intake, "q1"), "anxiety": answer_full(cfg, intake, "q3"),
                      "panic": answer_full(cfg, intake, "q4"), "sleep_recent": ", ".join(sleep) if sleep else None},
        "functioning": {"impact": answer_full(cfg, intake, "q6")},
        "treatment": {"help": answer_full(cfg, intake, "q9"), "meds": b["somatic"]["meds"], "meds_from_intake": b["somatic"]["meds_from_intake"],
                      "order": b["somatic"]["order"],
                      "ae": [{"at": x.created_at.isoformat(), "severity": SEV_RU.get(x.severity, x.severity), "symptom": (x.details or {}).get("symptom"),
                              "persists": x.persists} for x in aes]},
        "risks": {"suicidal": answer_full(cfg, intake, "q12"),
                  "safety_followup": [{"q": sfq.get(k, k), "a": {"yes": "да", "no": "нет", "unsure": "не уверен(а)"}.get(v, v)} for k, v in (sf.answers or {}).items()] if sf else [],
                  "comorbid": [x for x in [b["somatic"]["chronic"], b["somatic"]["neuro"], b["somatic"]["somatic"]] if x],
                  "substances": answer_full(cfg, intake, "q14"), "family": answer_full(cfg, intake, "q20"),
                  "drug": b["risks"]},
        "exams": {"scales": b["scales"]},
    }


# ---------------------------------------------------------------- «Динамика состояния» и «Что изменилось?»

def _checkins(db: Session, pid: int, days: int = 42) -> List[M.Checkin]:
    since = clock.now().date() - timedelta(days=days)
    return db.execute(select(M.Checkin).where(M.Checkin.patient_id == pid, M.Checkin.day >= since).order_by(M.Checkin.day)).scalars().all()


def _avg(vals: List[Any]) -> Optional[float]:
    v = [x for x in vals if isinstance(x, (int, float))]
    return round(sum(v) / len(v), 1) if v else None


@router.get("/patients/{pid}/dynamics", summary="Динамика: шкалы по датам, сон и настроение, терапия, нежелательные явления, пропуски")
def dynamics(pid: int, user: M.User = Psy, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    p = _patient(db, pid)
    a = core.assess_patient(db, cfg, p, persist=False)
    cks = _checkins(db, p.id)
    o = _active_order(db, p.id)
    aes = db.execute(select(M.AEReport).where(M.AEReport.patient_id == p.id).order_by(M.AEReport.created_at)).scalars().all()
    events = []
    if o:
        events.append({"at": datetime.combine(o.started_on, datetime.min.time()).isoformat(), "label": "Начат Авиандр", "kind": "therapy"})
    events += [{"at": x.created_at.isoformat(), "label": "НЯ: " + ((x.details or {}).get("symptom") or SEV_RU.get(x.severity, x.severity)), "kind": "ae"} for x in aes]
    days = [c.day for c in cks]
    gaps = [{"from": days[i].isoformat(), "to": days[i + 1].isoformat(), "days": (days[i + 1] - days[i]).days - 1}
            for i in range(len(days) - 1) if (days[i + 1] - days[i]).days > 2]
    last = days[-1] if days else None
    if last and (clock.now().date() - last).days > 2:
        gaps.append({"from": last.isoformat(), "to": clock.now().date().isoformat(), "days": (clock.now().date() - last).days})
    interval = cfg["monitoring"]["self_report"]["interval_days"]
    runs = _runs(db, p.id)
    missed = []
    for sid in cfg["monitoring"]["self_report"]["scales"]:
        rs = [r for r in runs if r.scale_id == sid]
        if not rs or (clock.now() - rs[-1].completed_at).days >= interval:
            missed.append(SCALE_RU.get(sid, sid) + (": последняя оценка " + rs[-1].completed_at.strftime("%d.%m.%Y") if rs else ": не заполнялась"))
    return {"patient": {"id": p.id, "code": p.code}, "series": a["dynamics"]["series"], "events": events,
            "checkins": [{"day": c.day.isoformat(), "mood_low": (c.answers or {}).get("c1"), "anxiety": (c.answers or {}).get("c2"),
                          "sleep": (c.answers or {}).get("c3"), "doses": (c.answers or {}).get("c4"), "side_effects": (c.answers or {}).get("c5")} for c in cks],
            "therapy": {"drug": cfg.drug["trade_name"] + " (" + cfg.drug["inn"] + ")", "started_on": o.started_on.isoformat(),
                        "regimen": (o.regimen or {}).get("regimen"), "doctor_changes": (o.regimen or {}).get("doctor_changes")} if o else None,
            "ae": [{"at": x.created_at.isoformat(), "severity": SEV_RU.get(x.severity, x.severity), "symptom": (x.details or {}).get("symptom"), "persists": x.persists} for x in aes],
            "gaps": gaps, "missed_assessments": missed,
            "activity_note": "Отдельного вопроса об активности в ежедневном чек-ине нет: используется отметка о влиянии на повседневные дела (анкета, вопрос 6)."}


@router.get("/patients/{pid}/what-changed", summary="«Что изменилось?»: какие показатели, насколько, за какой период, какие ответы требуют внимания")
def what_changed(pid: int, user: M.User = Psy, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    p = _patient(db, pid)
    hint = cfg["monitoring"]["dynamics_definitions"]["significant_change_ui_hint"]
    need = {"phq9": hint["phq9_points"], "gad7": hint["gad7_points"]}
    lines, attention = [], []
    runs = _runs(db, p.id)
    start = None
    for sid in ("phq9", "gad7"):
        rs = [r for r in runs if r.scale_id == sid]
        if len(rs) < 2:
            if rs:
                lines.append("%s: одно заполнение (%s), сравнивать пока не с чем" % (SCALE_RU[sid], rs[-1].total))
            continue
        a, b = rs[-2], rs[-1]
        d = b.total - a.total
        days = (b.completed_at - a.completed_at).days
        verdict = "заметное ухудшение" if d >= need[sid] else "заметное улучшение" if -d >= need[sid] else "без заметных изменений"
        n = need[sid]
        word = "балл" if n % 10 == 1 and n % 100 != 11 else "балла" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "баллов"
        lines.append("%s: %s → %s (%+d) за %d дн. — %s (ориентир %s %s)" % (SCALE_RU[sid], a.total, b.total, d, days, verdict, n, word))
        start = min(start or a.completed_at, a.completed_at)
        if sid == "phq9" and (b.answers or {}).get("phq9_9", 0) and (b.answers or {}).get("phq9_9", 0) >= 1:
            attention.append("PHQ-9, пункт 9 (мысли о смерти или самоповреждении) = %s в последнем заполнении" % b.answers.get("phq9_9"))
    cks = _checkins(db, p.id, 14)
    cut = clock.now().date() - timedelta(days=7)
    for key, name in (("c1", "Сниженное настроение"), ("c2", "Тревога")):
        prev = _avg([(c.answers or {}).get(key) for c in cks if c.day < cut])
        cur = _avg([(c.answers or {}).get(key) for c in cks if c.day >= cut])
        if prev is not None and cur is not None:
            lines.append("%s по чек-ину (0–10): в среднем %s → %s (неделя к неделе)" % (name, prev, cur))
    for c in cks:
        ans = c.answers or {}
        if ans.get("c6") in ("да", "затрудняюсь ответить"):
            attention.append("%s: мысли о смерти в чек-ине — «%s»" % (c.day.strftime("%d.%m"), ans.get("c6")))
        if ans.get("c5") in ("мешали обычным делам", "сильно мешали"):
            attention.append("%s: неприятные ощущения «%s»" % (c.day.strftime("%d.%m"), ans.get("c5")))
        if ans.get("c4") in ("часть приёмов пропущена", "не принимал(-а)"):
            attention.append("%s: приём лекарства — «%s»" % (c.day.strftime("%d.%m"), ans.get("c4")))
    for al in _open_alerts(db, p.id):
        if al.level in ("red", "orange"):
            attention.append("Открытый сигнал: " + al.title)
    return {"patient": {"id": p.id, "code": p.code}, "period": {"from": start.isoformat() if start else None, "to": clock.now().isoformat()},
            "lines": lines or ["Недостаточно повторных данных для сравнения"], "attention": attention[:12],
            "note": "Ориентиры изменения — из monitoring.json (не диагноз). Оценку проводит врач."}


# ---------------------------------------------------------------- «Клинические рекомендации» с решением психиатра

def _key(it: Dict[str, Any]) -> str:
    return (it["kind"] + ":" + str(it.get("tier")) + ":" + it["found"])[:120]


@router.get("/recommendations", summary="Рекомендации системы по пациентам и решения психиатра")
def recommendations(user: M.User = Psy, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    out = []
    for p in _patients(db):
        items, level = patient_hints(cfg, db, p)
        decs = db.execute(select(M.PsyDecision).where(M.PsyDecision.patient_id == p.id).order_by(M.PsyDecision.id)).scalars().all()
        last = {d.item_key: d for d in decs}
        for it in items:
            it["key"] = _key(it)
            d = last.get(it["key"])
            it["decision"] = {"decision": d.decision, "label": DECISION_RU.get(d.decision, d.decision), "comment": d.comment,
                              "at": d.at.isoformat()} if d else None
        out.append({"patient_id": p.id, "code": p.code, "level": level, "items": items})
    out.sort(key=lambda x: LEVELS.index(x["level"]) if x["level"] in LEVELS else 9)
    return out


class DecisionIn(BaseModel):
    item_key: str = Field(min_length=3, max_length=120)
    decision: str = Field(pattern="^(confirm|modify|reject)$")
    comment: str = Field(default="", max_length=2000)


@router.post("/recommendations/{pid}/decision", summary="Решение психиатра: подтвердить, изменить или отклонить (изменение и отказ — с комментарием)")
def decide(pid: int, body: DecisionIn, user: M.User = Psy, db: Session = Depends(get_db, scope="function")):
    p = _patient(db, pid)
    if body.decision in ("modify", "reject") and len(body.comment.strip()) < 3:
        raise HTTPException(422, "для изменения или отказа нужен комментарий")
    db.add(M.PsyDecision(patient_id=p.id, item_key=body.item_key, decision=body.decision, comment=body.comment.strip(), by=user.id))
    audit.log(db, user, "psy.recommendation_decision", "patient", p.id, p.id, decision=body.decision)
    db.flush()
    return {"ok": True, "label": DECISION_RU[body.decision]}


# ---------------------------------------------------------------- «План лечения и наблюдения»

@router.get("/patients/{pid}/plan", summary="План лечения и наблюдения: план, терапия, переносимость, следующая оценка, цели, визиты, история решений")
def plan(pid: int, user: M.User = Psy, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    from .psy_notes import PsychNote, DECISIONS
    import json as _json
    p = _patient(db, pid)
    mp = db.execute(select(M.MyPlan).where(M.MyPlan.patient_id == p.id).order_by(M.MyPlan.id.desc())).scalars().first()
    labels = {s["id"]: s["label"] for s in cfg["my_plan"]["sections"]}
    sections = []
    if mp and mp.sections:
        try:
            raw = _json.loads(mp.sections) if isinstance(mp.sections, str) else mp.sections
        except ValueError:
            raw = {}
        sections = [{"label": labels.get(k, k), "text": v} for k, v in (raw or {}).items() if v]
    orders = db.execute(select(M.TherapyOrder).where(M.TherapyOrder.patient_id == p.id).order_by(M.TherapyOrder.id)).scalars().all()
    aes = db.execute(select(M.AEReport).where(M.AEReport.patient_id == p.id).order_by(M.AEReport.created_at.desc())).scalars().all()
    goal = db.execute(select(M.Goal).where(M.Goal.patient_id == p.id).order_by(M.Goal.id.desc())).scalars().first()
    visits = db.execute(select(M.Visit).where(M.Visit.patient_id == p.id, M.Visit.at >= clock.now() - timedelta(hours=12)).order_by(M.Visit.at)).scalars().all()
    interval = cfg["monitoring"]["self_report"]["interval_days"]
    runs = _runs(db, p.id)
    next_assessment = (runs[-1].completed_at + timedelta(days=interval)).date().isoformat() if runs else clock.now().date().isoformat()
    props = db.execute(select(M.Proposal).where(M.Proposal.patient_id == p.id, M.Proposal.status.in_(("confirmed", "modified", "rejected")))
                       .order_by(M.Proposal.decided_at)).scalars().all()
    ST = {"confirmed": "подтверждено", "modified": "изменено", "rejected": "отклонено"}
    KIND = {"therapy": "Терапия", "routing": "Направление", "status": "Статус"}
    history = [{"at": x.decided_at.isoformat() if x.decided_at else None, "text": "%s: %s — %s" % (KIND.get(x.kind, x.kind), (x.payload or {}).get("title") or x.key, ST.get(x.status, x.status)),
                "who": "лечащий врач"} for x in props]
    refs = db.execute(select(M.Referral).where(M.Referral.patient_id == p.id)).scalars().all()
    for n in db.execute(select(PsychNote).where(PsychNote.referral_id.in_([r.id for r in refs] or [0])).order_by(PsychNote.ts)).scalars():
        history.append({"at": n.ts.isoformat(), "text": DECISIONS.get(n.decision, n.decision) + (": " + n.comment if n.comment else ""), "who": "психиатр"})
    for d in db.execute(select(M.PsyDecision).where(M.PsyDecision.patient_id == p.id).order_by(M.PsyDecision.at)).scalars():
        history.append({"at": d.at.isoformat(), "text": "Рекомендация системы «%s» — %s%s" % (d.item_key.split(":", 2)[-1], DECISION_RU.get(d.decision, d.decision).lower(), (": " + d.comment) if d.comment else ""), "who": "психиатр"})
    history.sort(key=lambda h: h["at"] or "")
    return {"patient": {"id": p.id, "code": p.code},
            "agreed_plan": {"sections": sections, "confirmed_by_doctor": bool(mp and mp.confirmed_by_doctor)},
            "therapy": [{"drug": cfg.drug["trade_name"] + " (" + cfg.drug["inn"] + ")", "regimen": (o.regimen or {}).get("regimen"), "started_on": o.started_on.isoformat(),
                         "stopped": bool(o.stopped_at), "doctor_changes": (o.regimen or {}).get("doctor_changes")} for o in orders],
            "tolerance": [{"at": x.created_at.isoformat(), "severity": SEV_RU.get(x.severity, x.severity), "symptom": (x.details or {}).get("symptom"), "persists": x.persists} for x in aes],
            "next_assessment": next_assessment, "goal": {"text": goal.text, "by": "пациент" if goal.set_by == p.user_id else "вместе с врачом"} if goal else None,
            "visits": [{"at": v.at.isoformat(), "note": v.note} for v in visits], "history": history}


# ---------------------------------------------------------------- «Сообщения от пациентов»

@router.get("/messages", summary="Сообщения и самоотчёты пациентов между приёмами")
def messages(user: M.User = Psy, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    out = []
    for p in _patients(db):
        msgs = db.execute(select(M.Message).where(M.Message.patient_id == p.id).order_by(M.Message.ts)).scalars().all()
        reads = set(db.execute(select(M.DoctorMark.kind).where(M.DoctorMark.patient_id == p.id, M.DoctorMark.by == user.id,
                                                              M.DoctorMark.kind.like("msg_read:%"))).scalars().all())
        runs = _runs(db, p.id)
        cks = _checkins(db, p.id, 21)
        feed = []
        for i, m in enumerate(msgs):
            mine = m.sender_id == p.user_id
            if not mine:
                continue
            answered = any(x.sender_id != p.user_id and x.ts > m.ts for x in msgs[i + 1:])
            near = [r for r in runs if r.completed_at <= m.ts]
            ck = next((c for c in reversed(cks) if c.day <= m.ts.date()), None)
            ctx = []
            if near:
                ctx.append("%s = %s (%s)" % (SCALE_RU.get(near[-1].scale_id, near[-1].scale_id), near[-1].total, near[-1].completed_at.strftime("%d.%m")))
            if ck:
                ctx.append("чек-ин %s: тревога %s/10, сон — %s" % (ck.day.strftime("%d.%m"), (ck.answers or {}).get("c2", "—"), (ck.answers or {}).get("c3", "—")))
            feed.append({"id": m.id, "kind": "message", "type": "Запрос приёма" if m.kind == "appointment_request" else "Сообщение", "at": m.ts.isoformat(), "text": m.body,
                         "read": ("msg_read:%d" % m.id) in reads, "needs_reply": not answered, "context": ctx})
        for c in cks:
            ans = c.answers or {}
            if ans.get("c5") in ("были, почти не мешали", "мешали обычным делам", "сильно мешали"):
                feed.append({"id": None, "kind": "tolerance", "type": "Переносимость", "at": datetime.combine(c.day, datetime.min.time()).isoformat(),
                             "text": "Неприятные ощущения: " + ans["c5"], "read": True, "needs_reply": False, "context": []})
            if ans.get("c4") in ("часть приёмов пропущена", "не принимал(-а)"):
                feed.append({"id": None, "kind": "missed", "type": "Пропуск приёма", "at": datetime.combine(c.day, datetime.min.time()).isoformat(),
                             "text": "Приём лекарства: " + ans["c4"], "read": True, "needs_reply": False, "context": []})
        for e in db.execute(select(M.AdherenceEvent).where(M.AdherenceEvent.patient_id == p.id, M.AdherenceEvent.kind.in_(("confirmed_missed", "confirmed_missed_partial", "self_discontinuation")))).scalars():
            feed.append({"id": None, "kind": "missed", "type": "Пропуск приёма", "at": datetime.combine(e.day, datetime.min.time()).isoformat(),
                         "text": {"confirmed_missed": "подтверждённый пропуск", "confirmed_missed_partial": "пропущена часть приёмов", "self_discontinuation": "самостоятельная отмена"}[e.kind],
                         "read": True, "needs_reply": False, "context": []})
        for al in _open_alerts(db, p.id):
            if al.level in ("red", "orange"):
                feed.append({"id": None, "kind": "state", "type": "Изменение самочувствия", "at": al.created_at.isoformat(), "text": al.title,
                             "read": True, "needs_reply": False, "context": []})
        feed.sort(key=lambda x: x["at"], reverse=True)
        out.append({"patient_id": p.id, "code": p.code, "unread": sum(1 for f in feed if not f["read"]), "needs_reply": sum(1 for f in feed if f["needs_reply"]),
                    "items": feed[:30]})
    out.sort(key=lambda x: (-x["unread"], x["code"]))
    return out


@router.post("/messages/{mid}/read", summary="Отметить сообщение пациента прочитанным психиатром")
def message_read(mid: int, user: M.User = Psy, db: Session = Depends(get_db, scope="function")):
    m = db.get(M.Message, mid)
    if m is None:
        raise HTTPException(404, "сообщение не найдено")
    _patient(db, m.patient_id)
    key = "msg_read:%d" % m.id
    if not db.execute(select(M.DoctorMark).where(M.DoctorMark.patient_id == m.patient_id, M.DoctorMark.by == user.id, M.DoctorMark.kind == key)).first():
        db.add(M.DoctorMark(patient_id=m.patient_id, kind=key, by=user.id))
        db.flush()
    return {"ok": True}
