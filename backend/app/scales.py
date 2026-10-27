"""Движок подсчёта шкал по конфигурации (scales.json).

Правила (из scales.json → _meta.missing_item_policy_default):
  * в PHQ-9 и GAD-7 нельзя пропустить пункт; незавершённый опросник сохраняется БЕЗ итогового балла;
  * пропуск пункта о суицидальных мыслях = «не разрешено»: уровень не снижается;
  * высокий балл — не опасность, низкий её не исключает: функция лишь считает и подписывает.
Тексты пунктов, пороги и подписи берутся из конфигурации.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import expr as X
from .config_loader import Config


class ScaleError(ValueError):
    pass


def _allowed(scale: dict, item: dict, part: Optional[str] = None) -> Optional[set]:
    if "answers" in item:
        return {a["value"] for a in item["answers"]}
    if part and "answers_kr" in scale:
        return {a["value"] for a in scale["answers_kr"][part]}
    if "answers" in scale:
        return {a["value"] for a in scale["answers"]}
    return None


def is_dual(scale: dict) -> bool:
    return scale.get("scoring", {}).get("type") == "sum_two_subscales"


def validate_answer(scale: dict, item: dict, value: Any) -> Any:
    """Проверяет значение ответа на пункт. Возвращает нормализованное значение или бросает ScaleError."""
    if is_dual(scale):
        if not isinstance(value, dict) or set(value) != {"fear", "avoidance"}:
            raise ScaleError("пункт %s: нужен ответ {fear, avoidance}" % item["id"])
        for part in ("fear", "avoidance"):
            ok = _allowed(scale, item, part)
            if value[part] not in ok:
                raise ScaleError("пункт %s: недопустимое значение %r (%s)" % (item["id"], value[part], part))
        return {"fear": int(value["fear"]), "avoidance": int(value["avoidance"])}
    ok = _allowed(scale, item)
    if ok is not None and value not in ok:
        raise ScaleError("пункт %s: недопустимое значение %r" % (item["id"], value))
    return value


def item_value(scale: dict, ans: Any) -> int:
    if is_dual(scale):
        return int(ans["fear"]) + int(ans["avoidance"])
    return int(ans)


def score(cfg: Config, scale_id: str, answers: Dict[str, Any]) -> Dict[str, Any]:
    scale = cfg.scales.get(scale_id)
    if scale is None:
        raise ScaleError("неизвестная шкала %s" % scale_id)
    if scale.get("enabled") is False:
        raise ScaleError("шкала %s выключена в конфигурации: %s" % (scale_id, scale.get("enabled_reason", "")))
    items = scale.get("items")
    if not items:
        raise ScaleError("у шкалы %s нет пунктов" % scale_id)
    ids = [i["id"] for i in items]
    for k in answers:
        if k not in ids:
            raise ScaleError("неизвестный пункт %s" % k)
    clean: Dict[str, Any] = {}
    for it in items:
        if it["id"] in answers and answers[it["id"]] is not None:
            clean[it["id"]] = validate_answer(scale, it, answers[it["id"]])
    missing = [i for i in ids if i not in clean]
    complete = not missing
    total = sum(item_value(scale, clean[i]) for i in ids) if complete else None

    band = None
    label = None
    if total is not None:
        for entry in scale.get("interpretation", []):
            if "from" in entry and entry["from"] <= total <= entry["to"]:
                band, label = entry, entry.get("doctor_label")
                break
            if "rule" in entry:
                env = X.Env({"score": total})
                if X.evaluate(entry["rule"], env):
                    band, label = entry, entry.get("doctor_label")
                    break

    flags: List[str] = []
    safety_item = scale.get("safety_item")
    safety_unresolved = False
    if safety_item:
        sid = safety_item["item_id"]
        if sid not in clean:
            safety_unresolved = True
            flags.append("safety_item_unresolved")
        elif item_value(scale, clean[sid]) >= 1:
            flags.append("safety_item_positive")

    return {
        "scale_id": scale_id,
        "title": scale.get("title"),
        "complete": complete,
        "total": total,
        "answered": len(clean),
        "of": len(ids),
        "missing": missing,
        "band": band.get("severity_band") if band else None,
        "label": label,
        "zone": band.get("zone") if band else None,
        "flags": flags,
        "safety_item_unresolved": safety_unresolved,
        "answers": clean,
        "source_ids": scale.get("source_ids", []),
        "version_ru": scale.get("version_ru"),
        "license_status": scale.get("license_status"),
        "status": scale.get("status"),
        "incomplete_note": None if complete else "Опросник не завершён: итоговый балл не рассчитывается.",
    }


def required_scales(cfg: Config, intake: Dict[str, Any]) -> List[str]:
    """Какие шкалы предложить по ответам анкеты. Триггеры — в rule_bindings.json → scale_triggers."""
    out = list(cfg["intake_questionnaire"]["scale_trigger_summary"].get("always", []))

    def sel(qid: str) -> set:
        v = intake.get(qid)
        if v is None:
            return set()
        return set(v) if isinstance(v, (list, tuple, set)) else {v}

    for scale_id, trg in cfg.bindings.get("scale_triggers", {}).items():
        if scale_id.startswith("_") or scale_id == "status":
            continue
        hit = bool(sel(trg["question"]) & set(trg["options"]))
        also = trg.get("also")
        if hit and also:
            chosen = sel(also["question"])
            hit = bool(chosen) and not (chosen & set(also.get("not_options", [])))
        if hit:
            out.append(scale_id)
    seen, res = set(), []
    for s in out:
        sc = cfg.scales.get(s)
        if s in seen or not sc or sc.get("enabled") is False:
            continue
        seen.add(s)
        res.append(s)
    return res
