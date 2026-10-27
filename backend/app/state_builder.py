"""Снимок состояния пациента из БД для движка (формат описан в app/facts.py)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import clock, models as M


def _j(v):
    if v is None:
        return None
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return v


def profile_fields(db: Session, patient_id: int) -> Dict[str, Any]:
    rows = db.execute(select(M.ProfileFieldValue).where(M.ProfileFieldValue.patient_id == patient_id).order_by(M.ProfileFieldValue.id)).scalars()
    out: Dict[str, Any] = {}
    for r in rows:
        out[r.field_id] = _j(r.value)
    return out


def intake(db: Session, patient_id: int) -> Dict[str, Any]:
    rows = db.execute(select(M.IntakeAnswer).where(M.IntakeAnswer.patient_id == patient_id)).scalars()
    return {r.question_id: _j(r.answer) for r in rows}


def build_state(db: Session, patient: M.Patient, now: datetime = None) -> Dict[str, Any]:
    pid = patient.id
    now = now or clock.now()
    fields = profile_fields(db, pid)

    runs = []
    for r in db.execute(select(M.ScaleRun).where(M.ScaleRun.patient_id == pid).order_by(M.ScaleRun.started_at)).scalars():
        runs.append({"scale_id": r.scale_id, "at": r.completed_at or r.started_at, "answers": r.answers or {}})

    sf = db.execute(select(M.SafetyFollowup).where(M.SafetyFollowup.patient_id == pid).order_by(M.SafetyFollowup.id.desc())).scalars().first()
    safety = None
    if sf:
        safety = {"answers": sf.answers or {}, "complete": sf.complete, "started": True, "sf6_days_ago": sf.sf6_days_ago}

    entries = [{"date": c.day, "answers": c.answers or {}} for c in
               db.execute(select(M.Checkin).where(M.Checkin.patient_id == pid).order_by(M.Checkin.day)).scalars()]
    adh = [{"date": a.day, "kind": a.kind} for a in
           db.execute(select(M.AdherenceEvent).where(M.AdherenceEvent.patient_id == pid).order_by(M.AdherenceEvent.day)).scalars()]
    ae_row = db.execute(select(M.AEReport).where(M.AEReport.patient_id == pid).order_by(M.AEReport.id.desc())).scalars().first()
    ae = None
    if ae_row:
        ae = {"severity": ae_row.severity, "urgent_flag": ae_row.urgent_flag, "persists": ae_row.persists, "worsening": ae_row.worsening}

    flags: Dict[str, Any] = {}
    for f in db.execute(select(M.ClinicianFlag).where(M.ClinicianFlag.patient_id == pid).order_by(M.ClinicianFlag.id)).scalars():
        flags[f.flag] = f.value

    order = db.execute(select(M.TherapyOrder).where(M.TherapyOrder.patient_id == pid, M.TherapyOrder.stopped_at.is_(None))
                       .order_by(M.TherapyOrder.id.desc())).scalars().first()
    therapy = {"started_on": order.started_on} if order else {}

    symptoms: Dict[str, Any] = {}
    for s in db.execute(select(M.SymptomEntry).where(M.SymptomEntry.patient_id == pid).order_by(M.SymptomEntry.id)).scalars():
        symptoms[s.name] = {"present": s.present, "duration_weeks": s.duration_weeks}

    meds = [{"name": m.name, "dose": m.dose} for m in
            db.execute(select(M.MedItem).where(M.MedItem.patient_id == pid, M.MedItem.active.is_(True))).scalars()]
    meds_conf = str(fields.get("meds_confirmed", "")).lower() in ("yes", "true", "да")

    return {
        "now": now,
        "profile": {"sex": patient.sex, "birth_date": patient.birth_date, "fields": fields},
        "intake": intake(db, pid),
        "scale_runs": runs,
        "safety_followup": safety,
        "checkin": {"enabled_on": patient.checkin_enabled_on, "entries": entries},
        "adherence_events": adh,
        "ae": ae,
        "clinician_flags": flags,
        "patient_report": {"immediate_threat": flags.get("patient_immediate_threat")},
        "therapy": therapy,
        "symptoms": symptoms,
        "meds": {"items": meds, "confirmed_by_doctor": meds_conf},
    }
