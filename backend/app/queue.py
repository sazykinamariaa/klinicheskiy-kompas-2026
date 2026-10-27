"""Очередь задач (outbox-паттерн) на таблице БД: доставка уведомлений и таймеры эскалации.

Свойства (проверяются тестами и скриптом bench_alert.py):
  * идемпотентность: ключ idempotency_key уникален, повторная постановка и повторная обработка не дублируют отправку;
  * повторы с нарастающей паузой; при исчерпании попыток — переключение на запасной канал и немедленная эскалация;
  * устойчивость к сбоям: задача записана в БД до отправки, сбой канала или перезапуск процесса её не теряют
    (задача «в обработке» возвращается в очередь по истечении аренды);
  * «отправка уведомления не равна оказанию помощи»: уведомление не закрывает и не подтверждает алерт.
Для горизонтального масштабирования: на PostgreSQL выборка задач делается с FOR UPDATE SKIP LOCKED
(здесь — compare-and-set по статусу, работает и на SQLite).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import clock, models as M
from .config_loader import Config

# Параметры инфраструктуры (не клинические): задаются окружением
BACKOFF = [int(x) for x in os.environ.get("KK_RETRY_BACKOFF", "5,15,60,300,900").split(",")]
MAX_ATTEMPTS = len(BACKOFF) + 1
LEASE_SECONDS = int(os.environ.get("KK_QUEUE_LEASE", "60"))


class ChannelError(Exception):
    pass


class LocalChannel:
    """Канал доставки (push / sms / в приложении). Сообщение уже сохранено в базе (очередь outbox); внешний провайдер SMS/push
    подключается через тот же интерфейс send(user, text)."""

    def __init__(self, name: str):
        self.name = name
        self.fail_next = 0       # сколько ближайших отправок «упадёт» (для тестов и замеров)
        self.always_fail = False

    def send(self, user: M.User, text: str) -> None:
        if self.always_fail:
            raise ChannelError("канал %s недоступен (имитация)" % self.name)
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ChannelError("временный сбой канала %s (имитация)" % self.name)


CHANNELS: Dict[str, LocalChannel] = {"push": LocalChannel("push"), "sms": LocalChannel("sms"), "in_app": LocalChannel("in_app")}


def reset_channels() -> None:
    for c in CHANNELS.values():
        c.fail_next = 0
        c.always_fail = False


def enqueue(db: Session, kind: str, payload: Dict[str, Any], key: str, due: Optional[datetime] = None,
            alert_id: Optional[int] = None) -> M.Outbox:
    """Поставить задачу. Повторная постановка с тем же ключом возвращает существующую (идемпотентность)."""
    row = M.Outbox(kind=kind, payload=payload, idempotency_key=key, next_attempt_at=due or clock.now(), alert_id=alert_id)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
        return row
    except IntegrityError:
        return db.execute(select(M.Outbox).where(M.Outbox.idempotency_key == key)).scalar_one()


def _claim(db: Session, job: M.Outbox, now: datetime) -> bool:
    """Compare-and-set: только один обработчик получает задачу."""
    res = db.execute(update(M.Outbox).where(M.Outbox.id == job.id, M.Outbox.status.in_(("pending", "processing")),
                                            M.Outbox.next_attempt_at <= now)
                     .values(status="processing", next_attempt_at=now + timedelta(seconds=LEASE_SECONDS)))
    db.commit()
    return res.rowcount == 1


def process_due(db: Session, cfg: Config, limit: int = 200) -> Dict[str, int]:
    now = clock.now()
    stats = {"sent": 0, "retry": 0, "dead": 0, "skipped": 0, "escalated": 0}
    ids = db.execute(select(M.Outbox.id).where(M.Outbox.status.in_(("pending", "processing")), M.Outbox.next_attempt_at <= now)
                     .order_by(M.Outbox.id).limit(limit)).scalars().all()
    for jid in ids:
        job = db.get(M.Outbox, jid)
        if job is None or not _claim(db, job, now):
            continue
        db.refresh(job)
        try:
            if job.kind == "notify":
                _do_notify(db, cfg, job, stats)
            elif job.kind == "escalate":
                _do_escalate(db, cfg, job, stats)
            else:
                job.status, job.sent_at = "sent", clock.now()
                stats["sent"] += 1
        except Exception as e:  # непредвиденная ошибка обработчика не должна терять задачу
            _fail(db, cfg, job, "обработчик: %r" % e, stats)
        db.commit()
    return stats


def _event(db: Session, alert_id: Optional[int], kind: str, **data: Any) -> None:
    if alert_id:
        db.add(M.AlertEvent(alert_id=alert_id, kind=kind, data=data))


def _do_notify(db: Session, cfg: Config, job: M.Outbox, stats: Dict[str, int]) -> None:
    p = job.payload
    user = db.get(M.User, p["user_id"])
    channel = p["channel"]
    # идемпотентность доставки: уже доставлено этому адресату по этому каналу — не повторять
    dup = db.execute(select(M.NotificationLog).where(M.NotificationLog.outbox_id == job.id, M.NotificationLog.status == "delivered")).first()
    if dup:
        job.status = "sent"
        stats["skipped"] += 1
        return
    if job.alert_id and p.get("skip_if_accepted"):
        a = db.get(M.Alert, job.alert_id)
        if a and a.accepted_at:
            job.status = "skipped"
            stats["skipped"] += 1
            return
    try:
        CHANNELS[channel].send(user, p["text"])
    except Exception as e:
        db.add(M.NotificationLog(outbox_id=job.id, alert_id=job.alert_id, channel=channel, recipient=user.login, status="failed", detail=str(e)))
        _fail(db, cfg, job, str(e), stats)
        return
    now = clock.now()
    db.add(M.NotificationLog(outbox_id=job.id, alert_id=job.alert_id, channel=channel, recipient=user.login, status="delivered", ts=now))
    _event(db, job.alert_id, "notified", user=user.login, channel=channel, text_kind=p.get("kind"))
    job.status, job.sent_at, job.attempts = "sent", now, job.attempts + 1
    stats["sent"] += 1


def _fail(db: Session, cfg: Config, job: M.Outbox, err: str, stats: Dict[str, int]) -> None:
    job.attempts += 1
    job.last_error = err[:500]
    if job.attempts < MAX_ATTEMPTS:
        job.status = "pending"
        job.next_attempt_at = clock.now() + timedelta(seconds=BACKOFF[min(job.attempts - 1, len(BACKOFF) - 1)])
        stats["retry"] += 1
        return
    job.status = "dead"
    stats["dead"] += 1
    _event(db, job.alert_id, "delivery_failed", channel=job.payload.get("channel"), user_id=job.payload.get("user_id"), error=err[:200])
    if job.kind == "notify":
        # запасной канал и немедленная эскалация: красный алерт не должен потеряться из-за сбоя канала
        other = "sms" if job.payload.get("channel") == "push" else "push"
        if job.payload.get("channel") != other and not job.payload.get("fallback"):
            enqueue(db, "notify", dict(job.payload, channel=other, fallback=True), job.idempotency_key + ":fb", alert_id=job.alert_id)
        if job.alert_id and job.payload.get("level") == "red":
            enqueue(db, "escalate", {"alert_id": job.alert_id, "step": "delivery_failure", "to": "duty_doctor", "reason": "delivery_failed"},
                    "alert:%s:esc:delivery_failure:%s" % (job.alert_id, job.payload.get("user_id")), alert_id=job.alert_id)


def _do_escalate(db: Session, cfg: Config, job: M.Outbox, stats: Dict[str, int]) -> None:
    from .alerts_service import notify_targets, staff_text  # во избежание циклического импорта
    p = job.payload
    alert = db.get(M.Alert, job.alert_id)
    if alert is None or alert.closed_at or (alert.accepted_at and p.get("reason") != "delivery_failed"):
        job.status = "skipped"
        stats["skipped"] += 1
        return
    patient = db.get(M.Patient, alert.patient_id)
    users = notify_targets(db, cfg, patient, p["to"])
    if not users:
        _event(db, alert.id, "escalation_target_missing", to=p["to"])
    channels = [c for c in cfg["alert_rules"]["levels"][0]["notify"]["channels"] if cfg["clinic_settings"]["notification_channels"].get(c)]
    for u in users:
        for ch in channels:
            enqueue(db, "notify", {"user_id": u.id, "channel": ch, "level": alert.level, "kind": "escalation",
                                   "text": staff_text(alert, patient, escalation=True)},
                    "alert:%s:esc:%s:%s:%s" % (alert.id, p["step"], u.id, ch), alert_id=alert.id)
    _event(db, alert.id, "escalated", to=p["to"], step=p["step"], recipients=[u.login for u in users])
    job.status, job.sent_at = "sent", clock.now()
    stats["escalated"] += 1


def overview(db: Session) -> Dict[str, Any]:
    """Сводка очереди для панели администратора (без клинических данных)."""
    from sqlalchemy import func
    rows = db.execute(select(M.Outbox.status, func.count()).group_by(M.Outbox.status)).all()
    return {"by_status": {s: n for s, n in rows}}
