"""Проверка формулировок (жёсткое ограничение 9): врачу нельзя «диагноз», «у пациента депрессия»,
«подтверждено», «противопоказаний нет» при неполных данных; пациенту нельзя «вы здоровы», «вылечены»,
названия степеней, красные цвета. Шаблоны — в config (rule_bindings.json → text_lint,
drug_aviandr.json → phrasing.forbidden)."""
from __future__ import annotations

import re
from typing import Any, Iterable, List

from .config_loader import Config


def _drug_forbidden(cfg: Config) -> List[str]:
    out = []
    for s in cfg.drug["phrasing"]["forbidden"]:
        m = re.findall(r"«([^»]+)»", s)
        out += [x.strip().lower() for x in m]
    return out


def lint(cfg: Config, text: str, audience: str = "doctor") -> List[str]:
    """Вернуть список нарушений (пусто — текст допустим)."""
    spec = cfg.bindings.get("text_lint", {})
    bad: List[str] = []
    key = "doctor_forbidden_regex" if audience == "doctor" else "patient_forbidden_regex"
    for pat in spec.get(key, []):
        m = re.search(pat, text, flags=re.I)
        if m:
            bad.append("%s: «%s»" % (pat, m.group(0)))
    low = text.lower()
    if audience == "doctor":
        for ph in _drug_forbidden(cfg):
            # фразы вида «Противопоказаний нет», «Увеличьте дозу»
            core = ph.rstrip("»").strip()
            if core and core in low and core not in ("назначить авиандр",):
                bad.append("запрещённая формулировка препарата: «%s»" % core)
    return bad


def walk_strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("_") or k in ("source", "basis", "when", "facts_used", "config", "status", "id", "rule_id"):
                continue
            yield from walk_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from walk_strings(v)
