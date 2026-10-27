"""Сводка для психиатра (состав — routing_rules.json → psychiatrist_summary_fields) и экспорт: структурированный JSON
(FHIR-подобный Bundle) и PDF. Сводка собирается из данных карточки; ничего не придумывается."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import clock, models as M, state_builder as SB
from .config_loader import Config


def _labels(cfg: Config, qid: str, sel: Any) -> List[str]:
    q = cfg.intake_q.get(qid)
    if not q or sel is None:
        return []
    ids = sel if isinstance(sel, list) else [sel]
    return [o["label"] for o in q["options"] if o["id"] in ids]


def build_summary(db: Session, cfg: Config, patient: M.Patient, a: Dict[str, Any]) -> Dict[str, Any]:
    pid = patient.id
    intake = SB.intake(db, pid)
    fields = SB.profile_fields(db, pid)
    sections: Dict[str, Any] = {}
    prof = a["hypothesis"]["symptoms"]
    sections["complaints_and_symptoms"] = {
        "patient_reported": _labels(cfg, "q1", intake.get("q1")),
        "onset": _labels(cfg, "q2", intake.get("q2")),
        "symptom_profile": {k: {"present": v["present"], "duration_weeks": v["duration_weeks"], "source": v["source"]} for k, v in prof.items() if v["present"] is not False},
        "hypothesis": a["hypothesis"]["lines"],
    }
    sections["functioning"] = _labels(cfg, "q6", intake.get("q6"))
    runs = []
    for r in db.execute(select(M.ScaleRun).where(M.ScaleRun.patient_id == pid, M.ScaleRun.complete.is_(True)).order_by(M.ScaleRun.completed_at)).scalars():
        runs.append({"scale": cfg.scales[r.scale_id]["title"], "total": r.total, "at": (r.completed_at or r.started_at).isoformat()})
    sections["scales"] = runs
    sections["previous_episodes_and_treatment"] = {"episodes": _labels(cfg, "q7", intake.get("q7")), "help_received": _labels(cfg, "q9", intake.get("q9"))}
    meds = [{"name": m.name, "dose": m.dose} for m in db.execute(select(M.MedItem).where(M.MedItem.patient_id == pid, M.MedItem.active.is_(True))).scalars()]
    orders = [{"drug": o.drug_id, "regimen": o.regimen.get("regimen"), "started_on": o.started_on.isoformat()} for o in
              db.execute(select(M.TherapyOrder).where(M.TherapyOrder.patient_id == pid, M.TherapyOrder.stopped_at.is_(None))).scalars()]
    sections["current_medications"] = {"reported": meds, "confirmed_orders": orders}
    ae = [{"severity": x.severity, "urgent": x.urgent_flag, "at": x.created_at.isoformat(), "details": x.details} for x in
          db.execute(select(M.AEReport).where(M.AEReport.patient_id == pid).order_by(M.AEReport.id)).scalars()]
    sections["comorbidities_allergies_adverse_events"] = {"comorbidities": _labels(cfg, "q11", intake.get("q11")),
                                                           "profile": {k: fields.get(k) for k in ("hypersensitivity", "egfr_ml_min", "liver_failure_child_pugh", "epilepsy", "cardiovascular_disease", "diabetes_or_endocrine") if k in fields},
                                                           "adverse_events": ae}
    sections["self_report_dynamics"] = a.get("dynamics", {}).get("series", {})
    sections["risks"] = {"amplifiers": a["amplifiers"], "safety_state_q12": a["facts"].get("intake.q12"),
                         "open_alerts": [{"rule": x["rule_id"], "level": x["level"], "title": x["title"]} for x in a["alerts"]]}
    sections["warnings_and_basis"] = {"alerts": [{"rule": x["rule_id"], "title": x["title"], "basis": x["basis"], "facts": x["facts_used"]} for x in a["alerts"]],
                                      "routing": [{"rule": c["rule_id"], "kind": c["kind"], "title": c["title"], "basis": c["basis"]} for k in ("mandatory", "desirable") for c in a["routing"][k]],
                                      "drug_check_state": a["drug_check"]["state"]}
    decided = [{"kind": p.kind, "key": p.key, "title": (p.payload or {}).get("title") or ((p.payload or {}).get("drug") or {}).get("trade_name"),
                "status": p.status, "reason": p.reason, "at": p.decided_at.isoformat() if p.decided_at else None}
               for p in db.execute(select(M.Proposal).where(M.Proposal.patient_id == pid, M.Proposal.status.in_(("confirmed", "modified", "rejected"))).order_by(M.Proposal.id)).scalars()]
    sections["decisions_already_taken"] = decided
    labels = {fid: f["label"] for fid, f in cfg.profile_fields.items()}
    out = {
        "title": "Сводка для психиатра",
        "generated_at": clock.now().isoformat(),
        "patient": {"code": patient.code, "sex": patient.sex, "synthetic": patient.synthetic, "age": a["facts"].get("profile.age")},
        "field_order": cfg["routing_rules"]["psychiatrist_summary_fields"],
        "sections": sections,
        "disclaimer": "Диагноз устанавливает врач. Сводка не меняет и не отменяет терапию.",
    }
    out["readable"] = readable(out, labels)
    return out


# ---- краткий читаемый вид (для экрана психиатра и PDF): без кодов правил, имён полей и служебных меток -------------

DRUG_WORDS = {
    "indicated_pending_doctor": "препарат можно рассмотреть, решение за врачом",
    "contraindicated": "препарат противопоказан",
    "interaction_requires_decision": "есть взаимодействие, нужно решение врача",
    "out_of_indication": "препарат вне показаний",
    "safety_check_incomplete": "проверка безопасности препарата не завершена",
}
Q12_WORDS = {"negative": "В анкете на вопрос о мыслях о смерти и самоповреждении ответил(-а) «нет»", "past": "В анкете: такие мысли были раньше, сейчас нет",
             "recent": "В анкете: такие мысли были в последние дни", "current": "В анкете: такие мысли присутствуют сейчас", "unresolved": "В анкете: на вопрос о таких мыслях не ответил(-а)"}
SEV = {"mild": "лёгкое", "moderate": "умеренное", "moderate_to_severe": "умеренное или тяжёлое"}
KIND = {"therapy": "терапия", "routing": "направление", "status": "статус динамики"}
STAT = {"confirmed": "подтверждено", "modified": "изменено врачом", "rejected": "отклонено"}


def _d(iso: Any) -> str:
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d.%m.%Y")
    except ValueError:
        return str(iso)


def _weeks(w: Any) -> str:
    if w is None:
        return ""
    w = float(w)
    return "менее недели" if w < 1 else "около %d нед." % round(w)


def readable(summary: Dict[str, Any], labels: Dict[str, str] = None) -> List[Dict[str, Any]]:
    """Список блоков {title, lines}: коротко и по делу, обычным языком."""
    S, labels, blocks = summary["sections"], labels or {}, []

    def add(title: str, lines: List[str]) -> None:
        lines = [x for x in lines if x]
        if lines:
            blocks.append({"title": title, "lines": lines})

    pt = summary["patient"]
    who = {"м": "Мужчина", "ж": "Женщина"}.get(pt.get("sex"), "Пациент") + (", %s лет" % pt["age"] if pt.get("age") else "")
    top = []
    cs = S["complaints_and_symptoms"]
    top += cs.get("hypothesis", [])[:1]
    risks, warn = S["risks"], S["warnings_and_basis"]
    if risks["open_alerts"]:
        top.append("Требует оценки: " + "; ".join(a["title"] for a in risks["open_alerts"][:3]) + ".")
    mand = [r["title"] for r in warn["routing"] if r["kind"] == "mandatory"]
    des = [r["title"] for r in warn["routing"] if r["kind"] != "mandatory"]
    if mand:
        top.append("Консультация психиатра обязательна: " + "; ".join(mand) + ".")
    if des:
        top.append("Желательно обсудить: " + "; ".join(des) + ".")
    add(who + " · главное", top)

    sp = [(n, v) for n, v in cs.get("symptom_profile", {}).items() if v.get("present")]
    groups: Dict[str, List[str]] = {}
    for n, v in sp:
        groups.setdefault(_weeks(v.get("duration_weeks")), []).append(n)
    lines = []
    if cs.get("patient_reported"):
        lines.append("Пациент сообщает: " + "; ".join(x.rstrip(".") for x in cs["patient_reported"]) + ".")
    if cs.get("onset"):
        lines.append("Начало: " + "; ".join(x.rstrip(".") for x in cs["onset"]) + ".")
    for w, names in groups.items():
        lines.append("Симптомы%s: %s." % (" (" + w + ")" if w else "", ", ".join(names)))
    add("Жалобы и симптомы", lines)

    fn = [x.split("—", 1)[-1].strip() if "—" in x else x for x in S.get("functioning", [])]
    add("Влияние на жизнь", [(f[0].upper() + f[1:]).rstrip(".") + "." for f in fn])

    by: Dict[str, List[Dict[str, Any]]] = {}
    for r in S["scales"]:
        by.setdefault(r["scale"], []).append(r)
    sc = []
    for name, rs in by.items():
        pts = " → ".join(str(r["total"]) for r in rs)
        sc.append("%s: %s (%s)" % (name, pts, _d(rs[0]["at"]) + (" — " + _d(rs[-1]["at"]) if len(rs) > 1 else "")))
    add("Шкалы", ["; ".join(sc) + "." if sc else "Шкалы пока не заполнены."])

    pe = S["previous_episodes_and_treatment"]
    add("Прежние эпизоды и лечение", [("Эпизоды: " + "; ".join(x.rstrip(".") for x in pe["episodes"]) + ".") if pe["episodes"] else "",
                                       ("Помощь ранее: " + "; ".join(x.rstrip(".") for x in pe["help_received"]) + ".") if pe["help_received"] else ""])

    cm = S["current_medications"]
    meds = ["%s%s" % (m["name"], " " + m["dose"] if m.get("dose") else "") for m in cm["reported"]]
    orders = ["%s с %s" % (o["drug"], _d(o["started_on"])) for o in cm["confirmed_orders"]]
    add("Препараты", ["Принимает: " + ", ".join(meds) + "." if meds else "Принимаемые препараты не указаны.", ("Назначено врачом: " + ", ".join(orders) + ".") if orders else ""])

    ca = S["comorbidities_allergies_adverse_events"]
    prof = []
    for k, v in ca["profile"].items():
        if v in (None, "unknown", "no", "нет"):
            continue
        prof.append(labels.get(k, k) + ("" if v == "yes" else ": %s" % v))
    ae = ["%s (%s)" % (SEV.get(x["severity"], x["severity"]), _d(x["at"])) for x in ca["adverse_events"]]
    add("Сопутствующее и нежелательные явления", [("Сопутствующие состояния: " + "; ".join(x.rstrip(".") for x in ca["comorbidities"]) + ".") if ca["comorbidities"] else "",
                                                   ("Отмечено врачом: " + "; ".join(prof) + ".") if prof else "",
                                                   ("Нежелательные явления: " + ", ".join(ae) + ".") if ae else ""])

    add("Риски", [Q12_WORDS.get(risks.get("safety_state_q12"), ""), ("Усиливает: " + ", ".join(risks["amplifiers"]) + ".") if risks["amplifiers"] else ""])

    red = any(a.get("level") == "red" for a in risks["open_alerts"])
    add("Препарат (справка системы)", ["Предложение по препарату скрыто до оценки безопасности пациента." if red else (DRUG_WORDS.get(warn.get("drug_check_state"), "").capitalize() + ".")])

    dec = []
    for x in S["decisions_already_taken"]:
        t = x.get("title") or KIND.get(x["kind"], "")
        dec.append("%s: %s — %s%s" % (KIND.get(x["kind"], "").capitalize(), t, STAT.get(x["status"], x["status"]), (" (причина: %s)" % x["reason"]) if x.get("reason") else ""))
    add("Решения врача", dec or ["Пока не принято."])
    return blocks


def to_fhir_like(summary: Dict[str, Any], a: Dict[str, Any]) -> Dict[str, Any]:
    """FHIR-подобный Bundle (не полный профиль FHIR): Patient, Observation (шкалы), MedicationStatement, Flag (алерты), ServiceRequest."""
    entries: List[Dict[str, Any]] = [{"resource": {"resourceType": "Patient", "identifier": [{"value": summary["patient"]["code"]}],
                                                   "gender": {"м": "male", "ж": "female"}.get(summary["patient"]["sex"], "unknown")}}]
    for s in summary["sections"]["scales"]:
        entries.append({"resource": {"resourceType": "Observation", "status": "final", "code": {"text": s["scale"]},
                                     "valueInteger": s["total"], "effectiveDateTime": s["at"]}})
    for m in summary["sections"]["current_medications"]["reported"]:
        entries.append({"resource": {"resourceType": "MedicationStatement", "status": "active", "medicationCodeableConcept": {"text": m["name"]}, "dosage": [{"text": m["dose"]}]}})
    for al in a["alerts"]:
        entries.append({"resource": {"resourceType": "Flag", "status": "active", "code": {"text": al["title"]}, "extension": [{"url": "level", "valueString": al["level"]}, {"url": "rule", "valueString": al["rule_id"]}]}})
    for k in ("mandatory", "desirable"):
        for c in a["routing"][k]:
            entries.append({"resource": {"resourceType": "ServiceRequest", "status": "draft", "intent": "proposal", "priority": c["timing_tier"],
                                         "code": {"text": "Консультация психиатра"}, "reasonCode": [{"text": c["title"]}], "extension": [{"url": "kind", "valueString": k}]}})
    return {"resourceType": "Bundle", "type": "collection", "timestamp": summary["generated_at"],
            "meta": {"tag": [{"code": "fhir-like", "display": "FHIR-подобный экспорт, не заявляет соответствия профилям FHIR"}]},
            "entry": entries}
