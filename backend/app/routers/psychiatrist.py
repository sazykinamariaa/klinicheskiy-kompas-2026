"""Психиатр: входящие направления со сводкой, экспорт (JSON, FHIR-подобный, PDF), подтверждение получения."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, clock, core, models as M, proposals as PR
from ..config_loader import Config
from ..deps import get_cfg, get_db, require_roles
from ..pdfexport import summary_pdf
from ..summary import build_summary, to_fhir_like

router = APIRouter(prefix="/api/psychiatrist", tags=["Психиатр"])
Psy = Depends(require_roles("psychiatrist"))


def _ref(db: Session, rid: int) -> M.Referral:
    r = db.get(M.Referral, rid)
    if r is None:
        raise HTTPException(404, "направление не найдено")
    return r


@router.get("/referrals", summary="Направления, подтверждённые лечащими врачами")
def referrals(user: M.User = Psy, db: Session = Depends(get_db, scope="function")):
    order = {"urgent": 0, "soon": 1, "planned": 2}
    out = []
    for r in db.execute(select(M.Referral).where(M.Referral.status != "cancelled").order_by(M.Referral.id.desc())).scalars():
        p = db.get(M.Patient, r.patient_id)
        out.append({"id": r.id, "patient": p.code, "rule_id": r.rule_id, "kind": r.kind, "tier": r.tier, "status": r.status,
                    "due_at": r.due_at.isoformat() if r.due_at else None, "confirmed_at": r.confirmed_at.isoformat()})
    out.sort(key=lambda x: (x["status"] != "awaiting_acceptance", order.get(x["tier"], 9)))
    return out


@router.get("/referrals/{rid}", summary="Направление и сводка (снимок на момент подтверждения)")
def referral(rid: int, user: M.User = Psy, db: Session = Depends(get_db, scope="function")):
    r = _ref(db, rid)
    p = db.get(M.Patient, r.patient_id)
    audit.log(db, user, "referral.view", "referral", r.id, p.id)
    PR.referral_event(db, r, "received", user)  # «Получено»: психиатр впервые открыл направление
    return {"id": r.id, "patient": p.code, "rule_id": r.rule_id, "kind": r.kind, "tier": r.tier, "status": r.status, "summary": r.summary}


@router.post("/referrals/{rid}/accept", summary="Подтвердить получение направления")
def accept(rid: int, user: M.User = Psy, db: Session = Depends(get_db, scope="function")):
    r = _ref(db, rid)
    if r.status == "awaiting_acceptance":
        r.status = "accepted"
        audit.log(db, user, "referral.accept", "referral", r.id, r.patient_id)
        PR.referral_event(db, r, "received", user)
        PR.referral_event(db, r, "accepted", user)
    return {"ok": True, "status": r.status, "accepted_at": clock.now().isoformat()}


class CompleteIn(BaseModel):
    note: str = Field(default="", max_length=2000)


@router.post("/referrals/{rid}/complete", summary="Завершить направление (консультация проведена, рекомендации переданы)")
def complete(rid: int, body: CompleteIn, user: M.User = Psy, db: Session = Depends(get_db, scope="function")):
    r = _ref(db, rid)
    if r.status not in ("accepted", "awaiting_acceptance"):
        raise HTTPException(409, "направление уже завершено или отменено")
    r.status = "completed"
    PR.referral_event(db, r, "received", user)
    PR.referral_event(db, r, "accepted", user)
    PR.referral_event(db, r, "completed", user, note=body.note)
    audit.log(db, user, "referral.complete", "referral", r.id, r.patient_id)
    return {"ok": True, "status": r.status}


@router.get("/referrals/{rid}/summary.pdf", summary="Сводка в PDF")
def pdf(rid: int, user: M.User = Psy, db: Session = Depends(get_db, scope="function")):
    r = _ref(db, rid)
    if not r.summary:
        raise HTTPException(404, "сводка не сформирована")
    audit.log(db, user, "referral.export_pdf", "referral", r.id, r.patient_id)
    return Response(summary_pdf(r.summary), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="summary-%d.pdf"' % r.id})


@router.get("/referrals/{rid}/summary.fhir", summary="Структурированный экспорт (FHIR-подобный)")
def fhir(rid: int, user: M.User = Psy, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    r = _ref(db, rid)
    p = db.get(M.Patient, r.patient_id)
    a = core.assess_patient(db, cfg, p, persist=False)
    audit.log(db, user, "referral.export_fhir", "referral", r.id, p.id)
    return to_fhir_like(r.summary or build_summary(db, cfg, p, a), a)
