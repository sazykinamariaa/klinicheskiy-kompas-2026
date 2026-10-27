"""Начальные данные базы: пользователи всех ролей и пациенты S1–S8 (scenarios.json и seed_data.py).

Пациенты создаются теми же таблицами, что и при обычной работе; даты сдвигаются так, чтобы последняя точка приходилась на «сейчас».
Назначения и направления создаются только штатным путём (proposals.py): предложение системы или выбор основания врачом.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import clock, core, seed_data as FX, models as M, scales as SC
from .config_loader import Config
from .security import hash_password

INIT_PASSWORD = os.environ.get("KK_INIT_PASSWORD", "Kompas2026x")  # начальный пароль; смените после первого входа

USERS = [
    ("admin", "admin", "Администратор системы", None),
    ("doctor1", "doctor", "Врач-терапевт 1", None),
    ("doctor2", "doctor", "Врач-терапевт 2", None),
    ("duty", "duty", "Дежурный врач", "duty_doctor"),
    ("psychiatrist", "psychiatrist", "Психиатр", None),
]
REMOVED_LOGINS = ["clinic_admin", "staff"]  # в базах прежних версий отключаются (_normalize)

# Раскладка по трём сценариям ТЗ: первичное обращение — S1 (Авиандр можно рассмотреть), S2 (СКФ < 60);
# лечение Авиандром — S3 (хорошая динамика), S4 (нежелательное явление, нет заметного улучшения); ухудшение с алертом — S5.
SCENARIOS = [("S1", FX.s1, 0), ("S2", FX.s2, 0), ("S3", FX.s3_treatment, 6), ("S4", FX.s4_treatment_ae, 4), ("S5", FX.s5, 3)]
# Пациенты врача-терапевта 2 на лечении, подтверждённые психиатром: у каждого свой диагноз (F41.1, F41.9, F43.9)
CONFIRMED = [("S6", FX.s6, 8), ("S7", FX.s7, 6), ("S8", FX.s8, 4)]


def _user(db: Session, login: str, role: str, name: str, duty_role: str = None) -> M.User:
    u = db.execute(select(M.User).where(M.User.login == login)).scalar_one_or_none()
    if u:
        return u
    u = M.User(login=login, password_hash=hash_password(INIT_PASSWORD), role=role, name=name, duty_role=duty_role, phone="+7 900 000-00-00")
    db.add(u)
    db.flush()
    return u


def seed_users(db: Session) -> Dict[str, M.User]:
    return {login: _user(db, login, role, name, dr) for login, role, name, dr in USERS}


def _shift(v: Any, delta: timedelta) -> Any:
    if isinstance(v, datetime):
        return v + delta
    if isinstance(v, date):
        return v + delta
    return v


def _confirm_therapy(db, cfg, p, doctor, started_on):
    """Назначение создаётся только штатным путём: предложение системы → подтверждение врача."""
    from . import proposals as PR
    a = core.assess_patient(db, cfg, p, persist=False)  # без алертов: на момент первичного приёма они уже неактуальны
    PR.sync_proposals(db, cfg, p, a)
    db.flush()
    prop = db.execute(select(M.Proposal).where(M.Proposal.patient_id == p.id, M.Proposal.kind == "therapy", M.Proposal.status == "pending")).scalars().first()
    if prop is None:
        return None
    try:
        PR.decide(db, cfg, prop, doctor, "confirm", reason="назначение подтверждено врачом на первичном приёме")
    except PR.ProposalError:
        return None
    db.flush()
    order = db.execute(select(M.TherapyOrder).where(M.TherapyOrder.patient_id == p.id).order_by(M.TherapyOrder.id.desc())).scalars().first()
    if order is not None:
        order.started_on = started_on
        order.confirmed_at = datetime.combine(started_on, datetime.min.time()) + timedelta(hours=10)
        prop.decided_at = order.confirmed_at
        db.flush()
    return order



def seed_scenario(db: Session, cfg: Config, doctor: M.User, code: str, builder, week: int) -> M.Patient:
    st = builder(cfg, week)
    delta = clock.now() - st["now"]
    existing = db.execute(select(M.Patient).where(M.Patient.doctor_id == doctor.id, M.Patient.code == code)).scalar_one_or_none()
    if existing:
        return existing
    age = st["profile"]["age"]
    birth = (clock.now().date() - timedelta(days=int(age * 365.25) + 100)).isoformat()
    login = "patient_" + code.lower()
    pu = _user(db, login, "patient", code)
    p = M.Patient(code=code, sex=st["profile"]["sex"], birth_date=birth, doctor_id=doctor.id, user_id=pu.id, status="active", synthetic=False)
    db.add(p)
    db.flush()
    db.add(M.Consent(patient_id=p.id, version="stub-0", text_status="stub_pending_legal"))
    for fid, v in st["profile"]["fields"].items():
        db.add(M.ProfileFieldValue(patient_id=p.id, field_id=fid, value=json.dumps(v, ensure_ascii=False), entered_by=doctor.id))
    intake = dict(FX.INTAKE_DISPLAY.get(code, {}))  # остальные ответы анкеты (не влияют на правила)
    intake.update(st["intake"])
    for qid, v in intake.items():
        db.add(M.IntakeAnswer(patient_id=p.id, question_id=qid, answer=json.dumps(v, ensure_ascii=False)))
    th = (st.get("therapy") or {}).get("started_on")
    limit = datetime.combine(th, datetime.min.time()) + timedelta(days=3) if th else None
    early = [r for r in st["scale_runs"] if limit is None or r["at"] <= limit]
    late = [r for r in st["scale_runs"] if limit is not None and r["at"] > limit]
    def add_runs(rows):
        for r in rows:
            res = SC.score(cfg, r["scale_id"], r["answers"])
            at = _shift(r["at"], delta)
            db.add(M.ScaleRun(patient_id=p.id, scale_id=r["scale_id"], answers=res["answers"], complete=res["complete"], total=res["total"],
                              started_at=at, completed_at=at))
    def add_meds(rows):
        for m in rows:
            name, dose = (m["name"], m.get("dose")) if isinstance(m, dict) else (m, None)
            db.add(M.MedItem(patient_id=p.id, name=name, dose=dose, source="doctor", confirmed_by_doctor=True))
    add_runs(early)
    own = cfg.drug["inn"].lower()
    pre = [m for m in st["meds"]["items"] if not th or own not in (m["name"] if isinstance(m, dict) else m).lower()]
    post = [m for m in st["meds"]["items"] if th and own in (m["name"] if isinstance(m, dict) else m).lower()]
    add_meds(pre)
    for name, s in st.get("symptoms", {}).items():
        db.add(M.SymptomEntry(patient_id=p.id, name=name, present=s["present"], duration_weeks=s.get("duration_weeks"), entered_by=doctor.id))
    if th:
        db.flush()
        _confirm_therapy(db, cfg, p, doctor, _shift(th, delta))
        add_runs(late)
        add_meds(post)
    ck = st.get("checkin")
    if ck:
        p.checkin_enabled_on = _shift(ck["enabled_on"], delta)
        for e in ck["entries"]:
            db.add(M.Checkin(patient_id=p.id, day=_shift(e["date"], delta), answers=e["answers"], complete=False))
    for e in st.get("adherence_events", []):
        db.add(M.AdherenceEvent(patient_id=p.id, day=_shift(e["date"], delta), kind=e["kind"]))
    sf = st.get("safety_followup")
    if sf:
        db.add(M.SafetyFollowup(patient_id=p.id, answers=sf["answers"], complete=sf["complete"], started_at=clock.now(), completed_at=clock.now()))
    ae = st.get("ae")
    if ae:
        db.add(M.AEReport(patient_id=p.id, severity=ae["severity"], urgent_flag=ae.get("urgent_flag", False), persists=ae.get("persists"),
                          worsening=ae.get("worsening"), details=ae.get("details", {}), created_at=clock.now() - timedelta(days=ae.get("days_ago", 0))))
    goal = st.get("goal")
    if goal:
        db.add(M.Goal(patient_id=p.id, text=goal["text"], set_by=pu.id if goal.get("by") == "patient" else doctor.id))
    db.flush()
    return p


def seed_initial(db: Session, cfg: Config) -> Dict[str, Any]:
    users = seed_users(db)
    _normalize(db)
    pats = []
    for code, builder, week in SCENARIOS + CONFIRMED:
        doctor = users["doctor2" if code in FX.PSY_CONFIRMED else "doctor1"]
        p = seed_scenario(db, cfg, doctor, code, builder, week)
        if code in FX.VISITS and not db.execute(select(M.Visit).where(M.Visit.patient_id == p.id)).first():
            days, hhmm, note = FX.VISITS[code]
            h, m = (int(x) for x in hhmm.split(":"))
            at = datetime.combine(clock.now().date() + timedelta(days=days), datetime.min.time()) + timedelta(hours=h, minutes=m)
            db.add(M.Visit(patient_id=p.id, at=at, note=note, created_by=doctor.id))
        if code in FX.INTAKE_REVIEWED and not db.execute(select(M.DoctorMark).where(M.DoctorMark.patient_id == p.id)).first():
            db.add(M.DoctorMark(patient_id=p.id, kind="intake_reviewed", by=doctor.id))
        core.assess_patient(db, cfg, p, persist=True)
        if code == "S2":
            _refer_pending(db, cfg, p, doctor, "D-DRUG-CI")
        if code in FX.PSY_CONFIRMED:
            _psy_confirm(db, cfg, p, doctor, users["psychiatrist"], *FX.PSY_CONFIRMED[code])
        pats.append(p.id)
    if not db.execute(select(M.ShiftHandover)).first():  # журнал смен: прошлая смена передана и подтверждена
        now = clock.now()
        db.add(M.ShiftHandover(author_id=users["duty"].id, next_responsible_id=users["duty"].id, created_at=now - timedelta(hours=14),
                               confirmed_by=users["duty"].id, confirmed_at=now - timedelta(hours=13, minutes=40),
                               data={"open_cases": [], "waiting": [], "auto_done": [], "open_cases_note": "Незакрытых критических случаев нет.",
                                     "waiting_note": "", "done_actions": "Сигналы смены просмотрены, действия зафиксированы.",
                                     "next_steps": "Утром проверить новые сигналы и ответы специалистов."}))
    return {"users": {u: INIT_PASSWORD for u in users}, "patients": pats,
            "patient_logins": {"patient_s%d" % i: INIT_PASSWORD for i in range(1, 9)}}


def _normalize(db: Session) -> None:
    """База, заполненная прежней версией: убрать пометки «демо» и признак «синтетические данные»."""
    for u in db.execute(select(M.User).where(M.User.login.in_(REMOVED_LOGINS))).scalars():  # логины, убранные из демо
        u.active = False
    names = {login: name for login, _, name, _ in USERS}
    for u in db.execute(select(M.User).where(M.User.login.in_(list(names)))).scalars():
        if "(демо)" in (u.name or ""):
            u.name = names[u.login]
    for p in db.execute(select(M.Patient).where(M.Patient.synthetic.is_(True))).scalars():
        p.synthetic = False


def _refer_pending(db: Session, cfg: Config, p: M.Patient, doctor: M.User, key: str) -> None:
    """Направление, подтверждённое врачом и ещё не подтверждённое психиатром (группа «Новые пациенты»)."""
    from . import proposals as PR
    if db.execute(select(M.Referral).where(M.Referral.patient_id == p.id)).first():
        return
    prop = db.execute(select(M.Proposal).where(M.Proposal.patient_id == p.id, M.Proposal.kind == "routing", M.Proposal.key == key,
                                               M.Proposal.status == "pending")).scalars().first()
    if prop is not None:
        PR.decide(db, cfg, prop, doctor, "confirm")
        db.flush()


def _psy_confirm(db: Session, cfg: Config, p: M.Patient, doctor: M.User, psy: M.User, rule_id: str, ref_day: int, acc_day: int, note: str) -> None:
    """Направление врача и подтверждение психиатром с заключением; даты — от начала лечения."""
    from . import proposals as PR
    from .routers.psy_notes import PsychNote
    if db.execute(select(M.Referral).where(M.Referral.patient_id == p.id)).first():
        return
    r = PR.manual_referral(db, cfg, p, doctor, rule_id, "Пациент на лечении, прошу подтвердить диагноз и тактику.")
    order = db.execute(select(M.TherapyOrder).where(M.TherapyOrder.patient_id == p.id)).scalars().first()
    start = datetime.combine(order.started_on, datetime.min.time()) if order else clock.now() - timedelta(days=acc_day + 7)
    t_ref, t_acc = start + timedelta(days=ref_day, hours=11), start + timedelta(days=acc_day, hours=15)
    r.confirmed_at = t_ref
    PR.referral_event(db, r, "received", psy)
    PR.referral_event(db, r, "accepted", psy)
    r.status = "accepted"
    db.flush()
    for ev in db.execute(select(M.ReferralEvent).where(M.ReferralEvent.referral_id == r.id)).scalars():
        ev.at = {"received": t_ref + timedelta(hours=3), "accepted": t_acc}.get(ev.kind, t_ref)
    db.add(PsychNote(referral_id=r.id, author_id=psy.id, decision="advice_to_doctor", comment=note, ts=t_acc + timedelta(minutes=40)))
    db.flush()
