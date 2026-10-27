"""Уточняющие вопросы первичной анкеты («Если ответ «Да», уточните…», «укажите какие») — в едином виде.

Источник — intake_questionnaire.json (followups, followup + followup_when / followup_when_not, free_text_option).
Уточнения необязательны: на заполненность анкеты и на правила влияют только ответы, явно привязанные в rule_bindings.json.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException


TYPES = {"multi", "single", "single_or_text", "free_text_structured", "text"}


def clean(label: str) -> str:
    s = (label or "").strip()
    for t in (" (укажите какие)", " (уточните какие)", " (уточните)", " (укажите)"):
        s = s.replace(t, "")
    return s[:-1] if s.endswith(".") else s


def followups(q: Dict[str, Any]) -> List[Dict[str, Any]]:
    qid, out = q["id"], []
    fo = q.get("free_text_option")
    if fo and q.get("type") == "multi":
        lab = clean(next((o["label"] for o in q.get("options", []) if o["id"] == fo), "Другое"))
        out.append({"id": qid + "_other", "type": "text", "text": lab + ": уточните", "short": lab, "options": [], "fields": None,
                    "show_if": {"q": qid, "any": [fo]}})
    items = list(q.get("followups") or [])
    if q.get("followup"):
        f = dict(q["followup"])
        if q.get("followup_when"):
            f.setdefault("when", q["followup_when"])
        if q.get("followup_when_not"):
            f.setdefault("when_not", q["followup_when_not"])
        items.append(f)
    for f in items:
        if "text" not in f or f.get("type", "text") not in TYPES:
            continue  # например, q21a — ссылка на отдельный экран доверенного контакта, а не вопрос анкеты
        w = f.get("when")
        if isinstance(w, list) and w and ":" in str(w[0]):
            show = {"q": w[0].split(":", 1)[0], "any": [x.split(":", 1)[1] for x in w]}
        elif isinstance(w, list) and w:
            show = {"q": qid, "any": list(w)}
        elif f.get("when_not"):
            show = {"q": qid, "not": list(f["when_not"])}
        else:
            show = {"q": qid}
        out.append({"id": f["id"], "type": f.get("type", "text"), "text": f["text"], "short": f.get("short") or f["text"],
                    "options": [{"id": o["id"], "label": o["label"]} for o in f.get("options", [])], "fields": f.get("fields"), "show_if": show})
    return out


def all_followups(cfg) -> Dict[str, Dict[str, Any]]:
    return {f["id"]: f for q in cfg["intake_questionnaire"]["questions"] for f in followups(q)}


def _sel(v: Any) -> set:
    if isinstance(v, dict):
        v = v.get("choice")
    vals = v if isinstance(v, (list, tuple, set)) else [v]
    return {x for x in vals if isinstance(x, str) and x}


def visible(f: Dict[str, Any], answers: Dict[str, Any]) -> bool:
    s = f["show_if"]
    v = answers.get(s["q"])
    if v is None:
        return False
    if "any" not in s and "not" not in s:
        return True  # уточнение показывается после любого ответа на основной вопрос
    sel = _sel(v)
    if "any" in s:
        return bool(sel & set(s["any"]))
    if "not" in s:
        return bool(sel - set(s["not"]))
    return True


def text(f: Dict[str, Any], a: Any) -> Optional[str]:
    if a in (None, "", [], {}):
        return None
    lab = {o["id"]: clean(o["label"]) for o in f.get("options", [])}
    if f["type"] == "free_text_structured" and isinstance(a, dict):
        return "; ".join("%s: %s" % (k, str(v).strip()) for k, v in a.items() if str(v or "").strip()) or None
    if isinstance(a, dict):
        parts = [lab.get(a.get("choice"), a.get("choice")) if a.get("choice") else None, (a.get("text") or "").strip() or None]
        return ", ".join(p for p in parts if p) or None
    if isinstance(a, list):
        return ", ".join(lab.get(x, str(x)) for x in a) or None
    return lab.get(a, str(a).strip() or None)


def details(cfg, intake: Dict[str, Any], qid: str) -> List[Dict[str, str]]:
    """Ответы на уточнения к основному вопросу — для врача и психиатра."""
    q = cfg.intake_q.get(qid)
    if not q:
        return []
    out = []
    for f in followups(q):
        if visible(f, intake):
            t = text(f, intake.get(f["id"]))
            if t:
                out.append({"q": f["short"], "a": t})
    return out


def validate(f: Dict[str, Any], v: Any) -> Any:
    """Проверка ответа на уточнение. None — ответ очищен."""
    if v in (None, "", [], {}):
        return None
    t, ids = f["type"], {o["id"] for o in f.get("options", [])}
    if t == "multi":
        if not isinstance(v, list) or any(x not in ids for x in v):
            raise HTTPException(422, "выберите варианты из списка")
        return sorted(set(v))
    if t == "single":
        if v not in ids:
            raise HTTPException(422, "выберите вариант из списка")
        return v
    if t == "single_or_text":
        if isinstance(v, str) and v in ids:
            return v
        if isinstance(v, dict) and (v.get("choice") is None or v.get("choice") in ids) and isinstance(v.get("text") or "", str):
            txt = (v.get("text") or "").strip()[:500]
            return {"choice": v.get("choice"), "text": txt} if (v.get("choice") or txt) else None
        raise HTTPException(422, "выберите вариант или напишите своими словами")
    if t == "free_text_structured":
        fields = f.get("fields") or []
        if not isinstance(v, dict) or any(k not in fields or not isinstance(x, str) for k, x in v.items()):
            raise HTTPException(422, "неверный формат уточнения")
        v = {k: x.strip()[:1000] for k, x in v.items() if x.strip()}
        return v or None
    if not isinstance(v, str):
        raise HTTPException(422, "ожидается текст")
    return v.strip()[:1000] or None
