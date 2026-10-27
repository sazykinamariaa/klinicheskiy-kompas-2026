"""Модель данных «Клинического компаса».

Покрывает сущности, нужные задачам инструмента: пользователи и роли; пациент и связка «врач–пациент»;
приглашение и согласие; анкета; прохождения шкал; уточняющие вопросы безопасности; чек-ины; приверженность;
нежелательные явления; клинический профиль (версии полей); алерты и их журнал; предложения системы и решения врача;
назначения, направления, статусы динамики (создаются ТОЛЬКО через подтверждение врача); сообщения; «Мой план»; цель;
очередь доставки (outbox) и журнал уведомлений; журнал аудита; импорт историй болезни.
Персональные поля шифруются при хранении (EncryptedText). Клинические значения здесь не хранятся: это данные пациента.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .security import EncryptedText
from . import clock


def _now() -> datetime:
    return clock.now()


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), index=True)  # patient|doctor|duty|psychiatrist|admin
    name: Mapped[str] = mapped_column(EncryptedText, default="")
    phone: Mapped[Optional[str]] = mapped_column(EncryptedText, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    duty_role: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # duty_doctor|clinic_admin_on_duty
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Token(Base):
    __tablename__ = "tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), index=True)  # код или псевдоним
    sex: Mapped[Optional[str]] = mapped_column(String(2))
    birth_date: Mapped[Optional[str]] = mapped_column(EncryptedText, nullable=True)  # ISO-дата, шифруется
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(30), default="invited")  # invited|active|archived
    checkin_enabled_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    __table_args__ = (UniqueConstraint("doctor_id", "code", name="uq_doctor_code"),)


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Consent(Base):
    __tablename__ = "consents"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    version: Mapped[str] = mapped_column(String(40))
    text_status: Mapped[str] = mapped_column(String(60))  # заглушка до юридического текста
    accepted_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ProfileFieldValue(Base):
    """Клинический профиль: каждое изменение — новая запись (история сохраняется)."""
    __tablename__ = "profile_field_values"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    field_id: Mapped[str] = mapped_column(String(60), index=True)
    value: Mapped[Optional[str]] = mapped_column(EncryptedText, nullable=True)  # JSON-строка
    entered_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    entered_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    __table_args__ = (Index("ix_pfv_patient_field", "patient_id", "field_id", "id"),)


class IntakeAnswer(Base):
    __tablename__ = "intake_answers"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    question_id: Mapped[str] = mapped_column(String(20))
    answer: Mapped[Optional[str]] = mapped_column(EncryptedText)  # JSON
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    __table_args__ = (UniqueConstraint("patient_id", "question_id", name="uq_intake"),)


class ScaleRun(Base):
    __tablename__ = "scale_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    scale_id: Mapped[str] = mapped_column(String(30), index=True)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    complete: Mapped[bool] = mapped_column(Boolean, default=False)
    total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    __table_args__ = (Index("ix_scale_patient_scale", "patient_id", "scale_id", "started_at"),)


class SafetyFollowup(Base):
    __tablename__ = "safety_followups"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    complete: Mapped[bool] = mapped_column(Boolean, default=False)
    sf6_days_ago: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Checkin(Base):
    __tablename__ = "checkins"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    complete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    __table_args__ = (UniqueConstraint("patient_id", "day", name="uq_checkin_day"),)


class AdherenceEvent(Base):
    __tablename__ = "adherence_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(40))  # confirmed_taken|confirmed_missed|confirmed_missed_partial|self_discontinuation
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class AEReport(Base):
    __tablename__ = "ae_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    severity: Mapped[str] = mapped_column(String(30))  # mild|moderate|moderate_to_severe
    urgent_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    persists: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    worsening: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ClinicianFlag(Base):
    __tablename__ = "clinician_flags"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    flag: Mapped[str] = mapped_column(String(60))  # immediate_threat|secondary_cause_suspected
    value: Mapped[bool] = mapped_column(Boolean)
    set_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SymptomEntry(Base):
    __tablename__ = "symptom_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    present: Mapped[str] = mapped_column(String(10))  # yes|no|unknown
    duration_weeks: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entered_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class MedItem(Base):
    __tablename__ = "med_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    dose: Mapped[Optional[str]] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(20), default="patient")  # patient|doctor|import
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    confirmed_by_doctor: Mapped[bool] = mapped_column(Boolean, default=False)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    rule_id: Mapped[str] = mapped_column(String(40), index=True)
    level: Mapped[str] = mapped_column(String(10), index=True)
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="new", index=True)
    basis: Mapped[dict] = mapped_column(JSON, default=dict)
    facts: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    accepted_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    close_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after_hours: Mapped[bool] = mapped_column(Boolean, default=False)
    patient_notice: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    open_key: Mapped[Optional[str]] = mapped_column(String(80), unique=True, nullable=True)  # одно открытое на правило


class AlertEvent(Base):
    __tablename__ = "alert_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_now)
    kind: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Outbox(Base):
    """Очередь задач: доставка уведомлений и таймеры эскалации. Идемпотентна по idempotency_key, устойчива к сбоям."""
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)  # notify|escalate|reminder
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(15), default="pending", index=True)  # pending|sent|dead|skipped
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    alert_id: Mapped[Optional[int]] = mapped_column(ForeignKey("alerts.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class NotificationLog(Base):
    __tablename__ = "notification_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    outbox_id: Mapped[Optional[int]] = mapped_column(ForeignKey("outbox.id"), nullable=True)
    alert_id: Mapped[Optional[int]] = mapped_column(ForeignKey("alerts.id"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(15))
    recipient: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(15))  # delivered|failed
    ts: Mapped[datetime] = mapped_column(DateTime, default=_now)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Proposal(Base):
    """Предложение системы. Единственный путь к назначению, направлению и смене статуса — решение врача по предложению."""
    __tablename__ = "proposals"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)  # therapy|routing|status
    key: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    basis: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(15), default="pending", index=True)  # pending|confirmed|modified|rejected|superseded
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    decided_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decision_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    open_key: Mapped[Optional[str]] = mapped_column(String(160), unique=True, nullable=True)


class TherapyOrder(Base):
    __tablename__ = "therapy_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    drug_id: Mapped[str] = mapped_column(String(40))
    regimen: Mapped[dict] = mapped_column(JSON, default=dict)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id"), unique=True)
    confirmed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    started_on: Mapped[date] = mapped_column(Date)
    stopped_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    off_label: Mapped[bool] = mapped_column(Boolean, default=False)


class Referral(Base):
    __tablename__ = "referrals"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    rule_id: Mapped[str] = mapped_column(String(30))
    kind: Mapped[str] = mapped_column(String(15))  # mandatory|desirable
    tier: Mapped[str] = mapped_column(String(10))
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(25), default="awaiting_acceptance")  # awaiting_acceptance|accepted|done|cancelled
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id"), unique=True)
    confirmed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    deferred_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class StatusChange(Base):
    __tablename__ = "status_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))  # response|remission|relapse
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id"), unique=True)
    confirmed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(EncryptedText)
    kind: Mapped[str] = mapped_column(String(20), default="message")  # message|appointment_request|reminder
    ts: Mapped[datetime] = mapped_column(DateTime, default=_now)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class MyPlan(Base):
    __tablename__ = "my_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    sections: Mapped[Optional[str]] = mapped_column(EncryptedText)  # JSON
    version: Mapped[int] = mapped_column(Integer, default=1)
    edited_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    edited_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    confirmed_by_doctor: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Goal(Base):
    __tablename__ = "goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    text: Mapped[str] = mapped_column(EncryptedText)
    set_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class TrustedContact(Base):
    __tablename__ = "trusted_contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), unique=True)
    name: Mapped[str] = mapped_column(EncryptedText)
    phone: Mapped[str] = mapped_column(EncryptedText)
    consent: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    actor_role: Mapped[Optional[str]] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity: Mapped[Optional[str]] = mapped_column(String(40))
    entity_id: Mapped[Optional[str]] = mapped_column(String(40))
    patient_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class ImportJob(Base):
    __tablename__ = "import_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    source_text: Mapped[str] = mapped_column(EncryptedText)
    extracted: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="awaiting_review")  # awaiting_review|applied|discarded
    reviewed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


# ---------------------------------------------------------------- разделы врача (обратная связь медиков)

class Visit(Base):
    """Повторный приём, назначенный врачом (дата и цель визита)."""
    __tablename__ = "visits"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime)
    note: Mapped[str] = mapped_column(EncryptedText, default="")
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class DoctorMark(Base):
    """Отметка врача о просмотре (например, «анкета просмотрена»)."""
    __tablename__ = "doctor_marks"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ReferralEvent(Base):
    """Хронология направления: created → received → accepted → completed."""
    __tablename__ = "referral_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    referral_id: Mapped[int] = mapped_column(ForeignKey("referrals.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    note: Mapped[str] = mapped_column(EncryptedText, default="")


class ShiftHandover(Base):
    """Передача смены дежурного: незакрытые случаи, ожидающие ответа, сделанное, следующие шаги, кому передано."""
    __tablename__ = "shift_handovers"
    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    next_responsible_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class PsyDecision(Base):
    """Решение психиатра по рекомендации системы: подтвердить / изменить / отклонить (с комментарием)."""
    __tablename__ = "psy_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    item_key: Mapped[str] = mapped_column(String(120))
    decision: Mapped[str] = mapped_column(String(10))
    comment: Mapped[str] = mapped_column(EncryptedText, default="")
    by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime, default=_now)
