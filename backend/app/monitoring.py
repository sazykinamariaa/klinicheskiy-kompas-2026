"""Мониторинг: динамика шкал, предложения статусов «ответ / ремиссия / рецидив» (подтверждает только врач),
приверженность (подтверждённые данные отдельно от неизвестных), расписание из monitoring.json.

Правило ответа 50% применяется ТОЛЬКО к депрессии (PHQ-9 при исходном балле выше скринингового порога);
для GAD-7 используется ориентир интерфейса (4 балла) без статуса «ответ». Ремиссию система сама не предлагает по
баллам PHQ-9/GAD-7: нужен клинический балл, внесённый врачом (HAM-D / MADRS).
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from . import facts as F, scales as S
from .config_loader import Config


def _runs(cfg: Config, state: dict) -> Dict[str, List[dict]]:
    return F._scale_runs(cfg, state)


def dynamics(cfg: Config, state: dict) -> Dict[str, Any]:
    runs = _runs(cfg, state)
    hint = cfg["monitoring"]["dynamics_definitions"]["significant_change_ui_hint"]
    need = {"phq9": hint["phq9_points"], "gad7": hint["gad7_points"]}
    out: Dict[str, Any] = {"series": {}, "notes": [], "basis": {"source": "monitoring.json#dynamics_definitions", "status": "confirmed"}}
    for sid, rs in runs.items():
        done = [r for r in rs if r["complete"]]
        if not done:
            continue
        base, last = done[0], done[-1]
        bands = cfg.scales[sid].get("interpretation") or []

        def _label(v, bands=bands):
            for b in bands:
                if b["from"] <= v <= b["to"]:
                    return b["doctor_label"]
            return None
        item = {
            "title": cfg.scales[sid]["title"],
            "max": max([b["to"] for b in bands], default=None),
            "latest_label": _label(last["total"]),
            "previous": done[-2]["total"] if len(done) > 1 else None,
            "points": [{"at": r["at"].isoformat(), "total": r["total"], "label": r.get("label")} for r in done],
            "baseline": base["total"], "latest": last["total"],
            "change": last["total"] - base["total"],
            "change_pct": round(100.0 * (last["total"] - base["total"]) / base["total"], 1) if base["total"] else None,
        }
        if sid in need and len(done) > 1:
            d = base["total"] - last["total"]
            item["significant_improvement_hint"] = d >= need[sid]
            item["significant_worsening_hint"] = -d >= need[sid]
            item["hint_points"] = need[sid]
        out["series"][sid] = item
    out["notes"].append(cfg["monitoring"]["dynamics_definitions"]["screening_minimal"])
    return out


def status_suggestions(cfg: Config, state: dict, facts: Dict[str, Any], last_status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Предложения статусов. Всегда «ожидает подтверждения врача»; статус меняет только врач."""
    out: List[Dict[str, Any]] = []
    nums = cfg.bindings["monitoring_numbers"]
    thr = cfg.bindings["screening_thresholds"]["phq9"]["value"]
    runs = _runs(cfg, state)
    phq = [r for r in runs.get("phq9", []) if r["complete"]]
    dd = cfg["monitoring"]["dynamics_definitions"]
    basis = {"source": "monitoring.json#dynamics_definitions", "status": "confirmed"}
    resp_pct = nums["response_depression_pct"]["value"]
    if len(phq) >= 2 and phq[0]["total"] >= thr and phq[0]["total"] > 0:
        drop = 100.0 * (phq[0]["total"] - phq[-1]["total"]) / phq[0]["total"]
        if drop >= resp_pct and last_status not in ("response", "remission"):
            out.append({"kind": "status", "status": "response", "state": "ожидает подтверждения врача",
                        "title": "Возможен ответ на лечение (депрессия)",
                        "text": "PHQ-9: %d → %d (снижение на %.0f%% от исходного). %s" % (phq[0]["total"], phq[-1]["total"], drop, dd["response_depression"]),
                        "caveat": "Статус «ответ» присваивает врач с учётом клинической оценки и функционирования. Для GAD-7 правило 50% не применяется.",
                        "basis": dict(basis, evidence="PHQ-9 baseline %s, latest %s" % (phq[0]["total"], phq[-1]["total"]))})
    f = facts
    ham, mad = F.tri(None), None
    fields = (state.get("profile") or {}).get("fields", {}) or {}
    ham_v, mad_v = fields.get("ham_d_score"), fields.get("madrs_score")
    rm = nums["doctor_scale_remission"]
    if (ham_v is not None and float(ham_v) < rm["ham_d_lt"]) or (mad_v is not None and float(mad_v) < rm["madrs_lt"]):
        if last_status != "remission":
            out.append({"kind": "status", "status": "remission", "state": "ожидает подтверждения врача",
                        "title": "Клинический балл в диапазоне симптоматической ремиссии",
                        "text": dd["clinical_remission"],
                        "caveat": "Только врач подтверждает ремиссию с учётом симптомов, функционирования и длительности.",
                        "basis": dict(basis, evidence="HAM-D=%s, MADRS=%s (внесено врачом)" % (ham_v, mad_v))})
    if last_status in ("response", "remission") and len(phq) >= 2:
        hint = dd["significant_change_ui_hint"]["phq9_points"]
        if phq[-1]["total"] - phq[-2]["total"] >= hint:
            out.append({"kind": "status", "status": "relapse", "state": "ожидает подтверждения врача",
                        "title": "Рост симптомов после улучшения: возможен рецидив",
                        "text": dd["relapse"], "caveat": "Рецидив определяется клинически, а не только по порогу шкалы.",
                        "basis": dict(basis, evidence="PHQ-9 %d → %d" % (phq[-2]["total"], phq[-1]["total"]))})
    return out


