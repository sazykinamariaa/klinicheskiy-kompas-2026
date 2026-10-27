"""Врач: «Мой план» пациента, переписка, сводка в PDF."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, clock, core, models as M
from ..config_loader import Config
from ..deps import get_cfg, get_db, patient_for_doctor, require_roles
from ..pdfexport import summary_pdf
from ..summary import build_summary
from . import patient as PT

router = APIRouter(prefix="/api/doctor/patients/{patient_id}", tags=["Врач"])
Doctor = Depends(require_roles("doctor"))


@router.get("/plan", summary="«Мой план» пациента")
def plan(p: M.Patient = Depends(patient_for_doctor), db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    return PT.plan_view(db, cfg, p)


@router.put("/plan", summary="Изменить план вместе с пациентом")
def plan_put(body: PT.PlanIn, p: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    PT.plan_save(db, cfg, p, user, body.sections)
    return {"ok": True}


@router.post("/plan/confirm", summary="Врач подтверждает план")
def plan_confirm(p: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function")):
    row = db.execute(select(M.MyPlan).where(M.MyPlan.patient_id == p.id).order_by(M.MyPlan.id.desc())).scalars().first()
    if row is None:
        return {"ok": False, "note": "плана ещё нет"}
    row.confirmed_by_doctor, row.confirmed_at = user.id, clock.now()
    audit.log(db, user, "plan.confirm", "patient", p.id, p.id)
    return {"ok": True}


@router.get("/messages", summary="Переписка")
def messages(p: M.Patient = Depends(patient_for_doctor), db: Session = Depends(get_db, scope="function")):
    rows = db.execute(select(M.Message).where(M.Message.patient_id == p.id).order_by(M.Message.id)).scalars().all()
    return [{"id": m.id, "from_patient": m.sender_id == p.user_id, "body": m.body, "kind": m.kind, "ts": m.ts.isoformat()} for m in rows]


class Msg(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


@router.post("/messages", summary="Написать пациенту")
def send(body: Msg, p: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function")):
    db.add(M.Message(patient_id=p.id, sender_id=user.id, body=body.body))
    audit.log(db, user, "message.sent", "patient", p.id, p.id)
    return {"ok": True}


@router.get("/summary.pdf", summary="Сводка для психиатра в PDF (по текущим данным)")
def summary_pdf_view(p: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    a = core.assess_patient(db, cfg, p, persist=False)
    audit.log(db, user, "summary.export_pdf", "patient", p.id, p.id)
    return Response(summary_pdf(build_summary(db, cfg, p, a)), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="summary-%s.pdf"' % p.id})


# ---- импорт истории болезни (проверка врачом) -------------------------------------------------

from .. import importer as IMP  # noqa: E402
import json as _json  # noqa: E402


class ImportIn(BaseModel):
    text: str = Field(min_length=10, max_length=60000)


@router.post("/import", summary="Загрузить текст истории болезни: система предложит кандидатов, врач проверит")
def import_create(body: ImportIn, p: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor, db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    ex = IMP.extract(cfg, body.text)
    job = M.ImportJob(patient_id=p.id, created_by=user.id, source_text=body.text, extracted=ex)
    db.add(job)
    db.flush()
    audit.log(db, user, "import.create", "import", job.id, p.id, items=len(ex["items"]))
    return {"job_id": job.id, "items": list(enumerate(ex["items"])), "status": job.status}


class ImportApply(BaseModel):
    accept: list[int]


@router.post("/import/{job_id}/apply", summary="Принять выбранные кандидатов в карточку (остальное отбрасывается)")
def import_apply(job_id: int, body: ImportApply, p: M.Patient = Depends(patient_for_doctor), user: M.User = Doctor,
                 db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    from fastapi import HTTPException
    job = db.get(M.ImportJob, job_id)
    if job is None or job.patient_id != p.id:
        raise HTTPException(404, "не найдено")
    if job.status != "awaiting_review":
        raise HTTPException(409, "уже обработано")
    items = job.extracted["items"]
    applied = []
    for i in body.accept:
        if not (0 <= i < len(items)):
            raise HTTPException(422, "нет кандидата %d" % i)
        it = items[i]
        if it["kind"] == "dx_icd10":
            db.add(M.ProfileFieldValue(patient_id=p.id, field_id="dx_icd10", value=_json.dumps(it["value"]), entered_by=user.id))
        elif it["kind"] == "egfr_ml_min":
            db.add(M.ProfileFieldValue(patient_id=p.id, field_id="egfr_ml_min", value=_json.dumps(it["value"]), entered_by=user.id))
        elif it["kind"] == "med":
            db.add(M.MedItem(patient_id=p.id, name=it["value"], dose=it.get("dose"), source="import", confirmed_by_doctor=False))
            db.add(M.ProfileFieldValue(patient_id=p.id, field_id="meds_confirmed", value=_json.dumps("unknown"), entered_by=user.id))
        else:
            continue  # справочные кандидаты (шкалы, упоминания) в расчёт не входят
        applied.append(i)
    job.status, job.reviewed_by = "applied", user.id
    audit.log(db, user, "import.apply", "import", job.id, p.id, applied=applied, rejected=len(items) - len(applied))
    db.flush()
    core.assess_patient(db, cfg, p, persist=True)
    return {"ok": True, "applied": applied}
