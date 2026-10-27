"""Чекер безопасности терапии (справочник препарата из drug_aviandr.json).

Результат — ровно одно из пяти состояний (drug_aviandr.json → _meta.result_states):
  indicated_pending_doctor, contraindicated, safety_check_incomplete,
  out_of_indication, interaction_requires_decision.

Принципы:
  * показание проверяется по dx_icd10, который ввёл и подтвердил ВРАЧ, а не по гипотезе системы;
  * неизвестный клинический факт НИКОГДА не даёт «противопоказаний нет»: даёт «Проверка безопасности не завершена»;
  * при противопоказании положительное предложение не формируется; экстренный сигнал из-за противопоказания не запускается;
  * даже при полной проверке результат — только предложение «ожидает решения врача».
Все условия, тексты и режимы читаются из конфигурации.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from . import expr as X
from . import facts as F
from .config_loader import Config

RESULT_STATES = [
    "contraindicated",
    "interaction_requires_decision",
    "out_of_indication",
    "safety_check_incomplete",
    "indicated_pending_doctor",
]

# Человекочитаемое имя недостающего факта (из clinical_profile_fields.json берётся label)
EXTRA_LABELS = {
    "maoi_last_dose_date": "дата последнего приёма ИМАО (или отметка «не принимал»)",
    "profile.age": "дата рождения / возраст",
    "age_years": "дата рождения / возраст",
    "dx_icd10": "диагноз врача (код МКБ-10)",
    "meds_confirmed": "список принимаемых препаратов, проверенный врачом",
}


def _load_meddict(cfg: Config) -> dict:
    import json
    p = cfg.path / "med_dictionary.json"
    if not p.exists():
        return {"classes": {}, "drugs": []}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _expand_classes(md: dict, classes: List[str]) -> List[str]:
    out: List[str] = []
    for c in classes:
        for k in [c] + md["classes"].get(c, {}).get("implies", []):
            if k not in out:
                out.append(k)
    return out


def match_meds(cfg: Config, meds: List[Any]) -> Dict[str, Any]:
    """Сопоставление принимаемых препаратов со справочником. Возвращает распознанные и нераспознанные."""
    md = _load_meddict(cfg)
    index = {d["inn"].lower(): d for d in md["drugs"]}
    recognized, unknown = [], []
    for m in meds:
        name = (m.get("name") if isinstance(m, dict) else str(m)).strip()
        low = name.lower()
        hit = next((index[k] for k in index if low.startswith(k) or k in low.split()), None)
        if hit is None:
            unknown.append(name)
            continue
        recognized.append({"input": name, "inn": hit["inn"], "classes": _expand_classes(md, hit["classes"]), "note": hit.get("note")})
    return {"recognized": recognized, "unknown": unknown, "dictionary": md}


def _label(cfg: Config, name: str) -> str:
    base = name.split(".")[-1]
    if name in EXTRA_LABELS:
        return EXTRA_LABELS[name]
    f = cfg.profile_fields.get(base)
    if f:
        return f["label"]
    return name


def check(cfg: Config, state: dict, red_alert_active: bool = False, mandatory_routing: Optional[List[dict]] = None) -> Dict[str, Any]:
    now = state.get("now") or datetime.utcnow()
    facts, trace = F.build_facts(cfg, state)
    drug = cfg.drug
    logic = cfg.bindings.get("drug_indication_logic", {})

    meds_state = state.get("meds") or {}
    items = meds_state.get("items", []) if isinstance(meds_state, dict) else list(meds_state)
    meds_confirmed = bool(meds_state.get("confirmed_by_doctor")) if isinstance(meds_state, dict) else False
    mm = match_meds(cfg, items)
    md = mm["dictionary"]
    all_classes: Set[str] = {c for r in mm["recognized"] for c in r["classes"]}

    # ИМАО из списка препаратов перекрывает ответ врача «нет»/«неизвестно» (в сторону безопасности)
    if "ИМАО" in all_classes:
        facts["maoi_current"] = True

    funcs = F.make_funcs(facts, now)
    contraindications: List[dict] = []
    missing: List[dict] = []
    seen_missing: Set[str] = set()

    def note_missing(fact: str, ci: Optional[dict] = None) -> None:
        if fact in seen_missing or fact.startswith("delta"):
            return
        seen_missing.add(fact)
        missing.append({"fact": fact, "label": _label(cfg, fact), "needed_for": ci["id"] if ci else None,
                        "verify_data": ci.get("verify_data") if ci else None})

    for ci in drug["contraindications"]:
        env = X.Env(facts, set(), funcs)
        v = X.evaluate(ci["check"], env)
        if v is True:
            contraindications.append({
                "id": ci["id"], "text": ci["text"], "severity": ci["severity"], "verify_data": ci.get("verify_data"),
                "status": ci.get("status"), "no_positive_suggestion": ci.get("no_positive_suggestion", True), "ohlp_section": ci.get("ohlp_section"),
                "basis": {"source_ids": drug_sources(cfg), "edition": drug["edition_date"]["value"], "config": "drug_aviandr.json#contraindications", "ohlp_section": ci.get("ohlp_section")},
            })
        elif v is None:
            # ci_maoi_after неопределён, пока врач не ответил про ИМАО — это тоже недостающий факт
            for m in sorted(env.missing):
                note_missing(m, ci)

    # --- взаимодействия по списку препаратов
    interactions: List[dict] = []
    ix_by_id = {ix["id"]: ix for ix in drug["interactions"]}
    for r in mm["recognized"]:
        for cls in r["classes"]:
            iid = md["classes"].get(cls, {}).get("interaction_id")
            if not iid or iid not in ix_by_id:
                continue
            ix = ix_by_id[iid]
            if not any(h["ix_id"] == iid and h["med"] == r["inn"] for h in interactions):
                interactions.append({
                    "ix_id": iid, "med": r["inn"], "med_input": r["input"], "class": cls, "with_class": ix["with_class"],
                    "action": ix["action"], "text": ix["text"], "ui": ix.get("ui"), "status": ix.get("status"),
                    "note": ix.get("note"), "level": ix.get("ui_level"), "ohlp_section": ix.get("ohlp_section"), "title": ix.get("alert_title"),
                })
    maoi_combo = [h for h in interactions if h["action"] == "contraindicated_combination"]
    for h in maoi_combo:
        if not any(c["id"].startswith("ci_maoi") for c in contraindications):
            contraindications.append({
                "id": "ci_maoi_concurrent", "text": next(c["text"] for c in drug["contraindications"] if c["id"] == "ci_maoi_concurrent") + " (по списку принимаемых препаратов: %s)" % h["med"],
                "severity": "absolute", "verify_data": "список препаратов", "status": "confirmed_ohlp", "no_positive_suggestion": True, "ohlp_section": "4.3",
                "basis": {"source_ids": drug_sources(cfg), "edition": drug["edition_date"]["value"], "config": "drug_aviandr.json#interactions"},
            })
    needs_decision = [h for h in interactions if h["action"] == "requires_doctor_decision"]

    # --- предостережения (не блокируют проверку, но видны врачу)
    cautions: List[dict] = []
    clarify: List[dict] = []
    for c in drug["cautions"]:
        env = X.Env(facts, set(), funcs)
        v = X.evaluate(c["check"], env)
        if v is True:
            cautions.append({"id": c["id"], "text": c["text"], "status": c.get("status"), "note": c.get("note")})
        elif v is None:
            clarify.append({"id": c["id"], "text": c["text"], "missing": sorted(env.missing)})
    alc = X.evaluate("intake.q14_alcohol == true OR rus_audit_positive == true", X.Env(facts, set(), funcs))
    if alc is True:
        ax = ix_by_id.get("ix_alcohol")
        if ax:
            cautions.append({"id": "ix_alcohol", "text": ax["text"], "status": ax.get("status"), "note": None})

    # --- список препаратов: без подтверждения врача и без распознавания проверка не завершена
    if mm["unknown"]:
        for n in mm["unknown"]:
            note_missing("concomitant_meds:" + n)
            missing[-1]["label"] = "препарат «%s» не распознан справочником: проверьте взаимодействия вручную" % n
    if not meds_confirmed and not maoi_combo:
        meds_flag = logic.get("meds_confirmed_field", "meds_confirmed")
        if tri_field(state, meds_flag) is not True:
            note_missing(meds_flag)

    # --- показание по коду МКБ-10, который ввёл врач
    indication = _indication(cfg, facts, logic)

    # --- итоговое состояние
    if contraindications:
        result = "contraindicated"
    elif needs_decision:
        result = "interaction_requires_decision"
    elif indication["status"] in ("out_of_indication", "unconfirmed_requires_doctor_decision"):
        result = "out_of_indication"
    elif missing or indication["status"] == "unknown":
        result = "safety_check_incomplete"
    else:
        result = "indicated_pending_doctor"

    incomplete_items = [m["label"] for m in missing]
    if indication["status"] == "unknown":
        incomplete_items.insert(0, EXTRA_LABELS["dx_icd10"])

    texts = _texts(cfg, result, contraindications, needs_decision, interactions, cautions, incomplete_items, indication)
    gating = _gating(cfg, result, red_alert_active, mandatory_routing or [])
    card = _card(cfg, result, indication, gating, contraindications, interactions, cautions, clarify) if result != "contraindicated" or True else None

    return {
        "state": result,
        "indication": indication,
        "contraindications": contraindications,
        "interactions": interactions,
        "cautions": cautions,
        "to_clarify": clarify,
        "missing": missing,
        "incomplete_items": incomplete_items,
        "meds": {"recognized": mm["recognized"], "unknown": mm["unknown"], "confirmed_by_doctor": meds_confirmed},
        "texts": texts,
        "gating": gating,
        "card": card,
        "positive_suggestion": bool(gating["show_positive"]),
        "emergency_signal_triggered": False,  # противопоказание не запускает экстренный сигнал (медики 9.2, 9.3)
        "drug": {"trade_name": drug["trade_name"], "inn": drug["inn"], "edition": drug["edition_date"]["value"],
                 "registration": drug["registration"], "source_ids": drug_sources(cfg)},
    }


def tri_field(state: dict, name: str) -> Optional[bool]:
    fields = (state.get("profile") or {}).get("fields", {}) or {}
    return F.tri(fields.get(name))


def drug_sources(cfg: Config) -> List[str]:
    return cfg["drug_aviandr"]["_meta"].get("source_ids", [])


def _norm_code(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip().upper().split()[0] if str(v).strip() else ""
    return s or None


def _indication(cfg: Config, facts: Dict[str, Any], logic: dict) -> Dict[str, Any]:
    ind = cfg.drug["indications"]
    dx = _norm_code(facts.get("dx_icd10"))
    syndrome = facts.get("predominant_syndrome")
    by = {e["code"]: e for e in ind["by_icd10"]}
    dep_prefixes = tuple(logic.get("depression_icd_prefixes", []))
    dep_labels = logic.get("depressive_syndrome_labels", [])
    out: Dict[str, Any] = {"dx_icd10": dx, "status": "unknown", "note": None, "label": None,
                           "source": "drug_aviandr.json#indications", "dx_entered_by": "doctor"}
    if dx is None:
        # Депрессия как ведущий синдром (выбор врача) уже означает «вне показаний»
        if syndrome in dep_labels:
            out.update(status="out_of_indication", note="Депрессивный эпизод не указан как показание в описании препарата. «Вне инструкции»: решение только врача. Предлагается консультация психиатра.")
        else:
            out.update(note="Код МКБ-10 не внесён врачом: показание не проверяется (система диагноз не ставит).")
        return out
    entry = by.get(dx)
    if entry and entry["status"] == "confirmed_leaflet":
        out.update(status="confirmed", label=entry["label"], note="Показание подтверждено врачом (код %s)." % dx)
    elif entry:  # F41.9 / F43.9: показание не подтверждено листком
        second = facts.get(logic.get("second_indication_field", "second_indication_confirmed"))
        if second is True:
            out.update(status="confirmed", label=entry["label"], note="Врач подтвердил соответствие второму показанию; код %s в листке не указан — уточните по ОХЛП (verify_grls)." % dx, verify_grls=True)
        else:
            out.update(status="unconfirmed_requires_doctor_decision", label=entry["label"],
                       note="Код %s взят из вторичного источника и в листке-вкладыше не приведён: показание требует решения врача. Уточните по ОХЛП." % dx)
    elif dx.startswith(dep_prefixes) or syndrome in dep_labels:
        out.update(status="out_of_indication", note="Депрессивный эпизод не указан как самостоятельное показание в описании препарата. «Вне инструкции»: решение только врача.")
    else:
        out.update(status="out_of_indication", note="Код %s не входит в показания из описания препарата. «Вне инструкции»: решение только врача." % dx)
    return out


def _texts(cfg, result, ci, needs, ixs, cautions, incomplete, indication) -> List[str]:
    drug = cfg.drug
    t: List[str] = []
    if result == "contraindicated":
        for c in ci:
            t.append(c["text"])
        t.append("Положительное предложение о назначении не формируется. Предлагается пересмотреть варианты лечения с учётом противопоказания. Решение за врачом.")
    elif result == "interaction_requires_decision":
        for h in needs:
            t.append("%s: %s. %s" % (h["med"].capitalize(), h["with_class"], h["text"]))
        t.append(cfg.bindings["drug_routing"]["interaction_requires_decision"]["text"] + ".")
        t.append(drug["interaction_note"])
    elif result == "out_of_indication":
        t.append(indication["note"])
        t.append("Статус «вне инструкции»: решение о применении вне инструкции может принять только врач.")
    elif result == "safety_check_incomplete":
        t.append("Проверка безопасности не завершена: отсутствуют сведения о: " + "; ".join(incomplete) + ".")
        t.append("Положительное предложение не формируется, пока сведения не внесены.")
    else:
        t.append(indication["note"])
        t.append("По введённым данным противопоказания не обнаружены; проверка завершена врачом.")
        t.append(drug["phrasing"]["allowed"][0])
        t.append(drug["phrasing"]["allowed"][3])
    for c in cautions:
        t.append("Осторожность: " + c["text"])
    return t


def _gating(cfg: Config, result: str, red_active: bool, mandatory: List[dict]) -> Dict[str, Any]:
    g = cfg.drug["gating"]
    reasons: List[str] = []
    show = result == "indicated_pending_doctor"
    if show and red_active:
        show = False
        reasons.append("Есть активный красный алерт: положительное предложение скрыто, приоритет — экстренное реагирование.")
    note = None
    if show and mandatory:
        note = "после консультации психиатра"  # gating.if_mandatory_routing_active.behavior
        reasons.append("Активна маршрутизация «обязательно»: предложение показывается с пометкой «после консультации психиатра».")
    return {"show_positive": show, "note": note, "reasons": reasons, "rules_ref": "drug_aviandr.json#gating"}


def _card(cfg: Config, result, indication, gating, ci, ixs, cautions, clarify) -> Dict[str, Any]:
    d = cfg.drug
    positive = gating["show_positive"]
    return {
        "title": "%s (%s)" % (d["trade_name"], d["inn"]),
        "state": result,
        "positive_suggestion_text": d["phrasing"]["allowed"][0] if positive else None,
        "psychiatrist_note": gating["note"],
        "fields": {
            "registered_indications": [e["label"] + " (" + e["code"] + ")" for e in d["indications"]["by_icd10"] if e["status"] == "confirmed_leaflet"] + [o["label"] for o in d["indications"]["other"]],
            "indication_match": indication["note"],
            "safety_checks": {"contraindications": [c["text"] for c in ci], "interactions": [(h["med"], h["text"]) for h in ixs], "cautions": [c["text"] for c in cautions]},
            "dosing_reference": d["dosing_reference"] if positive else None,
            "dosing_note": "Режим из инструкции приведён справочно. Назначение и длительность определяет врач.",
            "monitoring": d["monitoring"],
            "adverse_events": {"common": d["adverse_events"]["common_in_description"], "tell_doctor_immediately": d["adverse_events"]["frequency_scheme"]["uncommon_tell_doctor_immediately"]},
            "source": {"ids": drug_sources(cfg), "edition": d["edition_date"]["value"], "nd": d["edition_date"]["nd"], "registration_valid_until": d.get("registration_valid_until")},
            "doctor_decision": d["recommendation_card"]["decision_requires"],
        },
        "decisions": ["confirm", "modify", "reject"] if positive else ["reject"],
        "reject_requires_reason": True,
        "verification_checklist_grls": d.get("verification_checklist_grls"),
    }
