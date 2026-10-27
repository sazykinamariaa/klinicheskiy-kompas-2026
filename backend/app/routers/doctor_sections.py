"""Разделы врача (обратная связь медиков): «Мои пациенты» по категориям и краткая карточка пациента."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, clock, core, intake_followups as IF, models as M, state_builder as SB
from ..config_loader import Config
from ..deps import get_cfg, get_db, patient_for_doctor, require_roles
from ..summary import _labels

router = APIRouter(prefix="/api/doctor", tags=["Врач: разделы"])
Doctor = Depends(require_roles("doctor"))

BRIEF_INTAKE = ["q1", "q3", "q4", "q5", "q8", "q12", "q13", "q14", "q16", "q19", "q20", "q21"]
BRIEF_SHORT = {"q1": "Изменения самочувствия", "q3": "Как проявляется тревога", "q4": "Внезапные приступы страха", "q5": "Избегаемые ситуации",
               "q8": "Периоды повышенного настроения или активности", "q12": "Мысли о смерти или самоповреждении", "q13": "Связь с менструальным циклом",
               "q14": "Алкоголь, никотин, другие вещества", "q16": "Голоса, убеждения о преследовании", "q19": "Навязчивости, пережитая травма", "q20": "Семейный анамнез",
               "q21": "Есть кого позвать на помощь"}


def answer_text(cfg: Config, qid: str, a: Any) -> Optional[str]:
    q = cfg.intake_q.get(qid)
    if q is None or a is None:
        return None
    if q.get("type") == "structured_list":
        if isinstance(a, list) and len(a) > 0:
            return "; ".join(m.get("name", "") + (" — " + m["dose"] if m.get("dose") else "") for m in a)
        else:
            return "ничего не принимает"
    if isinstance(a, dict):
        labels = [_clean(x) for x in _labels(cfg, qid, a.get("choice"))]
        return ", ".join(labels) + (": " + a.get("text") if a.get("text") else "")
    return "; ".join(_clean(x) for x in _labels(cfg, qid, a)) or str(a)


def answer_full(cfg: Config, intake: Dict[str, Any], qid: str) -> Optional[str]:
    """Ответ на вопрос анкеты вместе с уточнениями пациента."""
    a = answer_text(cfg, qid, intake.get(qid))
    det = IF.details(cfg, intake, qid)
    if a is None or not det:
        return a
    return a + " (" + "; ".join(d["q"] + ": " + d["a"] for d in det) + ")"


def _clean(label: str) -> str:
    """Подпись варианта для врача: без «(уточните)» и точки в конце."""
    return label.replace(" (уточните)", "").replace(" (укажите какие)", "").replace(" (укажите)", "").rstrip(".").strip()


def _my_patients(db: Session, user: M.User) -> List[M.Patient]:
    return db.execute(select(M.Patient).where(M.Patient.doctor_id == user.id, M.Patient.status != "archived")).scalars().all()


def _active_order(db: Session, pid: int) -> Optional[M.TherapyOrder]:
    return db.execute(select(M.TherapyOrder).where(M.TherapyOrder.patient_id == pid, M.TherapyOrder.stopped_at.is_(None)).order_by(M.TherapyOrder.id.desc())).scalars().first()


def _intake_progress(cfg: Config, db: Session, pid: int) -> Dict[str, int]:
    intake = SB.intake(db, pid)
    answered = len(set(intake.keys()).intersection(cfg.intake_q.keys()))
    return {"answered": answered, "total": len(cfg.intake_q)}


def _reviewed(db: Session, pid: int) -> bool:
    return db.execute(select(M.DoctorMark.id).where(M.DoctorMark.patient_id == pid, M.DoctorMark.kind == "intake_reviewed")).first() is not None


def _row(p: M.Patient, note: str, at: Optional[datetime] = None) -> Dict[str, Any]:
    return {"patient_id": p.id, "code": p.code, "sex": p.sex, "note": note, "at": at.isoformat() if at else None}


@router.get("/overview", summary="«Мои пациенты»: пять категорий со списками")
def overview(user: M.User = Doctor, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    pats = _my_patients(db, user)
    now = clock.now()
    on_treatment, new_intake, worsening, referrals, visits = [], [], [], [], []
    for p in pats:
        o = _active_order(db, p.id)
        if o:
            weeks = (now.date() - o.started_on).days // 7
            on_treatment.append(_row(p, "Авиандр с " + o.started_on.strftime("%d.%m.%Y") + " · неделя " + str(weeks)))
        pr = _intake_progress(cfg, db, p.id)
        if 0 < pr["answered"] < pr["total"]:
            new_intake.append(_row(p, "заполняет анкету: %d из %d" % (pr["answered"], pr["total"])))
        elif pr["answered"] >= pr["total"] and not _reviewed(db, p.id):
            new_intake.append(_row(p, "анкета заполнена, ещё не просмотрена"))
        alerts = db.execute(select(M.Alert).where(M.Alert.patient_id == p.id, M.Alert.closed_at.is_(None), M.Alert.level.in_(("red", "orange")))
                            .order_by(M.Alert.id.desc())).scalars().all()
        if alerts:
            worsening.append(_row(p, alerts[0].title, alerts[0].created_at))
        else:
            ser = core.assess_patient(db, cfg, p, persist=False)["dynamics"]["series"]
            if any(s.get("significant_worsening_hint") for s in ser.values()):
                worsening.append(_row(p, "по шкалам — заметное ухудшение"))
        for pp in db.execute(select(M.Proposal).where(M.Proposal.patient_id == p.id, M.Proposal.kind == "routing", M.Proposal.status == "pending")).scalars():
            referrals.append(_row(p, (pp.payload.get("title") or pp.key) + " — ждёт вашего решения", pp.created_at))
        for r in db.execute(select(M.Referral).where(M.Referral.patient_id == p.id, M.Referral.status == "awaiting_acceptance")).scalars():
            referrals.append(_row(p, r.rule_id + " — передано психиатру, ждёт получения", r.confirmed_at))
        vs = db.execute(select(M.Visit).where(M.Visit.patient_id == p.id, M.Visit.at >= now - timedelta(hours=12)).order_by(M.Visit.at)).scalars().first()
        if vs:
            visits.append(_row(p, "повторный приём" + (": " + vs.note if vs.note else ""), vs.at))
        req = db.execute(select(M.Message).where(M.Message.patient_id == p.id, M.Message.kind == "appointment_request", M.Message.read_at.is_(None))).scalars().first()
        if req:
            visits.append(_row(p, "пациент просит записать на приём", req.ts))
    visits.sort(key=lambda r: r["at"] or "")
    return {"buckets": [
        {"id": "on_treatment", "title": "Актуальные пациенты с планом лечения", "patients": on_treatment},
        {"id": "new_intake", "title": "Новые анкеты, требующие просмотра", "patients": new_intake},
        {"id": "worsening", "title": "Ухудшение состояния", "patients": worsening},
        {"id": "referrals", "title": "Направления к психиатру, ожидающие подтверждения", "patients": referrals},
        {"id": "visits", "title": "Ближайшие повторные приёмы", "patients": visits}]}


@router.get("/patients/{patient_id}/brief", summary="Краткая карточка: анкета, шкалы, длительность, лечение, болезни и препараты, риски")
def brief(patient: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    return brief_data(cfg, db, patient)


def brief_data(cfg: Config, db: Session, patient: M.Patient) -> Dict[str, Any]:
    """Краткая карточка (используют врач и психиатр)."""
    intake = SB.intake(db, patient.id)
    fields = SB.profile_fields(db, patient.id)
    a = core.assess_patient(db, cfg, patient, persist=False)
    def qa(qid): q = cfg.intake_q.get(qid); return {"id": qid, "q": BRIEF_SHORT.get(qid) or (q["text"] if q else qid), "a": answer_full(cfg, intake, qid)}
    intake_rows = [qa(q) for q in BRIEF_INTAKE if intake.get(q) is not None]
    scales = []
    for sid, s in a["dynamics"]["series"].items():
        pts = s.get("points", [])
        scales.append({"id": sid, "title": s.get("title"), "latest": s.get("latest"), "label": s.get("latest_label"), "baseline": s.get("baseline"), "count": len(pts), "date": pts[-1]["at"] if pts else None, "points": [{"at": x["at"], "total": x["total"]} for x in pts]})
    meds = db.execute(select(M.MedItem).where(M.MedItem.patient_id == patient.id, M.MedItem.active == True)).scalars().all()
    o = _active_order(db, patient.id)
    meds = [{"name": m.name, "dose": m.dose, "confirmed": m.confirmed_by_doctor} for m in meds if not (o and m.name.lower().startswith(cfg.drug["inn"]))]
    order = {"drug": cfg.drug["trade_name"] + " (" + cfg.drug["inn"] + ")", "regimen": (o.regimen or {}).get("regimen"), "started_on": o.started_on.isoformat()} if o else None
    d = a["drug_check"]
    risk = []
    for qid, bad, text in [("q12", None, "Мысли о смерти или самоповреждении"), ("q16", "o2", "Возможные психотические переживания"), ("q8", "o2", "Периоды повышенного настроения или активности"), ("q20", "o2", "Семейный анамнез")]:
        v = intake.get(qid)
        if v is None: continue
        if qid == "q12":
            if v != "o1":
                risk.append({"text": text, "answer": answer_text(cfg, qid, v)})
        elif v == bad:
            risk.append({"text": text, "answer": answer_full(cfg, intake, qid)})
    v14 = intake.get("q14")
    if isinstance(v14, list) and set(v14) - {"o5"}:
        risk.append({"text": "Алкоголь, никотин, другие вещества или лекарства вне схемы", "answer": answer_full(cfg, intake, "q14")})
    return {
        "patient": {"id": patient.id, "code": patient.code, "sex": patient.sex, "birth_date": patient.birth_date},
        "intake_progress": _intake_progress(cfg, db, patient.id), "reviewed": _reviewed(db, patient.id),
        "intake": intake_rows,
        "scales": scales,
        "duration_impact": {"duration": answer_text(cfg, "q2", intake.get("q2")), "impact": answer_text(cfg, "q6", intake.get("q6"))},
        "history": {"episodes": answer_text(cfg, "q7", intake.get("q7")), "help": answer_text(cfg, "q9", intake.get("q9"))},
        "somatic": {"chronic": answer_text(cfg, "q11", intake.get("q11")), "neuro": answer_text(cfg, "q17", intake.get("q17")), "somatic": answer_text(cfg, "q18", intake.get("q18")),
                    "meds": meds, "meds_from_intake": answer_text(cfg, "q10", intake.get("q10")), "order": order,
                    "hypersensitivity": fields.get("hypersensitivity")},
        "risks": {"drug_state": d["state"], "contraindications": [{"text": c.get("text"), "ohlp_section": c.get("ohlp_section")} for c in d.get("contraindications", [])],
                  "interactions": [{"title": x.get("title"), "level": x.get("level"), "med": x.get("med"), "ohlp_section": x.get("ohlp_section")} for x in d.get("interactions", [])],
                  "cautions": [c.get("text") for c in d.get("cautions", [])], "risk_factors": risk}
    }


@router.post("/patients/{patient_id}/intake-reviewed", summary="Отметить: анкета просмотрена врачом")
def intake_reviewed(patient: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function")):
    if not _reviewed(db, patient.id):
        db.add(M.DoctorMark(patient_id=patient.id, kind="intake_reviewed", by=user.id))
        audit.log(db, user, "intake.reviewed", "patient", patient.id, patient.id)
    db.flush()
    return {"ok": True}


class VisitIn(BaseModel):
    at: str = Field(description="ГГГГ-ММ-ДДTЧЧ:ММ")
    note: str = Field(default="", max_length=300)


@router.put("/patients/{patient_id}/next-visit", summary="Назначить повторный приём")
def next_visit(body: VisitIn, patient: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function")):
    try:
        at = datetime.fromisoformat(body.at)
    except ValueError:
        raise HTTPException(422, "дата приёма в формате ГГГГ-ММ-ДДTЧЧ:ММ")
    db.add(M.Visit(patient_id=patient.id, at=at, note=body.note.strip(), created_by=user.id))
    audit.log(db, user, "visit.set", "patient", patient.id, patient.id)
    db.flush()
    return {"ok": True, "at": at.isoformat()}


# ---------------------------------------------------------------- подсказки, направления, лекарственная безопасность

DRUG_STATE = {
    "indicated_pending_doctor": "Авиандр можно рассмотреть — ждёт решения врача",
    "contraindicated": "Противопоказание к Авиандру",
    "interaction_requires_decision": "Взаимодействие — нужно решение врача",
    "safety_check_incomplete": "Проверка безопасности не завершена",
    "out_of_indication": "Вне показаний инструкции",
}
LEVEL_ORDER = {"red": 0, "orange": 1, "yellow": 2, "green": 3}
FACT_LABELS = {"phq9": "PHQ-9", "gad7": "GAD-7", "phq9_item9": "PHQ-9, пункт 9", "checkin.c6": "Чек-ин: мысли о смерти",
               "therapy.weeks": "Недель лечения", "no_meaningful_improvement": "Нет заметного улучшения", "ae.severity": "Выраженность нежелательного явления",
               "persists": "Нежелательное явление сохраняется", "drug_check.state": "Проверка препарата", "patient_button": "Кнопка пациента",
               "worsening": "Нежелательное явление усиливается", "safety_followup.intent": "Намерение", "safety_followup.plan": "Конкретный план",
               "safety_followup.preparatory_actions": "Подготовительные действия", "safety_followup.can_stay_safe": "Может обеспечить свою безопасность",
               "safety_followup.recent_attempt_or_selfharm": "Недавняя попытка или самоповреждение",
               "symptom_criteria.depressive_episode_possible": "Возможны критерии депрессивного эпизода (МКБ-10)",
               "symptom_criteria.gad_possible": "Возможны критерии ГТР (МКБ-10)",
               "adherence.confirmed_missed_consecutive_days": "Подтверждённых пропусков приёма подряд, дней",
               "adherence.self_discontinuation_reported": "Пациент сообщил о самостоятельной отмене"}
STATUS_RU = {"approved_by_physician": "утверждено медиками проекта", "confirmed": "подтверждено", "confirmed_ohlp": "по ОХЛП",
             "draft_by_dev_pending_review": "черновик, ждёт проверки медиков", "doctor_manual": "решение врача"}
REF_STATUS = {"created": "Создано", "received": "Получено", "accepted": "Подтверждено психиатром", "completed": "Завершено", "cancelled": "Отменено"}
SUMMARY_LABELS = {"complaints_and_symptoms": "Жалобы и симптомы", "functioning": "Влияние на повседневную жизнь",
                  "previous_episodes_and_treatment": "Предыдущие эпизоды и лечение", "current_medications": "Текущие препараты",
                  "comorbidities_allergies_adverse_events": "Сопутствующие заболевания, аллергии, нежелательные явления",
                  "scales": "Результаты шкал", "self_report_dynamics": "Динамика самоотчётов", "risks": "Факторы риска",
                  "warnings_and_basis": "Предупреждения и основания", "decisions_already_taken": "Уже принятые решения"}


def _val(v: Any) -> str:
    if v is True or v == "yes": return "да"
    if v is False or v == "no": return "нет"
    if v is None or v == "unknown": return "нет данных"
    return str(v)


def _fact_label(cfg: Config, key: str, value: Any, intake: Dict[str, Any]) -> str:
    if key.startswith("intake.q"):
        qid = key.split(".")[1].split("_")[0]
        q = cfg.intake_q.get(qid)
        return (q["text"][:90] if q else qid) + " — " + (answer_text(cfg, qid, intake.get(qid)) or _val(value))
    if key in FACT_LABELS: return FACT_LABELS[key] + ": " + _val(value)
    return key + ": " + _val(value)


def _source_info(cfg: Config, text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Документ из раздела «Источники», на который опирается подсказка (или None, если документа нет)."""
    t = text or ""
    for sid, s in cfg.sources.items():
        rid = s.get("id_rubricator")
        if (rid and (rid in t or rid.replace("_", " ") in t)) or sid in t:
            return {"id": sid, "title": s["title"]}
    return None