def schedule_info(cfg: Config, state: dict) -> Dict[str, Any]:
    th = (state.get("therapy") or {}).get("started_on")
    today = state["now"].date()
    sched = cfg["monitoring"]["schedule"]
    hint = cfg.bindings["monitoring_numbers"]["schedule_hint_days"]["first_weeks"]
    if not th:
        stage = sched[0]
        nxt = None
    else:
        weeks = (today - F.as_date(th)).days // 7
        stage = sched[1] if weeks <= hint["until_weeks"] else (sched[2] if weeks <= 13 else sched[3])
        runs = [r for r in state.get("scale_runs", []) if r["scale_id"] in ("phq9", "gad7")]
        last = max((r["at"] for r in runs), default=None)
        nxt = (last.date() + timedelta(days=hint["interval_days"])).isoformat() if last and weeks <= hint["until_weeks"] else None
    return {"stage": stage["stage"], "instruments": stage["instruments"], "next_scales_due": nxt, "rules": cfg["monitoring"]["rules"],
            "basis": {"source": "monitoring.json#schedule", "status": "confirmed"}}


def adherence(cfg: Config, state: dict) -> Dict[str, Any]:
    """Подтверждённый приём, подтверждённый пропуск, нет отметки, нет данных, самостоятельное изменение — раздельно."""
    th = (state.get("therapy") or {}).get("started_on")
    if not th:
        return {"active": False, "note": "Напоминания и учёт приверженности включаются только по подтверждённому назначению."}
    start, today = F.as_date(th), state["now"].date()
    ev = {F.as_date(e["date"]): e["kind"] for e in state.get("adherence_events", [])}
    checkin_days = {F.as_date(e["date"]) for e in (state.get("checkin") or {}).get("entries", [])}
    c: Dict[str, int] = {"confirmed_taken": 0, "confirmed_missed": 0, "no_mark": 0, "no_data": 0, "self_discontinuation": 0}
    d = start
    while d <= today:
        k = ev.get(d)
        if k == "confirmed_taken":
            c["confirmed_taken"] += 1
        elif k in ("confirmed_missed", "confirmed_missed_partial"):
            c["confirmed_missed"] += 1
        elif k == "self_discontinuation":
            c["self_discontinuation"] += 1
        elif d in checkin_days:
            c["no_mark"] += 1      # чек-ин был, а об отметке приёма нет
        else:
            c["no_data"] += 1      # самонаблюдения нет вообще
        d += timedelta(days=1)
    known = c["confirmed_taken"] + c["confirmed_missed"]
    return {"active": True, "counts": c,
            "percent_taken_confirmed": round(100.0 * c["confirmed_taken"] / known, 1) if known else None,
            "note": cfg["monitoring"]["adherence"]["percent_taken"],
            "interim_instrument": cfg["monitoring"]["adherence"]["instrument"]["interim"]}
