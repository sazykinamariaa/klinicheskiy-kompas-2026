"""Единая точка оценки пациента: правила + чекер препарата + маршрутные карточки от препарата.

Результат содержит только ПРЕДЛОЖЕНИЯ (alerts, routing, therapy_suggestion). Ничего не назначается:
превращение в действие возможно лишь через подтверждение врача (app/proposals.py).
"""
from __future__ import annotations

from typing import Any, Dict, List

from . import drug as D
from . import rules as R
from .config_loader import Config


def assess(cfg: Config, state: dict) -> Dict[str, Any]:
    r = R.evaluate(cfg, state)
    red_active = r["level"] == "red"
    d = D.check(cfg, state, red_alert_active=red_active, mandatory_routing=r["routing"]["mandatory"])
    routing = r["routing"]

    dr = cfg.bindings.get("drug_routing", {})
    hours = cfg.bindings.get("tier_hours", {})
    tiers = cfg["routing_rules"]["_meta"]["timing_tiers"]

    def derived_card(spec: Dict[str, Any], kind: str, tier: str) -> Dict[str, Any]:
        return {
            "rule_id": spec["id"], "kind": kind, "title": spec["title"], "text": spec["text"],
            "timing_tier": tier, "timing_text": tiers.get(tier), "timing_override_text": None,
            "due_hours": hours.get(tier, {}).get("hours"),
            "when": "drug_check.state", "facts_used": {"drug_check.state": d["state"]},
            "clinical_note": None,
            "basis": {"source": spec["source"], "status": "draft_by_dev_pending_review", "config": "rule_bindings.json#drug_routing"},
            "doctor_decision": "подтвердить, отложить или отклонить (с причиной)",
            "state": "ожидает подтверждения врача",
        }

    if d["state"] == "contraindicated" and "contraindicated" in dr:
        routing["desirable"].append(derived_card(dr["contraindicated"], "desirable", "planned"))
    if d["state"] == "interaction_requires_decision" and "interaction_requires_decision" in dr:
        routing["desirable"].append(derived_card(dr["interaction_requires_decision"], "desirable", "soon"))
    if d["state"] == "out_of_indication" and d["indication"].get("status") == "out_of_indication":
        m = dr.get("out_of_indication_depression")
        if m and not any(c["rule_id"] == m["rule_id"] for c in routing["mandatory"]):
            facts = r["facts"]
            if facts.get("current_depressive") or facts.get("predominant_syndrome") in cfg.bindings.get("drug_indication_logic", {}).get("depressive_syndrome_labels", []):
                rule = next(x for x in cfg.routing_mandatory if x["id"] == m["rule_id"])
                routing["mandatory"].append(R._route_card(cfg, rule, "mandatory", "drug_check.out_of_indication", facts, set(r["fired"]), state.get("now")))

    # Предложение по терапии: только если проверка завершена и красного нет
    therapy = None
    if d["gating"]["show_positive"]:
        therapy = {
            "kind": "therapy_suggestion",
            "drug": d["drug"],
            "text": d["card"]["positive_suggestion_text"],
            "note": d["gating"]["note"],
            "state": "ожидает подтверждения врача",
            "decisions": d["card"]["decisions"],
            "reject_requires_reason": True,
            "basis": {"source_ids": d["drug"]["source_ids"], "edition": d["drug"]["edition"], "config": "drug_aviandr.json"},
        }

    for k in ("mandatory", "desirable"):
        routing[k].sort(key=lambda c: R.TIER_ORDER.get(c["timing_tier"], 9))

    return {
        "level": r["level"],
        "alerts": r["alerts"],
        "routing": routing,
        "drug_check": d,
        "therapy_suggestion": therapy,
        "amplifiers": r["amplifiers"],
        "unevaluated": r["unevaluated"],
        "facts": r["facts"],
        "trace": r["trace"],
        "hypothesis": symptom_hypothesis(cfg, r),
    }


def symptom_hypothesis(cfg: Config, r: Dict[str, Any]) -> Dict[str, Any]:
    """Профиль симптомов и гипотеза системы. Не диагноз. Формулировки «возможны признаки…» из patient_texts.json."""
    f = r["facts"]
    dep, gad = f.get("symptom_criteria.depressive_episode_possible"), f.get("symptom_criteria.gad_possible")
    lines: List[str] = []
    rr = cfg["routing_rules"]["symptom_criteria"]
    if dep is True:
        lines.append("Возможны признаки депрессивного эпизода: " + rr["depressive_episode_possible"]["system_text"])
    if gad is True:
        lines.append("Профиль симптомов, не исключающий генерализованное тревожное расстройство. Оценка критериев — клиническая.")
    if dep is True and gad is True:
        lines.append("Сочетание тревожной и депрессивной симптоматики: суммы PHQ-9 и GAD-7 не сравниваются; ведущий синдром выбирает врач. " + rr["comorbid"]["rule"].split(".")[0] + ".")
    if not lines:
        lines.append("Данных для гипотезы профиля недостаточно или критерии не выполнены. Диагноз устанавливает врач.")
    else:
        lines.append("Диагноз устанавливает врач.")
    return {"lines": lines, "depressive_criteria": dep, "gad_criteria": gad,
            "symptoms": {k: v for k, v in r["trace"].get("symptom_profile", {}).items()},
            "basis": {"source": "routing_rules.json#symptom_criteria", "source_ids": ["SRC-ICD10", "SRC-KR-DEP", "SRC-KR-GTR"]}}
