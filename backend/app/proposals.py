"""Предложения системы и решения врача.

ЕДИНСТВЕННЫЙ путь создания назначения (TherapyOrder), направления (Referral) и статуса динамики (StatusChange) —
решение врача по предложению (Proposal). Нигде в коде эти сущности не создаются иначе (проверяется тестом по исходникам).
Система создаёт только предложения «ожидает подтверждения врача».

Решения: confirm / modify / reject. Отклонение требует причину.
Подтверждать может только лечащий врач пациента: психиатр и дежурный клинических решений за первичного врача не подтверждают.
При подтверждении назначения проверка препарата выполняется заново: если данные изменились (противопоказание, красный алерт),
подтверждение отклоняется.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import audit, clock, models as M
from .config_loader import Config


class ProposalError(ValueError):
    def __init__(self, msg: str, status: int = 422):
        super().__init__(msg)
        self.status = status


def _open_key(patient_id: int, kind: str, key: str) -> str:
    return "%s:%s:%s" % (patient_id, kind, key)


def _upsert(db: Session, patient: M.Patient, kind: str, key: str, payload: dict, basis: dict) -> Optional[M.Proposal]:
    ok = _open_key(patient.id, kind, key)
    ex = db.execute(select(M.Proposal).where(M.Proposal.open_key == ok)).scalar_one_or_none()
    if ex:
        ex.payload, ex.basis = payload, basis
        return None
    p = M.Proposal(patient_id=patient.id, kind=kind, key=key, payload=payload, basis=basis, open_key=ok, status="pending")
    try:
        with db.begin_nested():
            db.add(p)
            db.flush()
    except IntegrityError:
        return None
    audit.log(db, None, "proposal.created", "proposal", p.id, patient.id, kind=kind, key=key)
    return p


def sync_proposals(db: Session, cfg: Config, patient: M.Patient, assessment: Dict[str, Any]) -> List[M.Proposal]:
    """Создать предложения по результату оценки; снять те, что больше не обоснованы (superseded)."""
    created: List[M.Proposal] = []
    wanted = set()
    ts = assessment.get("therapy_suggestion")
    on_therapy = db.execute(select(M.TherapyOrder.id).where(M.TherapyOrder.patient_id == patient.id, M.TherapyOrder.stopped_at.is_(None))).first()
    if ts and not on_therapy:  # назначение уже подтверждено и действует — не предлагать повторно
        wanted.add(_open_key(patient.id, "therapy", ts["drug"]["inn"]))
        p = _upsert(db, patient, "therapy", ts["drug"]["inn"], ts, ts["basis"])
        if p:
            created.append(p)
    active = set(db.execute(select(M.Referral.rule_id).where(M.Referral.patient_id == patient.id, M.Referral.status.in_(("awaiting_acceptance", "accepted")))).scalars().all())
    for kind in ("mandatory", "desirable"):
        for card in assessment["routing"][kind]:
            if card["rule_id"] in active:  # направление уже подтверждено и действует — не предлагать повторно
                continue
            wanted.add(_open_key(patient.id, "routing", card["rule_id"]))
            p = _upsert(db, patient, "routing", card["rule_id"], card, card["basis"])
            if p:
                created.append(p)
    for st in assessment.get("status_suggestions", []):
        wanted.add(_open_key(patient.id, "status", st["status"]))
        p = _upsert(db, patient, "status", st["status"], st, st["basis"])
        if p:
            created.append(p)
    for ex in db.execute(select(M.Proposal).where(M.Proposal.patient_id == patient.id, M.Proposal.status == "pending")).scalars():
        if ex.open_key not in wanted:
            ex.status, ex.open_key, ex.decided_at = "superseded", None, clock.now()
            ex.reason = "условия предложения перестали выполняться (данные изменились)"
    return created


def _check_actor(db: Session, user: M.User, proposal: M.Proposal) -> M.Patient:
    patient = db.get(M.Patient, proposal.patient_id)
    if user.role != "doctor" or patient.doctor_id != user.id:
        raise ProposalError("решение по предложению принимает только лечащий врач этого пациента", 403)
    return patient


def decide(db: Session, cfg: Config, proposal: M.Proposal, user: M.User, decision: str, reason: Optional[str] = None,
           changes: Optional[dict] = None) -> M.Proposal:
    from . import core
    if decision not in ("confirm", "modify", "reject"):
        raise ProposalError("decision: confirm | modify | reject")
    patient = _check_actor(db, user, proposal)
    if proposal.status != "pending":
        raise ProposalError("предложение уже обработано (%s)" % proposal.status, 409)
    if decision == "reject":
        if not reason or not reason.strip():
            raise ProposalError("отклонение требует причину")
        proposal.status = "rejected"
    else:
        if decision == "modify" and not changes:
            raise ProposalError("для изменения укажите changes")
        _apply(db, cfg, proposal, patient, user, decision, changes or {})
        proposal.status = "confirmed" if decision == "confirm" else "modified"
    proposal.decided_by, proposal.decided_at, proposal.reason = user.id, clock.now(), reason
    proposal.decision_data = changes
    proposal.open_key = None
    audit.log(db, user, "proposal.%s" % decision, "proposal", proposal.id, patient.id, kind=proposal.kind, reason=reason)
    return proposal


def _apply(db: Session, cfg: Config, p: M.Proposal, patient: M.Patient, user: M.User, decision: str, changes: dict) -> None:
    from . import core
    now = clock.now()
    if p.kind == "therapy":
        a = core.assess_patient(db, cfg, patient, persist=False)
        d = a["drug_check"]
        if d["state"] != "indicated_pending_doctor" or not d["gating"]["show_positive"]:
            raise ProposalError("проверка препарата изменилась (%s): подтверждение невозможно, пересмотрите карточку" % d["state"], 409)
        reg = dict(cfg.drug["dosing_reference"])
        reg.pop("status", None)
        if decision == "modify":
            reg["doctor_changes"] = changes
        order = M.TherapyOrder(patient_id=patient.id, drug_id=cfg.drug["id"], regimen=reg, proposal_id=p.id,
                               confirmed_by=user.id, confirmed_at=now, started_on=now.date())
        db.add(order)
    elif p.kind == "routing":
        from .summary import build_summary
        card = p.payload
        hours = card.get("due_hours")
        a = core.assess_patient(db, cfg, patient, persist=False)
        ref = M.Referral(patient_id=patient.id, rule_id=card["rule_id"], kind=card["kind"], tier=card["timing_tier"],
                         due_at=now + timedelta(hours=hours) if hours else None, proposal_id=p.id, confirmed_by=user.id,
                         confirmed_at=now, summary=build_summary(db, cfg, patient, a))
        if decision == "modify" and changes.get("deferred_until"):
            from datetime import datetime
            ref.deferred_until = datetime.fromisoformat(changes["deferred_until"])
        db.add(ref)
        db.flush()
        db.add(M.ReferralEvent(referral_id=ref.id, kind="created", actor_id=user.id, at=now))
    elif p.kind == "status":
        db.add(M.StatusChange(patient_id=patient.id, status=p.payload["status"], proposal_id=p.id, confirmed_by=user.id, confirmed_at=now))
    else:
        raise ProposalError("неизвестный тип предложения")


def manual_referral(db: Session, cfg: Config, patient: M.Patient, user: M.User, rule_id: str, comment: Optional[str] = None) -> M.Referral:
    """Направление к психиатру, созданное врачом вручную: врач выбирает основание из правил маршрутизации.
    Это тоже решение врача — фиксируется как подтверждённое им предложение (kind=routing) и событие «создано»."""
    from . import core
    from .summary import build_summary
    if patient.doctor_id != user.id:
        raise ProposalError("пациент не найден среди ваших пациентов", 404)
    rules = {r["id"]: ("mandatory", r) for r in cfg.routing_mandatory}
    rules.update({r["id"]: ("desirable", r) for r in cfg.routing_desirable})
    if rule_id not in rules:
        raise ProposalError("основание направления не найдено в правилах маршрутизации")
    kind, rule = rules[rule_id]
    active = db.execute(select(M.Referral).where(M.Referral.patient_id == patient.id, M.Referral.rule_id == rule_id,
                                                 M.Referral.status.in_(("awaiting_acceptance", "accepted")))).scalars().first()
    if active:
        raise ProposalError("по этому основанию направление уже создано и действует", 409)
    now = clock.now()
    tt = rule.get("timing_tier")
    tier = (tt.get("value") if isinstance(tt, dict) else tt) or "planned"
    hours = cfg.bindings.get("tier_hours", {}).get(tier, {}).get("hours")
    payload = {"rule_id": rule_id, "kind": kind, "title": rule["title"], "text": rule.get("text") or rule["title"], "timing_tier": tier,
               "manual": True, "comment": (comment or "").strip() or None}
    prop = M.Proposal(patient_id=patient.id, kind="routing", key=rule_id, payload=payload,
                      basis={"source": rule.get("source"), "status": "doctor_manual"}, status="confirmed",
                      decided_by=user.id, decided_at=now, reason=payload["comment"], open_key=None)
    db.add(prop)
    db.flush()
    a = core.assess_patient(db, cfg, patient, persist=False)
    ref = M.Referral(patient_id=patient.id, rule_id=rule_id, kind=kind, tier=tier, due_at=now + timedelta(hours=hours) if hours else None,
                     proposal_id=prop.id, confirmed_by=user.id, confirmed_at=now, summary=build_summary(db, cfg, patient, a))
    db.add(ref)
    db.flush()
    db.add(M.ReferralEvent(referral_id=ref.id, kind="created", actor_id=user.id, at=now, note=payload["comment"] or ""))
    audit.log(db, user, "referral.manual", "referral", ref.id, patient.id, rule_id=rule_id)
    return ref


def referral_event(db: Session, ref: M.Referral, kind: str, user: Optional[M.User] = None, note: str = "", once: bool = True) -> None:
    """Событие хронологии направления (received / accepted / completed)."""
    if once and db.execute(select(M.ReferralEvent).where(M.ReferralEvent.referral_id == ref.id, M.ReferralEvent.kind == kind)).first():
        return
    db.add(M.ReferralEvent(referral_id=ref.id, kind=kind, actor_id=user.id if user else None, at=clock.now(), note=note or ""))

