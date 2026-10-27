"""Алерт-пайплайн: превращает результат оценки в алерты, ставит уведомления в очередь,
ведёт жизненный цикл и закрытие с обязательными полями.

Политика (alert_rules.json, clinic_settings.json, patient_texts.json):
  красный  — немедленно, круглосуточно; push+SMS; подтверждение за N минут, затем эскалация на дежурного, затем на администратора смены;
  оранжевый — врачу; в рабочее время сразу, вне рабочего времени — в очередь на начало следующего рабочего дня
              + информационное уведомление дежурному + честный текст пациенту;
  жёлтый    — в приложении (карточка и сводка).
Система сама скорую не вызывает; «не удалось связаться» красный алерт не закрывает.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import audit, clock, models as M, queue as Q, worktime
from .config_loader import Config

LEVELS_NOTIFY = ("red", "orange")


class AlertError(ValueError):
    """Нарушение правил жизненного цикла (HTTP 409/422)."""

    def __init__(self, msg: str, status: int = 422):
        super().__init__(msg)
        self.status = status


def _level_cfg(cfg: Config, level: str) -> dict:
    return next(l for l in cfg["alert_rules"]["levels"] if l["id"] == level)


def staff_text(alert: M.Alert, patient: M.Patient, escalation: bool = False) -> str:
    from .config_loader import Config  # noqa
    return _tmpl(alert.level, patient, escalation)


_CFG_FOR_TEXT: Optional[Config] = None


def set_text_config(cfg: Config) -> None:
    global _CFG_FOR_TEXT
    _CFG_FOR_TEXT = cfg


def _tmpl(level: str, patient: M.Patient, escalation: bool, info_after_hours: bool = False) -> str:
    t = _CFG_FOR_TEXT.bindings["staff_message_templates"]
    key = "orange_info_after_hours" if info_after_hours else (level + ("_escalation" if escalation else ""))
    return t[key].format(code=patient.code)


def notify_targets(db: Session, cfg: Config, patient: M.Patient, role_key: str) -> List[M.User]:
    """Адресаты по роли. Если реальных людей в графике нет (в config стоит [ЖДЁМ]), используются сотрудники из БД с этой
    дежурной ролью; если для роли (ответственный сотрудник, администратор смены) учётной записи нет — дежурный врач;
    если нет и его — пустой список (событие escalation_target_missing видно врачу и администратору)."""
    if role_key == "treating_doctor":
        u = db.get(M.User, patient.doctor_id)
        return [u] if u and u.active else []
    res = list(db.execute(select(M.User).where(M.User.duty_role == role_key, M.User.active.is_(True))).scalars())
    if not res and role_key != "duty_doctor":  # отдельной учётной записи для этой роли нет — получает дежурный врач
        return notify_targets(db, cfg, patient, "duty_doctor")
    return res


def _channels(cfg: Config, level: str) -> List[str]:
    wanted = _level_cfg(cfg, level)["notify"]["channels"]
    enabled = cfg["clinic_settings"]["notification_channels"]
    return [c for c in wanted if enabled.get(c, c == "in_app")]


def sync_alerts(db: Session, cfg: Config, patient: M.Patient, assessment: Dict[str, Any]) -> List[M.Alert]:
    """Создать алерты по результату оценки. Повторная оценка тех же данных ничего не дублирует (open_key)."""
    created: List[M.Alert] = []
    now = clock.now()
    working = worktime.is_working(cfg, now)
    for card in assessment["alerts"]:
        level = card["level"]
        if level not in ("red", "orange", "yellow"):
            continue
        open_key = "%s:%s" % (patient.id, card["rule_id"])
        existing = db.execute(select(M.Alert).where(M.Alert.open_key == open_key)).scalar_one_or_none()
        if existing:
            existing.facts = card["facts_used"]
            continue
        after_hours = (not working) and level in ("orange", "red")
        alert = M.Alert(patient_id=patient.id, rule_id=card["rule_id"], level=level, title=card["title"], status="new",
                        basis=card["basis"], facts=card["facts_used"], open_key=open_key, created_at=now, after_hours=after_hours)
        if level in LEVELS_NOTIFY and not working:
            alert.patient_notice = cfg["patient_texts"]["after_hours_notice"]["text"].replace("[часы работы]", worktime.hours_text(cfg))
        try:
            with db.begin_nested():
                db.add(alert)
                db.flush()
        except IntegrityError:
            continue
        db.add(M.AlertEvent(alert_id=alert.id, kind="created", data={"rule": card["rule_id"], "level": level, "after_hours": after_hours}, ts=now))
        audit.log(db, None, "alert.created", "alert", alert.id, patient.id, rule=card["rule_id"], level=level)
        _enqueue_notifications(db, cfg, patient, alert, now, working)
        created.append(alert)
    return created


def _enqueue_notifications(db: Session, cfg: Config, patient: M.Patient, alert: M.Alert, now: datetime, working: bool) -> None:
    lvl = _level_cfg(cfg, alert.level)
    chans = _channels(cfg, alert.level)
    if alert.level == "red":
        # немедленно и круглосуточно, не дожидаясь планового ответа лечащего врача
        targets = notify_targets(db, cfg, patient, "treating_doctor") + notify_targets(db, cfg, patient, "responsible_staff")
        seen = set()
        for u in targets:
            if u.id in seen:
                continue
            seen.add(u.id)
            for ch in chans:
                Q.enqueue(db, "notify", {"user_id": u.id, "channel": ch, "level": "red", "kind": "first_wave", "text": _tmpl("red", patient, False)},
                          "alert:%s:notify:%s:%s" % (alert.id, u.id, ch), due=now, alert_id=alert.id)
        for i, step in enumerate(lvl.get("escalation", [])):
            Q.enqueue(db, "escalate", {"alert_id": alert.id, "step": "s%d" % i, "to": step["to"]},
                      "alert:%s:esc:s%d" % (alert.id, i), due=now + timedelta(minutes=step["after_minutes"]), alert_id=alert.id)
        if not seen:
            db.add(M.AlertEvent(alert_id=alert.id, kind="no_first_wave_recipient", data={}))
            Q.enqueue(db, "escalate", {"alert_id": alert.id, "step": "no_recipient", "to": "duty_doctor", "reason": "delivery_failed"},
                      "alert:%s:esc:no_recipient" % alert.id, due=now, alert_id=alert.id)
    elif alert.level == "orange":
        due = now if working else worktime.next_working_start(cfg, now)
        doc = notify_targets(db, cfg, patient, "treating_doctor")
        for u in doc:
            for ch in chans:
                Q.enqueue(db, "notify", {"user_id": u.id, "channel": ch, "level": "orange", "kind": "orange", "text": _tmpl("orange", patient, False)},
                          "alert:%s:notify:%s:%s" % (alert.id, u.id, ch), due=due, alert_id=alert.id)
        if not working:
            for u in notify_targets(db, cfg, patient, "duty_doctor"):
                Q.enqueue(db, "notify", {"user_id": u.id, "channel": "push", "level": "orange", "kind": "info_after_hours",
                                         "text": _tmpl("orange", patient, False, info_after_hours=True)},
                          "alert:%s:info:%s" % (alert.id, u.id), due=now, alert_id=alert.id)
        for step in lvl.get("escalation", []):
            Q.enqueue(db, "escalate", {"alert_id": alert.id, "step": "o%d" % step["after_minutes"], "to": step["to"]},
                      "alert:%s:esc:o%d" % (alert.id, step["after_minutes"]), due=due + timedelta(minutes=step["after_minutes"]), alert_id=alert.id)


# ---- жизненный цикл ------------------------------------------------------------------------

def _ev(db: Session, alert: M.Alert, kind: str, actor: Optional[M.User], **data: Any) -> None:
    db.add(M.AlertEvent(alert_id=alert.id, kind=kind, actor_id=actor.id if actor else None, data=data, ts=clock.now()))


def accept(db: Session, cfg: Config, alert: M.Alert, actor: M.User) -> M.Alert:
    if alert.closed_at:
        raise AlertError("алерт уже закрыт", 409)
    if alert.accepted_at is None:
        alert.accepted_at, alert.accepted_by = clock.now(), actor.id
        if alert.status == "new":
            alert.status = "accepted"
        _ev(db, alert, "accepted", actor)
        audit.log(db, actor, "alert.accept", "alert", alert.id, alert.patient_id)
    return alert


def contact_attempt(db: Session, cfg: Config, alert: M.Alert, actor: M.User, result: str, method: str, note: str = "") -> M.Alert:
    """Попытка связаться. «Не удалось связаться» НЕ закрывает алерт и не гасит эскалацию красного."""
    if alert.closed_at:
        raise AlertError("алерт уже закрыт", 409)
    _ev(db, alert, "contact_attempt", actor, result=result, method=method, note=note)
    audit.log(db, actor, "alert.contact_attempt", "alert", alert.id, alert.patient_id, result=result)
    if result == "reached":
        if alert.accepted_at is None:
            accept(db, cfg, alert, actor)
        alert.status = "contact_established_assessed" if alert.status in ("new", "accepted") else alert.status
    elif alert.level == "red":
        n = len(db.execute(select(M.AlertEvent.id).where(M.AlertEvent.alert_id == alert.id, M.AlertEvent.kind == "contact_attempt")).all())
        Q.enqueue(db, "escalate", {"alert_id": alert.id, "step": "unreachable%d" % n, "to": "duty_doctor", "reason": "delivery_failed"},
                  "alert:%s:esc:unreachable:%d" % (alert.id, n), alert_id=alert.id)
    return alert


def transition(db: Session, cfg: Config, alert: M.Alert, actor: M.User, status: str, data: Optional[dict] = None) -> M.Alert:
    lc = cfg["alert_rules"]["alert_lifecycle"]
    if status not in lc["statuses"] or status == "closed_with_documented_result":
        raise AlertError("недопустимый статус %r (закрытие — отдельным действием с обязательными полями)" % status)
    if alert.closed_at:
        raise AlertError("алерт уже закрыт", 409)
    if status == "handed_over_awaiting_confirmation" and not (data or {}).get("handed_to"):
        raise AlertError("при передаче укажите, кому передан пациент (handed_to)")
    if alert.accepted_at is None:
        accept(db, cfg, alert, actor)
    alert.status = status
    _ev(db, alert, "status", actor, status=status, **(data or {}))
    audit.log(db, actor, "alert.status", "alert", alert.id, alert.patient_id, status=status)
    return alert


def close(db: Session, cfg: Config, alert: M.Alert, actor: M.User, close_reason: str, data: Dict[str, Any]) -> M.Alert:
    lc = cfg["alert_rules"]["alert_lifecycle"]
    spec = cfg.bindings["alert_close_fields"]
    if alert.closed_at:
        raise AlertError("алерт уже закрыт", 409)
    if close_reason not in lc["close_reasons"]:
        raise AlertError("недопустимая причина закрытия %r; допустимо: %s" % (close_reason, ", ".join(lc["close_reasons"])))
    relaxed = close_reason in spec["relaxed_reasons"]
    missing: List[str] = []
    for f in spec["fields"]:
        if f.get("auto") or (relaxed and f["key"] != "comment"):
            continue
        v = data.get(f["key"])
        if f.get("subkeys"):
            if not isinstance(v, dict) or any(v.get(k) in (None, "") for k in f["subkeys"]):
                missing.append(f["label"])
        elif v in (None, "", []):
            missing.append(f["label"])
    if missing:
        raise AlertError("не заполнены обязательные поля закрытия: " + "; ".join(missing))
    method = str(data.get("contact_method", "")).lower()
    if alert.level == "red" and not relaxed and any(m in method for m in spec["unreachable_markers"]):
        raise AlertError("«не удалось связаться» не закрывает красный алерт: он остаётся нерешённым и идёт по цепочке эскалации", 409)
    if alert.level == "red" and close_reason == "technical_or_duplicate" and not data.get("comment"):
        raise AlertError("для технического закрытия красного алерта нужен комментарий")
    now = clock.now()
    close_data = dict(data, close_reason=close_reason, assessed_by={"user": actor.login, "at": now.isoformat()},
                      signal_basis={"rule": alert.rule_id, "title": alert.title, "basis": alert.basis, "facts": alert.facts})
    alert.closed_at, alert.close_data, alert.status, alert.open_key = now, close_data, "closed_with_documented_result", None
    if alert.accepted_at is None:
        alert.accepted_at, alert.accepted_by = now, actor.id
    _ev(db, alert, "closed", actor, close_reason=close_reason)
    audit.log(db, actor, "alert.close", "alert", alert.id, alert.patient_id, reason=close_reason)
    return alert


# ---- вид для пациента (без внутренних оценок риска и красного цвета) --------------------------

def patient_support_state(db: Session, cfg: Config, patient: M.Patient) -> Dict[str, Any]:
    """Что показать пациенту. Названия уровней и правил пациенту не передаются."""
    now = clock.now()
    open_alerts = db.execute(select(M.Alert).where(M.Alert.patient_id == patient.id, M.Alert.closed_at.is_(None))).scalars().all()
    order = {"red": 3, "orange": 2, "yellow": 1}
    top = max((a.level for a in open_alerts), key=lambda l: order.get(l, 0), default=None)
    t = cfg["patient_texts"]
    working = worktime.is_working(cfg, now)
    out: Dict[str, Any] = {"screen": "none", "after_hours_notice": None}
    if top == "red":
        sc = t["red_support_screen_short"]
        out.update(screen="support_short", title=sc["title"], lines=sc["lines"],
                   buttons=[{"id": "call_112", "label": "Позвонить 112", "tel": "112"},
                            {"id": "call_103", "label": "Позвонить 103", "tel": "103"},
                            {"id": "contact_doctor", "label": "Связаться с моим врачом"},
                            {"id": "helpline", "label": "Телефон психологической помощи"}],
                   details_available=True)
    elif top == "orange":
        out.update(screen="neutral_support", text=t["orange_neutral_screen"]["text"], buttons=[
            {"id": "call_112", "label": "Позвонить 112", "tel": "112"}, {"id": "call_103", "label": "Позвонить 103", "tel": "103"}])
    if top in ("red", "orange") and not working:
        out["after_hours_notice"] = t["after_hours_notice"]["text"].replace("[часы работы]", worktime.hours_text(cfg))
    return out