VAL_RU = {"mild": "лёгкая", "moderate": "умеренная", "moderate_to_severe": "выраженная", "contraindicated": "противопоказан",
          "indicated_pending_doctor": "можно рассмотреть", "caution": "с осторожностью", "insufficient_data": "данных недостаточно"}


def _ball(n: Any) -> str:
    try:
        k = abs(int(n))
    except (TypeError, ValueError):
        return "баллов"
    return "балл" if k % 10 == 1 and k % 100 != 11 else ("балла" if 2 <= k % 10 <= 4 and not 12 <= k % 100 <= 14 else "баллов")


def _phrase(cfg: Config, key: str, v: Any, intake: Dict[str, Any]) -> Optional[str]:
    """Факт правила — понятной врачу фразой; технические факты не показываем."""
    if v is None:
        return None
    if key.startswith("intake.q"):
        qid = key.split(".")[1].split("_")[0]
        q = cfg.intake_q.get(qid) or {}
        lab = BRIEF_SHORT.get(qid) or IF.clean(q.get("text", ""))[:70]
        ans = answer_text(cfg, qid, intake.get(qid))
        return "в анкете «%s» — %s" % (lab, (ans or _val(v)).lower())
    if key in ("phq9", "gad7"):
        return "%s — %s %s" % (FACT_LABELS[key], v, _ball(v))
    lab = FACT_LABELS.get(key)
    if not lab:
        return None
    return "%s — %s" % (lab if lab[:3].isupper() else lab[0].lower() + lab[1:], VAL_RU.get(v, _val(v)))


