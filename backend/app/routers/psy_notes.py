from __future__ import annotations
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column
from .. import audit, clock, models as M
from ..config_loader import Config
from ..db import Base
from ..deps import get_cfg, get_db, patient_for_doctor, require_roles

from ..security import EncryptedText

router = APIRouter(tags=["Псychiatrist"])
Psy = Depends(require_roles("psychiatrist"))

DECISIONS = {
    "consult_scheduled": "Консультация назначена",
    "advice_to_doctor": "Рекомендации лечащему врачу",
    "back_to_doctor": "Наблюдение у лечащего врача",
    "other": "Другое"
}

class PsychNote(Base):
    __tablename__ = "psych_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    referral_id: Mapped[int] = mapped_column(ForeignKey("referrals.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(30))
    comment: Mapped[str] = mapped_column(EncryptedText, default="")
    ts: Mapped[datetime] = mapped_column(DateTime, default=clock.now)

class NoteIn(BaseModel):
    decision: str
    comment: str = Field(min_length=3, max_length=2000)

def _ref(db, rid):
    r = db.get(M.Referral, rid)
    if not r:
        raise HTTPException(404, "направление не найдено")
    return r

def _note_out(db, n):
    author = db.get(M.User, n.author_id)
    return {
        "id": n.id,
        "decision": n.decision,
        "decision_label": DECISIONS.get(n.decision, n.decision),
        "comment": n.comment,
        "author": author.name if author else "",
        "ts": n.ts.isoformat()
    }

def _rule_title(cfg, rule_id):
    rr = cfg["routing_rules"]
    for item in rr.get("mandatory", []) + rr.get("desirable", []):
        if item.get("id") == rule_id:
            return item.get("title") or rule_id
    return rule_id

@router.get("/api/psychiatrist/referrals/{rid}/basis", summary="Кто и почему направил")
def basis(rid: int, user: M.User = Psy, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    r = _ref(db, rid)
    doc = db.get(M.User, r.confirmed_by)
    prop = db.get(M.Proposal, r.proposal_id)
    return {
        "rule_id": r.rule_id,
        "kind": r.kind,
        "title": _rule_title(cfg, r.rule_id),
        "confirmed_by": doc.name if doc else "",
        "confirmed_at": r.confirmed_at.isoformat(),
        "source": prop.basis if prop else None
    }

@router.get("/api/psychiatrist/referrals/{rid}/notes", summary="Решения и комментарии психиатра")
def notes(rid: int, user: M.User = Psy, db: Session = Depends(get_db, scope="function")):
    _ref(db, rid)
    rows = db.execute(select(PsychNote).where(PsychNote.referral_id == rid).order_by(PsychNote.id)).scalars().all()
    return [_note_out(db, n) for n in rows]

@router.post("/api/psychiatrist/referrals/{rid}/notes", summary="Записать решение психиатра")
def add_note(rid: int, body: NoteIn, user: M.User = Psy, db: Session = Depends(get_db, scope="function")):
    r = _ref(db, rid)
    if body.decision not in DECISIONS:
        raise HTTPException(422, "неизвестное решение")
    n = PsychNote(referral_id=r.id, author_id=user.id, decision=body.decision, comment=body.comment.strip())
    db.add(n)
    db.flush()
    audit.log(db, user, "referral.note", "referral", r.id, r.patient_id, decision=body.decision)
    return _note_out(db, n)

@router.get("/api/doctor/patients/{patient_id}/psy-notes", summary="Решения психиатра по направлениям пациента")
def doctor_notes(patient: M.Patient = Depends(patient_for_doctor), db: Session = Depends(get_db, scope="function")):
    refs = db.execute(select(M.Referral).where(M.Referral.patient_id == patient.id)).scalars().all()
    out = []
    for r in refs:
        for n in db.execute(select(PsychNote).where(PsychNote.referral_id == r.id).order_by(PsychNote.id)).scalars():
            out.append(dict(_note_out(db, n), rule_id=r.rule_id))
    return out