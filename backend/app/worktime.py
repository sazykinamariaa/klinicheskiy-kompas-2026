"""Рабочее время клиники (config/clinic_settings.json). Врач недоступен круглосуточно:
красные алерты уходят дежурному всегда, остальное учитывает рабочие часы."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from .config_loader import Config

_UTC = ZoneInfo("UTC")


def _tz(cfg: Config) -> ZoneInfo:
    return ZoneInfo(cfg["clinic_settings"]["timezone"])


def to_local(cfg: Config, utc_naive: datetime) -> datetime:
    return utc_naive.replace(tzinfo=_UTC).astimezone(_tz(cfg))


def _hours(cfg: Config, local: datetime):
    ws = cfg["clinic_settings"]["working_hours"]
    key = "mon_fri" if local.weekday() < 5 else "sat_sun"
    span = ws.get(key)
    if not span:
        return None
    h1, m1 = map(int, span[0].split(":"))
    h2, m2 = map(int, span[1].split(":"))
    return time(h1, m1), time(h2, m2)


def is_working(cfg: Config, utc_naive: datetime) -> bool:
    local = to_local(cfg, utc_naive)
    span = _hours(cfg, local)
    return bool(span and span[0] <= local.time() < span[1])


def next_working_start(cfg: Config, utc_naive: datetime) -> datetime:
    """Начало ближайшего рабочего интервала (UTC, наивное). Если сейчас рабочее время — возвращает текущее."""
    local = to_local(cfg, utc_naive)
    for add in range(0, 9):
        day = (local + timedelta(days=add)).replace(second=0, microsecond=0)
        span = _hours(cfg, day)
        if not span:
            continue
        start = day.replace(hour=span[0].hour, minute=span[0].minute)
        end = day.replace(hour=span[1].hour, minute=span[1].minute)
        if add == 0:
            if local < start:
                cand = start
            elif local < end:
                return utc_naive
            else:
                continue
        else:
            cand = start
        return cand.astimezone(_UTC).replace(tzinfo=None)
    return utc_naive


def hours_text(cfg: Config) -> str:
    ws = cfg["clinic_settings"]["working_hours"]
    mf = ws.get("mon_fri")
    return "пн–пт %s–%s" % (mf[0], mf[1]) if mf else "[данные уточняются]"
