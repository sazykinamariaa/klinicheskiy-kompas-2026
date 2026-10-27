"""Сборка плоского словаря фактов о пациенте для движка правил.

Вход — чистый снимок состояния ``state`` (словарь), выход — факты, у которых
«не известно» всегда представлено как None. Чтение анкеты идёт декларативно через
rule_bindings.json → fact_sources; в этом модуле нет клинических порогов
(числа берутся из конфигурации: monitoring.json, alert_rules.json, scales.json, rule_bindings.json).

Формат state (все поля необязательны):
  now: datetime
  profile: {sex, birth_date | age, fields: {field_id: value}}
  intake: {question_id: "o1" | ["o1","o3"]}
  scale_runs: [{scale_id, at: datetime, answers: {...}}]   # все прохождения
  safety_followup: {answers: {sf1..sf9: yes|no|unsure}, complete: bool, started: bool, sf6_days_ago: int|None}
  checkin: {enabled_on: date|None, entries: [{date, answers:{c6: ...}}]}
  adherence_events: [{date, kind}]  # confirmed_taken|confirmed_missed|confirmed_missed_partial|self_discontinuation
  ae: {severity, urgent_flag, persists, worsening} | None
  clinician_flags / patient_report: {immediate_threat, secondary_cause_suspected}
  therapy: {started_on: date|None}
  symptoms: {symptom_name: {present, duration_weeks}}   # внесено врачом
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from . import scales as S
from .config_loader import Config

YES = {"yes", "true", "да", True}
NO = {"no", "false", "нет", False}


def tri(v: Any) -> Optional[bool]:
    """Нормализация клинического факта в три состояния: True / False / None (неизвестно)."""
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("yes", "true", "да"):
        return True
    if s in ("no", "false", "нет"):
        return False
    return None  # unknown, неизвестно, "", «затрудняюсь», любое иное


def as_date(v: Any) -> Optional[date]:
    if v is None or v == "" or v == "none":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def calc_age(birth: Any, today: date) -> Optional[int]:
    b = as_date(birth)
    if not b:
        return None
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


def _selected(intake: Dict[str, Any], qid: str) -> Optional[Set[str]]:
    v = intake.get(qid)
    if v is None:
        return None
    if isinstance(v, dict):  # «Да (уточните)»: {"choice": ..., "text": ...}
        v = v.get("choice")
        if v is None:
            return None
    return set(v) if isinstance(v, (list, tuple, set)) else {v}


# --------------------------------------------------------------------------- каталог

SF_IDS = ["sf%d" % i for i in range(1, 10)]


def fact_catalog(cfg: Config) -> Set[str]:
    """Имена фактов, которые умеет выдавать этот модуль (для проверки исполнимости правил)."""
    names: Set[str] = {
        "profile.age", "age_years", "profile.sex",
        "phq9_item9", "phq9_item9_unresolved",
        "checkin.c6", "checkin.days_without",
        "adherence.confirmed_missed_consecutive_days", "adherence.self_discontinuation_reported",
        "therapy.weeks", "no_meaningful_improvement",
        "ae.severity", "ae.urgent_flag", "persists", "worsening",
        "safety_followup.intent", "safety_followup.plan", "safety_followup.preparatory_actions",
        "safety_followup.recent_attempt_or_selfharm", "safety_followup.can_stay_safe", "safety_followup.unresolved",
        "sf6_within_recent_days",
        "clinician_flag.immediate_threat", "clinician_flag.secondary_cause_suspected",
        "patient_report.immediate_threat",
        "symptom_criteria.depressive_episode_possible", "symptom_criteria.gad_possible",
        "current_depressive", "current_stable", "prior_episodes",
        "symptoms_present", "duration_weeks", "panic_duration_weeks",
        "rus_audit_positive", "pregnancy", "lactation", "sleep_disturbance_present",
    }
    names |= set(SF_IDS)
    fs = cfg.bindings.get("fact_sources", {})
    for k, v in fs.items():
        if k.startswith("intake."):
            names.add(k)
    names |= set(fs.get("scale_totals", {}).keys())
    names |= set(fs.get("scale_items", {}).keys())
    names |= set(cfg.profile_fields.keys())
    return names


# --------------------------------------------------------------------------- шкалы

def _scale_runs(cfg: Config, state: dict) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for r in sorted(state.get("scale_runs", []), key=lambda r: r["at"]):
        res = S.score(cfg, r["scale_id"], r["answers"])
        res["at"] = r["at"]
        out.setdefault(r["scale_id"], []).append(res)
    return out


def _latest_complete(runs: Dict[str, List[dict]], sid: str) -> Optional[dict]:
    for r in reversed(runs.get(sid, [])):
        if r["complete"]:
            return r
    return None


def _delta(runs: Dict[str, List[dict]], sid: str, days: int) -> Optional[float]:
    """Изменение итога за окно: последний полный итог минус самый ранний полный итог в окне [последний-days; последний].
    Одна точка в окне -> None (неизвестно)."""
    done = [r for r in runs.get(sid, []) if r["complete"]]
    if len(done) < 2:
        return None
    last = done[-1]
    window = [r for r in done[:-1] if last["at"] - r["at"] <= timedelta(days=days)]
    if not window:
        return None
    return last["total"] - window[0]["total"]


# --------------------------------------------------------------------------- симптомы

def symptom_profile(cfg: Config, state: dict, runs: Dict[str, List[dict]]) -> Dict[str, Dict[str, Any]]:
    """Профиль симптомов: {имя: {present: True/False/None, duration_weeks, source}}.
    Источники: PHQ-9, анкета q1/q2 и ручной ввод врача (врач перекрывает всё остальное)."""
    sm = cfg.bindings.get("symptom_map", {})
    prof: Dict[str, Dict[str, Any]] = {}

    def put(name: str, present: Optional[bool], src: str, weeks: Optional[float] = None) -> None:
        cur = prof.get(name)
        if cur is None or (present is True and cur["present"] is not True) or (cur["present"] is None and present is not None):
            prof[name] = {"present": present, "duration_weeks": weeks, "source": src}

    intake = state.get("intake", {})
    q2 = _selected(intake, "q2")
    dur = None
    if q2 and len(q2) == 1:
        dur = sm.get("duration_weeks_min_by_q2", {}).get(next(iter(q2)))

    phq = _latest_complete(runs, "phq9") or (runs.get("phq9") or [None])[-1]
    min_present = sm.get("phq9_item_present_min", {}).get("value", 2)
    for item_id, targets in sm.get("phq9_items", {}).items():
        val = phq["answers"].get(item_id) if phq else None
        for t in targets:
            if val is None:
                put(t, None, "phq9")
            else:
                put(t, bool(val >= min_present), "phq9", dur if val >= min_present else None)
    q1 = _selected(intake, "q1")
    if q1 is not None:
        for opt, targets in sm.get("intake_q1_options", {}).items():
            for t in targets:
                if opt in q1:
                    put(t, True, "intake", dur)
    for name, entry in (state.get("symptoms") or {}).items():
        prof[name] = {"present": tri(entry.get("present")), "duration_weeks": entry.get("duration_weeks"), "source": "doctor"}
    return prof


def _criteria(cfg: Config, prof: Dict[str, Dict[str, Any]]) -> Dict[str, Optional[bool]]:
    rr = cfg["routing_rules"]["symptom_criteria"]
    dep, gad = rr["depressive_episode_possible"], rr["gad_possible"]

    def pres(n: str) -> Optional[bool]:
        e = prof.get(n)
        return e["present"] if e else None

    def count(names: List[str]) -> Tuple[int, int]:
        yes = sum(1 for n in names if pres(n) is True)
        unk = sum(1 for n in names if pres(n) is None)
        return yes, unk

    my, mu = count(dep["main"])
    ay, au = count(dep["additional"])
    durs = [prof[n]["duration_weeks"] for n in dep["main"] + dep["additional"] if pres(n) is True and prof[n].get("duration_weeks") is not None]
    dur_ok: Optional[bool]
    if not durs:
        dur_ok = None
    else:
        dur_ok = min(durs) >= dep["min_duration_weeks"]
    # Критерий выполнен: точно набрано минимум; не выполнен: не наберётся даже при «неизвестно»; иначе неизвестно.
    if my >= dep["main_symptoms_min"] and ay >= dep["additional_min"]:
        sym: Optional[bool] = True
    elif my + mu < dep["main_symptoms_min"] or ay + au < dep["additional_min"]:
        sym = False
    else:
        sym = None
    if sym is False or dur_ok is False:
        dep_ok: Optional[bool] = False
    elif sym is True and dur_ok is True:
        dep_ok = True
    else:
        dep_ok = None

    sm_pool = cfg.bindings.get("symptom_map", {}).get("gad_symptom_pool", {})
    autonomic = gad["at_least_one_autonomic"]
    pool = list(autonomic) + list(sm_pool.get("other", []))
    gy, gu = count(pool)
    ay_, au_ = count(autonomic)
    gdurs = [prof[n]["duration_weeks"] for n in pool if pres(n) is True and prof[n].get("duration_weeks") is not None]
    gad_weeks_min = gad["persistent_widespread_anxiety_min_months"] * 52 / 12.0
    g_dur: Optional[bool] = None if not gdurs else (min(gdurs) >= gad_weeks_min)
    if gy >= gad["icd10_symptoms_min"] and ay_ >= 1:
        gs: Optional[bool] = True
    elif gy + gu < gad["icd10_symptoms_min"] or ay_ + au_ < 1:
        gs = False
    else:
        gs = None
    if gs is False or g_dur is False:
        gad_ok: Optional[bool] = False
    elif gs is True and g_dur is True:
        gad_ok = True
    else:
        gad_ok = None
    return {"dep": dep_ok, "gad": gad_ok}


# --------------------------------------------------------------------------- главная функция

def build_facts(cfg: Config, state: dict) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    now: datetime = state.get("now") or datetime.utcnow()
    today = now.date()
    facts: Dict[str, Any] = {}
    trace: Dict[str, Any] = {}
    fs = cfg.bindings.get("fact_sources", {})
    intake = state.get("intake", {})
    prof = state.get("profile", {}) or {}
    fields = dict(prof.get("fields", {}) or {})

    # --- профиль
    sex = (prof.get("sex") or "").strip().lower()
    sex = {"ж": "f", "м": "m", "f": "f", "m": "m"}.get(sex)
    age = prof.get("age")
    if age is None:
        age = calc_age(prof.get("birth_date"), today)
    facts["profile.age"] = age
    facts["age_years"] = age
    facts["profile.sex"] = sex
    for fid, f in cfg.profile_fields.items():
        v = fields.get(fid)
        if f.get("type") == "tri_state":
            facts[fid] = tri(v)
        elif isinstance(v, str) and v.strip().lower() in ("неизвестно", "unknown", ""):
            facts[fid] = None
        else:
            facts[fid] = v
    # выведенные факты (напр. беременность не применима к мужскому полу)
    derived_notes = {}
    for fid, d in cfg.bindings.get("derived_facts", {}).items():
        if fid.startswith("_"):
            continue
        if facts.get(fid) is None and d["when"].replace(" ", "") == "profile.sex==m" and sex == "m":
            facts[fid] = tri(d["value"])
            derived_notes[fid] = d["reason"]
    trace["derived"] = derived_notes
    # ИМАО из списка принимаемых препаратов перекрывает ответ врача «нет»/«неизвестно» (в сторону безопасности)
    meds = state.get("meds") or []
    facts["_meds"] = meds

    # --- анкета по fact_sources
    for name, src in fs.items():
        if not name.startswith("intake."):
            continue
        kind = src["kind"]
        if kind == "any_of":
            vals = []
            for part in src["of"]:
                sel = _selected(intake, part["question"])
                vals.append(None if sel is None else bool(sel & set(part["options"])))
            if any(v is True for v in vals):
                facts[name] = True
            elif all(v is None for v in vals):
                facts[name] = None
            else:
                facts[name] = False
            continue
        sel = _selected(intake, src["question"])
        if sel is None:
            facts[name] = None
        elif kind == "option_map":
            facts[name] = src["map"].get(next(iter(sel))) if len(sel) == 1 else None
        elif kind == "option_any":
            facts[name] = bool(sel & set(src["options"]))
        elif kind == "option_value":
            opt_id = next(iter(sel))
            q = cfg.intake_q[src["question"]]
            facts[name] = next((o.get("value") for o in q["options"] if o["id"] == opt_id), None)
        elif kind == "option_attr":
            opt_id = next(iter(sel))
            q = cfg.intake_q[src["question"]]
            facts[name] = next((o.get(src["attr"]) for o in q["options"] if o["id"] == opt_id), None)
    facts["prior_episodes"] = None if facts.get("intake.q7") is None else facts["intake.q7"] in ("one", "several", "chronic_no_remission")
    # panic_duration: нижняя граница из ответа о давности (если приступы есть)
    q2 = _selected(intake, "q2")
    dw = None
    if q2 and len(q2) == 1:
        dw = cfg.bindings.get("symptom_map", {}).get("duration_weeks_min_by_q2", {}).get(next(iter(q2)))
    facts["duration_weeks"] = dw
    facts["panic_duration_weeks"] = dw

    # --- шкалы
    runs = _scale_runs(cfg, state)
    trace["runs"] = {k: [{kk: vv for kk, vv in r.items() if kk in ("total", "complete", "at")} for r in v] for k, v in runs.items()}
    for fname, sid in fs.get("scale_totals", {}).items():
        r = _latest_complete(runs, sid)
        facts[fname] = r["total"] if r else None
    for fname, spec in fs.get("scale_items", {}).items():
        val = None
        unresolved_flag = False
        rs = runs.get(spec["scale"], [])
        if rs:
            last = rs[-1]
            val = last["answers"].get(spec["item"])
            if val is None:
                unresolved_flag = True
        facts[fname] = val
        facts[fname + "_unresolved"] = unresolved_flag if rs else None
    facts["phq9_item9_unresolved"] = facts.get("phq9_item9_unresolved")
    facts["_delta"] = {sid: _delta(runs, sid, 14) for sid in runs}
    audit = cfg.scales.get("rus_audit", {}).get("interpretation_rules", {})
    cut = audit.get("screen_positive_cutoff")
    facts["rus_audit_positive"] = None if facts.get("rus_audit") is None or cut is None else facts["rus_audit"] >= cut

    # --- скрининговые пороги и «стабильное состояние»
    thr = cfg.bindings.get("screening_thresholds", {})
    phq, gad = facts.get("phq9"), facts.get("gad7")
    phq_t = thr.get("phq9", {}).get("value")
    gad_t = thr.get("gad7", {}).get("value")
    totals = [(phq, phq_t), (gad, gad_t)]
    known = [(v, t) for v, t in totals if v is not None and t is not None]
    facts["current_stable"] = None if not known else all(v < t for v, t in known)

    # --- симптомы и критерии
    sp = symptom_profile(cfg, state, runs)
    crit = _criteria(cfg, sp)
    facts["symptom_criteria.depressive_episode_possible"] = crit["dep"]
    facts["symptom_criteria.gad_possible"] = crit["gad"]
    cd: Optional[bool]
    if crit["dep"] is True or (phq is not None and phq_t is not None and phq >= phq_t):
        cd = True
    elif crit["dep"] is False and (phq is None or phq_t is None or phq < phq_t):
        cd = False
    else:
        cd = None
    facts["current_depressive"] = cd
    any_sym = [e["present"] for e in sp.values()]
    facts["symptoms_present"] = True if any(v is True for v in any_sym) else (None if any(v is None for v in any_sym) or not any_sym else False)
    trace["symptom_profile"] = sp
    facts["sleep_disturbance_present"] = (sp.get("нарушение сна") or {}).get("present")

    # --- безопасность: уточняющие вопросы
    sf = state.get("safety_followup") or {}
    ans = sf.get("answers", {}) or {}
    for k in SF_IDS:
        v = ans.get(k)
        facts[k] = v if v in ("yes", "no", "unsure") else None
    recent_days = None
    for r in cfg.alert_rules:
        if r["id"] == "R-RED-02":
            recent_days = r.get("recent_period_days", {}).get("value")
    sf6_ago = sf.get("sf6_days_ago")
    within = None
    if facts["sf6"] == "yes":
        within = True if sf6_ago is None or recent_days is None else bool(sf6_ago <= recent_days)
    elif facts["sf6"] == "no":
        within = False
    facts["sf6_within_recent_days"] = within
    facts["safety_followup.intent"] = tri(ans.get("sf4"))
    facts["safety_followup.plan"] = tri(ans.get("sf5"))
    facts["safety_followup.preparatory_actions"] = within if facts["sf6"] == "yes" else tri(ans.get("sf6"))
    facts["safety_followup.recent_attempt_or_selfharm"] = within
    facts["safety_followup.can_stay_safe"] = tri(ans.get("sf8"))
    started = bool(sf.get("started"))
    if started:
        any_unsure = any(ans.get(k) in ("unsure", None) for k in SF_IDS if k in ans) or not sf.get("complete")
        facts["safety_followup.unresolved"] = bool(any_unsure)
    else:
        facts["safety_followup.unresolved"] = None
    facts["_sf_started"] = started

    # --- флаги врача/пациента
    cf = state.get("clinician_flags") or {}
    pr = state.get("patient_report") or {}
    facts["clinician_flag.immediate_threat"] = tri(cf.get("immediate_threat"))
    facts["clinician_flag.secondary_cause_suspected"] = tri(cf.get("secondary_cause_suspected"))
    facts["patient_report.immediate_threat"] = tri(pr.get("immediate_threat"))

    # --- чек-ин
    ck = state.get("checkin") or {}
    entries = sorted(ck.get("entries", []), key=lambda e: as_date(e["date"]))
    facts["checkin.c6"] = entries[-1]["answers"].get("c6") if entries else None
    if ck.get("enabled_on") is not None or entries:
        last_day = as_date(entries[-1]["date"]) if entries else as_date(ck.get("enabled_on"))
        facts["checkin.days_without"] = (today - last_day).days
    else:
        facts["checkin.days_without"] = None

    # --- приверженность: только подтверждённые данные
    ev = sorted(state.get("adherence_events", []), key=lambda e: as_date(e["date"]))
    streak = 0
    for e in reversed(ev):
        if e["kind"] in ("confirmed_missed", "confirmed_missed_partial"):
            streak += 1
        elif e["kind"] == "confirmed_taken":
            break
    facts["adherence.confirmed_missed_consecutive_days"] = streak if ev else None
    facts["adherence.self_discontinuation_reported"] = any(e["kind"] == "self_discontinuation" for e in ev) if ev else None

    # --- терапия и ответ
    th = state.get("therapy") or {}
    started_on = as_date(th.get("started_on"))
    facts["therapy.weeks"] = ((today - started_on).days // 7) if started_on else None
    facts["no_meaningful_improvement"] = _no_improvement(cfg, runs, started_on)

    # --- нежелательные явления
    ae = state.get("ae") or {}
    facts["ae.severity"] = ae.get("severity")
    facts["ae.urgent_flag"] = tri(ae.get("urgent_flag")) if ae else None
    facts["persists"] = tri(ae.get("persists")) if ae else None
    facts["worsening"] = tri(ae.get("worsening")) if ae else None
    return facts, trace


def _no_improvement(cfg: Config, runs: Dict[str, List[dict]], started_on: Optional[date]) -> Optional[bool]:
    """Нет заметного улучшения: ни одна из шкал не снизилась на ориентир интерфейса
    (monitoring.json → dynamics_definitions.significant_change_ui_hint). Не диагноз и не критерий ответа."""
    if not started_on:
        return None
    hint = cfg["monitoring"]["dynamics_definitions"]["significant_change_ui_hint"]
    need = {"phq9": hint["phq9_points"], "gad7": hint["gad7_points"]}
    verdicts = []
    for sid, pts in need.items():
        done = [r for r in runs.get(sid, []) if r["complete"]]
        base = next((r for r in done if r["at"].date() <= started_on + timedelta(days=3)), None)
        if base is None or len(done) < 2:
            continue
        verdicts.append((base["total"] - done[-1]["total"]) >= pts)
    if not verdicts:
        return None
    return not any(verdicts)


def make_funcs(facts: Dict[str, Any], now: datetime):
    """Функции, доступные в условиях: delta(scale, Nd), days_since(field)."""
    today = now.date()

    def delta(env, scale_id, window):
        env.missing.discard(scale_id)
        days = int(str(window).lower().rstrip("d"))
        sd = facts.get("_delta", {})
        v = sd.get(scale_id)
        if v is None:
            env.missing.add("delta(%s)" % scale_id)
        return v

    def days_since(env, field):
        v = facts.get(field)
        if v is None:
            env.missing.add(field)
            return None
        if str(v).lower() == "none":
            return 99999
        d = as_date(v)
        return None if d is None else (today - d).days

    return {"delta": delta, "days_since": days_since}
