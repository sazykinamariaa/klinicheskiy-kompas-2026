"""Импорт из текста истории болезни: извлечение кандидатов правилами (без LLM, детерминированно) и ПРОВЕРКА ВРАЧОМ.

Ничего не попадает в карточку само: импорт создаёт ImportJob «ждёт проверки»; врач отмечает, что принять.
Принятые препараты добавляются как «импорт, не подтверждено врачом» и сбрасывают «список проверен врачом».
Баллы шкал из старых документов показываются врачу как справка и в расчёт правил НЕ входят (первичные ответы неизвестны).
Метрики качества: scripts/eval_import.py (точность и полнота на размеченных тестовых текстах).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from .config_loader import Config
from . import drug as D

ICD = re.compile(r"\b([FfGgIiEeNnKk]\d{2}(?:\.\d{1,2})?)\b")
EGFR = re.compile(r"(?:СКФ|eGFR)[^\d]{0,12}(\d{2,3})", re.I)
DOSE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(мг|мкг|г)\b(?:\s*(?:/|в)?\s*(?:сут\w*|день|д\.?))?", re.I)
SCALE_PATTERNS = {"phq9": re.compile(r"PHQ-?9[^\d]{0,20}(\d{1,2})", re.I), "gad7": re.compile(r"GAD-?7[^\d]{0,20}(\d{1,2})", re.I)}
ALLERGY = re.compile(r"аллерги\w*\s+(?:на\s+)?([А-Яа-яЁё\-]{4,}(?:\s[А-Яа-яЁё\-]{4,})?)", re.I)
NEG_NEAR = re.compile(r"(не\s+принима\w*|отмен\w*|прекращ\w*|без)\s*$", re.I)


def extract(cfg: Config, text: str) -> Dict[str, Any]:
    md = D._load_meddict(cfg)
    items: List[Dict[str, Any]] = []
    low = text.lower()

    def add(kind: str, value: Any, span: tuple, **extra: Any) -> None:
        items.append(dict({"kind": kind, "value": value, "span": list(span), "excerpt": text[max(0, span[0] - 25):span[1] + 25].replace("\n", " ")}, **extra))

    seen_dx = set()
    for m in ICD.finditer(text):
        code = m.group(1).upper()
        if code[0] == "F" and code not in seen_dx:
            seen_dx.add(code)
            add("dx_icd10", code, m.span(), note="диагноз из документа; врач решает, внести ли его как свой")
    for m in EGFR.finditer(text):
        v = int(m.group(1))
        if 5 <= v <= 200:
            add("egfr_ml_min", v, m.span())
    for d in md["drugs"]:
        inn = d["inn"].lower()
        for m in re.finditer(r"(?<![а-яё])%s[а-яё]*" % re.escape(inn), low):
            before = text[max(0, m.start() - 24):m.start()]
            if NEG_NEAR.search(before):
                add("med_mentioned_not_current", d["inn"], m.span(), note="упоминание отмены или «не принимает»: в список не предлагается")
                continue
            after = text[m.end():m.end() + 40]
            dm = DOSE.search(after)
            add("med", d["inn"], m.span(), dose=dm.group(0).strip() if dm else None)
    for sid, rx in SCALE_PATTERNS.items():
        for m in rx.finditer(text):
            v = int(m.group(1))
            if v <= (27 if sid == "phq9" else 21):
                add("scale_total", {"scale": sid, "total": v}, m.span(), note="справка: в расчёт правил не входит")
    for m in ALLERGY.finditer(text):
        add("allergy_mention", m.group(1).strip(), m.span(), note="поле «гиперчувствительность» заполняет врач")
    items.sort(key=lambda i: i["span"][0])
    return {"items": items, "status": "ожидает проверки врачом", "method": "правила и справочник (детерминированно)"}
