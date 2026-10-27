"""Движок правил: алерты (красный / оранжевый / жёлтый) и маршрутизация к психиатру
(«обязательно» / «желательно»). Все условия, уровни, тексты, сроки читаются из конфигурации.

Модуль чистый: он ничего не пишет в БД и ничего не назначает. Он возвращает
ПРЕДЛОЖЕНИЯ с основанием (правило, данные, источник). Превращение предложения в действие
происходит только после подтверждения врачом (см. proposals.py).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from . import expr as X
from . import facts as F
from .config_loader import Config

LEVEL_ORDER = {"green": 0, "yellow": 1, "orange": 2, "red": 3}
TIER_ORDER = {"urgent": 0, "soon": 1, "planned": 2}


def _facts_used(expr_src: str, facts: Dict[str, Any], fired: Set[str]) -> Dict[str, Any]:
    try:
        refs = X.collect_refs(X.parse(expr_src))
    except X.ExprError:
        return {}
    used = {}
    for r in sorted(refs):
        v = facts.get(r)
        used[r] = v
    return used


def _eval(cfg: Config, src: str, facts: Dict[str, Any], fired: Set[str], now) -> Tuple[Optional[bool], Set[str], Optional[str]]:
    env = X.Env(facts, fired, F.make_funcs(facts, now))
    try:
        v = X.evaluate(src, env)
    except X.ExprError as e:
        return None, set(), str(e)
    return v, env.missing, None


def _source_block(cfg: Config, rule: dict) -> Dict[str, Any]:
    return {
        "source": rule.get("source"),
        "status": rule.get("status") or rule.get("level_assignment_status") or "approved_by_physician",
        "config": "alert_rules.json" if rule["id"].startswith("R-") else "routing_rules.json",
        "approval": cfg["approval"]["approval"]["date"] if cfg["approval"]["approval"].get("status") == "approved_by_physician" else None,
    }


def evaluate(cfg: Config, state: dict) -> Dict[str, Any]:
    """Главная точка входа: факты -> сработавшие алерты, маршрутизация, список «не вычислено»."""
    from datetime import datetime
    now = state.get("now") or datetime.utcnow()
    facts, trace = F.build_facts(cfg, state)
    fired_ids: Set[str] = set()
    alerts: List[Dict[str, Any]] = []
    unevaluated: List[Dict[str, Any]] = []

    def add_unevaluated(rule: dict, reason: str, missing: Set[str]) -> None:
        unevaluated.append({"rule_id": rule["id"], "title": rule.get("title"), "reason": reason, "missing_facts": sorted(missing)})

    # 1) Алерты
    for rule in cfg.alert_rules:
        rep = cfg.exec_report.get(rule["id"], {"executable": True})
        if not rep["executable"]:
            add_unevaluated(rule, rep["why"], set())
            continue
        src = cfg.rule_expr(rule)
        v, missing, err = _eval(cfg, src, facts, fired_ids, now)
        if err:
            add_unevaluated(rule, err, set())
        elif v is True:
            fired_ids.add(rule["id"])
            alerts.append(_alert_card(cfg, rule, src, facts, fired_ids))
        elif v is None:
            add_unevaluated(rule, "нет данных", missing)

    # 2) Синтетические сигналы по таблицам соответствия из alert_rules.json
    alerts += _safety_state_alerts(cfg, facts, fired_ids)
    alerts += _safety_followup_alerts(cfg, facts, fired_ids, now)

    # R-RED-* можно поднять и через результат уточняющих вопросов: добавляем в fired для маршрутизации
    for a in alerts:
        if a["level"] == "red":
            fired_ids.add(a["rule_id"])
        if a["level"] == "orange" and a["rule_id"].startswith(("SF-", "SAFETY-")):
            fired_ids.add("R-ORANGE-01")  # мысли/неразрешённая безопасность -> оперативная оценка (M-01)

    # 3) Маршрутизация
    routing = {"mandatory": [], "desirable": [], "pending_data": []}
    for kind, rules in (("mandatory", cfg.routing_mandatory), ("desirable", cfg.routing_desirable)):
        for rule in rules:
            rep = cfg.exec_report.get(rule["id"], {"executable": True})
            if not rep["executable"]:
                routing["pending_data"].append({"rule_id": rule["id"], "title": rule.get("title"), "why": rep["why"]})
                continue
            src = cfg.rule_expr(rule)
            v, missing, err = _eval(cfg, src, facts, fired_ids, now)
            if v is True:
                routing[kind].append(_route_card(cfg, rule, kind, src, facts, fired_ids, now))
            elif err:
                routing["pending_data"].append({"rule_id": rule["id"], "title": rule.get("title"), "why": err})
    for k in ("mandatory", "desirable"):
        routing[k].sort(key=lambda c: TIER_ORDER.get(c["timing_tier"], 9))

    alerts.sort(key=lambda a: -LEVEL_ORDER[a["level"]])
    level = alerts[0]["level"] if alerts else "green"
    return {
        "level": level,
        "alerts": alerts,
        "routing": routing,
        "unevaluated": unevaluated,
        "amplifiers": _amplifiers(cfg, facts, fired_ids, now),
        "facts": {k: v for k, v in facts.items() if not k.startswith("_")},
        "trace": trace,
        "fired": sorted(fired_ids),
    }


def _alert_card(cfg: Config, rule: dict, src: str, facts: Dict[str, Any], fired: Set[str]) -> Dict[str, Any]:
    lv = next(l for l in cfg["alert_rules"]["levels"] if l["id"] == rule["level"])
    override = rule.get("contact_override")
    contact = override["value"] if isinstance(override, dict) else None
    if contact is None:
        cw = lv.get("contact_within")
        contact = cw["value"] if isinstance(cw, dict) else None
    return {
        "rule_id": rule["id"],
        "level": rule["level"],
        "level_label": lv["label"],
        "title": rule["title"],
        "when": src,
        "facts_used": _facts_used(src, facts, fired),
        "actions": rule.get("actions", []),
        "note": rule.get("note"),
        "action_text": rule.get("action"),
        "patient_message": rule.get("patient_message"),
        "contact_within": contact,
        "basis": _source_block(cfg, rule),
        "routing_ref": rule.get("routing"),
    }


def _safety_state_alerts(cfg: Config, facts: Dict[str, Any], fired: Set[str]) -> List[Dict[str, Any]]:
    """alert_rules.json → safety_state_mapping.intake_q12: уровень = первое слово записи."""
    out = []
    mp = cfg["alert_rules"]["safety_state_mapping"]["intake_q12"]
    st = facts.get("intake.q12")
    if st and st in mp:
        text = mp[st]
        level = text.split()[0].strip(",;")
        if level in LEVEL_ORDER and level != "green":
            already = any(r in fired for r in ("R-ORANGE-01",)) and level == "orange"
            if not already:
                out.append({
                    "rule_id": "SAFETY-Q12-" + st.upper(),
                    "level": level,
                    "level_label": next(l["label"] for l in cfg["alert_rules"]["levels"] if l["id"] == level),
                    "title": "Ответ на вопрос 12 анкеты: %s" % st,
                    "when": "intake.q12 == %s" % st,
                    "facts_used": {"intake.q12": st},
                    "actions": [],
                    "note": text,
                    "contact_within": None,
                    "basis": {"source": "alert_rules.json#safety_state_mapping", "status": "approved_by_physician"},
                    "routing_ref": None,
                })
    return out


def _safety_followup_alerts(cfg: Config, facts: Dict[str, Any], fired: Set[str], now) -> List[Dict[str, Any]]:
    """Исполняемая запись result_rule: уровень по ответам sf1–sf9. Красный ставится ТОЛЬКО по подтверждённым ответам;
    «затрудняюсь» и прерванный блок дают оранжевый и уровень не снижают."""
    out = []
    spec = cfg.bindings.get("safety_followup_result", {})
    lv_labels = {l["id"]: l["label"] for l in cfg["alert_rules"]["levels"]}
    for item in spec.get("items", []):
        if any(r in fired for r in item.get("rule_ids", [])):
            continue  # то же событие уже зафиксировано правилом R-RED-0x
        if item["level"] != "red" and any(r.startswith("R-RED-") for r in fired):
            continue  # красный уже есть: оранжевая запись по тем же ответам лишняя
        v, _, _ = _eval(cfg, item["expr"], facts, fired, now)
        if v is True:
            out.append({
                "rule_id": item["id"],
                "level": item["level"],
                "level_label": lv_labels[item["level"]],
                "title": "Результат уточняющих вопросов безопасности (%s)" % item["id"],
                "when": item["expr"],
                "facts_used": _facts_used(item["expr"], facts, fired),
                "actions": [],
                "note": "Структурированные вопросы безопасности: не шкала, суммарного балла нет.",
                "contact_within": None,
                "basis": {"source": spec.get("source"), "status": "approved_by_physician"},
                "routing_ref": None,
            })
    return out


def _tier_for(cfg: Config, rule: dict, facts: Dict[str, Any], fired: Set[str], now) -> Tuple[str, Optional[str]]:
    tier = cfg.timing_tier(rule) or "planned"
    note = None
    ov = rule.get("timing_tier_override")
    if isinstance(ov, dict) and ov.get("when"):
        v, _, _ = _eval(cfg, ov["when"], facts, fired, now)
        if v is True:
            note = ov["value"]
    for o in cfg.bindings.get("routing_tier_overrides", {}).get(rule["id"], []):
        v, _, _ = _eval(cfg, o["when"], facts, fired, now)
        if v is True:
            tier = o["value"]
    return tier, note


def _route_card(cfg: Config, rule: dict, kind: str, src: str, facts: Dict[str, Any], fired: Set[str], now) -> Dict[str, Any]:
    tier, tier_note = _tier_for(cfg, rule, facts, fired, now)
    tiers = cfg["routing_rules"]["_meta"]["timing_tiers"]
    hours = cfg.bindings.get("tier_hours", {})
    return {
        "rule_id": rule["id"],
        "kind": kind,
        "title": rule["title"],
        "text": rule.get("text"),
        "timing_tier": tier,
        "timing_text": tiers.get(tier),
        "timing_override_text": tier_note,
        "due_hours": hours.get(tier, {}).get("hours") if isinstance(hours.get(tier), dict) else None,
        "when": src,
        "facts_used": _facts_used(src, facts, fired),
        "clinical_note": rule.get("clinical_note"),
        "basis": {"source": rule.get("source"), "status": rule.get("status") or "approved_by_physician", "config": "routing_rules.json"},
        "doctor_decision": "подтвердить, отложить или отклонить (с причиной)",
        "state": "ожидает подтверждения врача",
    }


def _amplifiers(cfg: Config, facts: Dict[str, Any], fired: Set[str], now) -> List[str]:
    out = []
    for label, src in cfg.bindings.get("amplifier_conditions", {}).items():
        if label.startswith("_"):
            continue
        v, _, _ = _eval(cfg, src, facts, fired, now)
        if v is True:
            out.append(label)
    return out
