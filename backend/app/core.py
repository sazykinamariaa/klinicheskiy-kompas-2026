"""Фасад: оценка пациента с сохранением алертов и предложений."""
from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import alerts_service as AL, engine, models as M, monitoring, proposals, state_builder as SB
from .config_loader import Config


def assess_patient(db: Session, cfg: Config, patient: M.Patient, persist: bool = True, now=None) -> Dict[str, Any]:
    state = SB.build_state(db, patient, now)
    a = engine.assess(cfg, state)
    last = db.execute(select(M.StatusChange).where(M.StatusChange.patient_id == patient.id).order_by(M.StatusChange.id.desc())).scalars().first()
    a["status_suggestions"] = monitoring.status_suggestions(cfg, state, a["facts"], last.status if last else None)
    a["dynamics"] = monitoring.dynamics(cfg, state)
    a["schedule"] = monitoring.schedule_info(cfg, state)
    a["adherence"] = monitoring.adherence(cfg, state)
    if persist:
        AL.sync_alerts(db, cfg, patient, a)
        proposals.sync_proposals(db, cfg, patient, a)
        db.flush()
    return a