def _snapshot(db: Session, p: M.Patient, a: Dict[str, Any]) -> List[str]:
    """Текущие данные пациента для обоснования, если у правила нет отдельных фактов."""
    out = []
    for s in (a.get("dynamics") or {}).get("series", {}).values():
        t = "%s — %s %s" % (s["title"], s["latest"], _ball(s["latest"]))
        if s.get("previous") is not None and s["previous"] != s["latest"]:
            t += " (было %s)" % s["previous"]
        out.append(t)
    i9 = (a.get("facts") or {}).get("phq9_item9")
    if i9:
        out.append("пункт 9 PHQ-9 (мысли о смерти) — %s" % i9)
    ae = db.execute(select(M.AEReport).where(M.AEReport.patient_id == p.id).order_by(M.AEReport.created_at.desc())).scalars().first()
    if ae and ae.persists:
        out.append("нежелательное явление: %s, сохраняется" % ((ae.details or {}).get("symptom") or VAL_RU.get(ae.severity, ae.severity)))
    o = _active_order(db, p.id)
    if o:
        out.append("лечение Авиандром — %d нед." % max(0, (clock.now().date() - o.started_on).days // 7))
    return out


def _basis(cfg: Config, intake: Dict[str, Any], facts: Optional[Dict[str, Any]], snap: List[str]) -> str:
    ph = [x for x in (_phrase(cfg, k, v, intake) for k, v in (facts or {}).items()) if x][:4] or snap[:3]
    if not ph:
        return "Данных пациента для обоснования пока недостаточно: заполните анкету и шкалы."
    s = "; ".join(ph)
    return s[0].upper() + s[1:] + "."


def patient_hints(cfg: Config, db: Session, p: M.Patient):
    """Подсказки по одному пациенту: [items], уровень (используют врач и психиатр)."""
    a = core.assess_patient(db, cfg, p, persist=False)
    intake = SB.intake(db, p.id)
    snap = _snapshot(db, p, a)
    items = []
    for tier in ("mandatory", "desirable"):
        for c in a["routing"][tier]:
            items.append({"kind": "routing", "tier": tier, "found": c["title"], "basis": _basis(cfg, intake, c.get("facts_used"), snap), "why": [_fact_label(cfg, k, v, intake) for k, v in (c.get("facts_used") or {}).items()],
                          "clarify": [], "risks": [], "next_step": (c.get("text") or ("Направление к психиатру — " + ("обязательно" if tier == "mandatory" else "желательно"))) + (". Срок: " + c["timing_text"] if c.get("timing_text") else ""),
                          "source": _source_info(cfg, (c.get("basis") or {}).get("source")), "status": STATUS_RU.get((c.get("basis") or {}).get("status"), (c.get("basis") or {}).get("status"))})
    d = a["drug_check"]
    on_therapy = _active_order(db, p.id) is not None
    if d["state"] in DRUG_STATE and not (on_therapy and d["state"] == "indicated_pending_doctor"):  # уже назначен — «можно рассмотреть» не показываем
        risks = [x.get("text", "") + (" (ОХЛП, раздел " + x["ohlp_section"] + ")" if x.get("ohlp_section") else "") for x in d.get("contraindications", [])]
        risks += [(x.get("title") or "") + (" — " + x["med"] if x.get("med") else "") for x in d.get("interactions", [])]
        risks += [x.get("text", "") for x in d.get("cautions", [])]
        clarify = [x.get("text", "") for x in d.get("to_clarify") or []] + ["Нет данных: " + m for m in d.get("missing") or []]
        unknown = (d.get("meds") or {}).get("unknown") or []
        if unknown: clarify.append("Нераспознанные препараты: " + ", ".join(unknown))
        texts = d.get("texts") or []
        items.append({"kind": "drug", "tier": d["state"], "found": DRUG_STATE[d["state"]], "basis": " ".join((texts[:-1] if len(texts) > 1 else texts)[:2]) or _basis(cfg, intake, None, snap), "why": texts[:-1] if len(texts) > 1 else texts,
                      "clarify": clarify, "risks": risks, "next_step": texts[-1] if texts else None, "status": STATUS_RU["confirmed_ohlp"],
                      "source": _source_info(cfg, "SRC-AVIANDR-GRLS")})
    alerts = db.query(M.Alert).filter(M.Alert.patient_id == p.id).filter(M.Alert.closed_at.is_(None)).order_by(M.Alert.id).all()
    for al in alerts:
        items.append({"kind": "alert", "tier": al.level, "found": al.title, "basis": _basis(cfg, intake, al.facts, snap), "why": [_fact_label(cfg, k, v, intake) for k, v in (al.facts or {}).items()],
                      "clarify": [], "risks": [], "next_step": "Подтвердите получение сигнала и зафиксируйте действие",
                      "source": _source_info(cfg, (al.basis or {}).get("source")), "status": STATUS_RU.get((al.basis or {}).get("status"), (al.basis or {}).get("status")), "alert_id": al.id})
    lv = min([LEVEL_ORDER.get(al.level, 3) for al in alerts] + [3])
    return items, [k for k, v in LEVEL_ORDER.items() if v == lv][0]


@router.get("/hints", summary="Клинические подсказки по пациентам: что обнаружено, основание, что уточнить, риски, шаг, источник")
def hints(user: M.User = Doctor, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    out = []
    for p in _my_patients(db, user):
        items, level = patient_hints(cfg, db, p)
        if items:
            out.append({"patient_id": p.id, "code": p.code, "level": level, "items": items})
    out.sort(key=lambda x: LEVEL_ORDER.get(x["level"], 9))
    return out


def _ref_row(cfg: Config, db: Session, r: M.Referral) -> Dict[str, Any]:
    from .psy_notes import PsychNote, DECISIONS
    p = db.get(M.Patient, r.patient_id)
    evs = db.query(M.ReferralEvent).filter(M.ReferralEvent.referral_id == r.id).order_by(M.ReferralEvent.at).all()
    kinds = [e.kind for e in evs]
    st = "created"
    if r.status == "cancelled": st = "cancelled"
    elif r.status == "completed": st = "completed"
    elif r.status == "accepted": st = "accepted"
    elif "received" in kinds: st = "received"
    else: st = "created"
    rules = {x["id"]: x for x in cfg.routing_mandatory + cfg.routing_desirable}
    rule = rules.get(r.rule_id, {})
    notes = db.query(PsychNote).filter(PsychNote.referral_id == r.id).order_by(PsychNote.ts).all()
    return {"id": r.id, "patient_id": p.id, "code": p.code, "rule_id": r.rule_id, "title": rule.get("title", r.rule_id), "kind": r.kind, "tier": r.tier,
            "status": st, "status_label": REF_STATUS[st], "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
            "due_at": r.due_at.isoformat() if r.due_at else None,
            "events": [{"kind": e.kind, "label": REF_STATUS.get(e.kind, e.kind), "at": e.at.isoformat(), "note": e.note or None} for e in evs],
            "transmitted": [SUMMARY_LABELS.get(k, k) for k in ((r.summary or {}).get("sections") or {}).keys()],
            "recommendations": [{"decision": DECISIONS.get(n.decision, n.decision), "comment": n.comment, "at": n.ts.isoformat()} for n in notes]}


@router.get("/referrals", summary="Направления и передача пациентов")
def referrals(user: M.User = Doctor, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    pats = {p.id: p for p in _my_patients(db, user)}
    ids = list(pats) or [0]
    refs = db.query(M.Referral).filter(M.Referral.patient_id.in_(ids)).order_by(M.Referral.id.desc()).all()
    pending = db.query(M.Proposal).filter(M.Proposal.patient_id.in_(ids)).filter(M.Proposal.kind == "routing").filter(M.Proposal.status == "pending").order_by(M.Proposal.id).all()
    base_list = [{"id": x["id"], "title": x["title"], "kind": "mandatory"} for x in cfg.routing_mandatory] + [{"id": x["id"], "title": x["title"], "kind": "desirable"} for x in cfg.routing_desirable]
    return {"referrals": [_ref_row(cfg, db, r) for r in refs],
            "pending": [{"proposal_id": x.id, "patient_id": x.patient_id, "code": pats[x.patient_id].code, "rule_id": x.key, "title": x.payload.get("title") or x.key, "tier": x.payload.get("timing_tier"), "kind": x.payload.get("kind")} for x in pending],
            "bases": base_list, "patients": [{"id": p.id, "code": p.code} for p in pats.values()]}


class ReferralIn(BaseModel):
    rule_id: str = Field(min_length=1, max_length=40)
    comment: str = Field(default="", max_length=1000)


@router.post("/patients/{patient_id}/referrals", summary="Создать направление к психиатру: врач выбирает основание")
def referral_create(body: ReferralIn, patient: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    from .. import proposals as PR
    try:
        ref = PR.manual_referral(db, cfg, patient, user, body.rule_id, body.comment)
    except PR.ProposalError as e:
        raise HTTPException(e.status, str(e))
    db.flush()
    return _ref_row(cfg, db, ref)


@router.get("/drug-safety", summary="Лекарственная безопасность по пациентам")
def drug_safety(user: M.User = Doctor, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    out = []
    now = clock.now()
    for p in _my_patients(db, user):
        a = core.assess_patient(db, cfg, p, persist=False)
        d = a["drug_check"]
        intake = SB.intake(db, p.id)
        fields = SB.profile_fields(db, p.id)
        meds = db.query(M.MedItem).filter(M.MedItem.patient_id == p.id).filter(M.MedItem.active == True).all()
        o = _active_order(db, p.id)
        aes = db.query(M.AEReport).filter(M.AEReport.patient_id == p.id).order_by(M.AEReport.created_at.desc()).all()
        changes = []
        if o and (now.date() - o.started_on).days <= 56: changes.append({"at": o.started_on.isoformat(), "text": "Начат приём Авиандра по подтверждённому назначению"})
        for e in db.query(M.AdherenceEvent).filter(M.AdherenceEvent.patient_id == p.id).filter(M.AdherenceEvent.kind == "self_discontinuation").all(): 
            changes.append({"at": e.day.isoformat(), "text": "Пациент сообщил о самостоятельной отмене"})
        if o and (o.regimen or {}).get("doctor_changes"): changes.append({"at": o.confirmed_at.isoformat() if o.confirmed_at else None, "text": "Врач изменил схему: " + str(o.regimen["doctor_changes"])})
        needs = [x.get("text", "") for x in d.get("to_clarify") or []] + ["Нет данных: " + m for m in d.get("missing") or []]
        unknown = (d.get("meds") or {}).get("unknown") or []
        if unknown: needs.append("Нераспознанные препараты: " + ", ".join(unknown))
        if not (d.get("meds") or {}).get("confirmed_by_doctor", True): needs.append("Список препаратов не подтверждён врачом")
        out.append({"patient_id": p.id, "code": p.code, "state": d["state"], "state_label": ("Принимает Авиандр по назначению врача" if o and d["state"] == "indicated_pending_doctor" else DRUG_STATE.get(d["state"], d["state"])),
                    "meds": [{"id": m.id, "name": m.name, "dose": m.dose, "source": m.source, "confirmed": m.confirmed_by_doctor} for m in meds
                             if not (o and m.name.lower().startswith(cfg.drug["inn"]))],
                    "meds_from_intake": answer_text(cfg, "q10", intake.get("q10")),
                    "order": {"drug": cfg.drug["trade_name"] + " (" + cfg.drug["inn"] + ")", "regimen": (o.regimen or {}).get("regimen"), "started_on": o.started_on.isoformat()} if o else None,
                    "allergy": _val(fields.get("hypersensitivity")) if "hypersensitivity" in fields else "нет данных",
                    "hypersensitivity": fields.get("hypersensitivity") or "unknown", "drug_allergies": fields.get("drug_allergies"),
                    "ae": [{"id": x.id, "at": x.created_at.isoformat(), "severity": x.severity, "symptom": (x.details or {}).get("symptom"), "urgent": x.urgent_flag, "persists": x.persists} for x in aes],
                    "changes": changes,
                    "contraindications": [{"text": c.get("text"), "ohlp_section": c.get("ohlp_section")} for c in d.get("contraindications", [])],
                    "interactions": [{"title": x.get("title"), "level": x.get("level"), "med": x.get("med"), "ohlp_section": x.get("ohlp_section")} for x in d.get("interactions", [])],
                    "cautions": [c.get("text") for c in d.get("cautions", [])],
                    "needs_check": needs})
    return out
    return out
