"""Оценка импорта: точность и полнота извлечения на размеченных СИНТЕТИЧЕСКИХ текстах. Запуск: python scripts/eval_import.py"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app import importer as IMP  # noqa: E402
from app.config_loader import load_config  # noqa: E402

CASES = [
    {"text": "Пациентка 36 лет. Диагноз: F41.1 генерализованное тревожное расстройство. Принимает амлодипин 5 мг/сут. СКФ 96 мл/мин. PHQ-9: 6, GAD-7: 14.",
     "gold": {("dx_icd10", "F41.1"), ("med", "амлодипин"), ("egfr_ml_min", "96"), ("scale_total", "phq9:6"), ("scale_total", "gad7:14")}},
    {"text": "Мужчина 57 лет, F41.1. СКФ 48. Постоянно принимает амлодипин 10 мг. Аллергия на пенициллин. GAD-7 13.",
     "gold": {("dx_icd10", "F41.1"), ("egfr_ml_min", "48"), ("med", "амлодипин"), ("scale_total", "gad7:13"), ("allergy_mention", "пенициллин")}},
    {"text": "Жалобы на сниженное настроение. Сертралин 100 мг в сутки назначен ранее. Диагноз F32.1. PHQ-9 = 19.",
     "gold": {("med", "сертралин"), ("dx_icd10", "F32.1"), ("scale_total", "phq9:19")}},
    {"text": "Ранее получал моклобемид, отменен в прошлом году. Сейчас лекарств не принимает. F41.2.",
     "gold": {("dx_icd10", "F41.2")}},
    {"text": "В анамнезе гипертония (I10). Жалоб на тревогу нет. Диагноз по психиатрии не установлен.",
     "gold": set()},
    {"text": "Пациентка принимает флуоксетин 20 мг, а также омепразол 20 мг. F33.1. eGFR 71.",
     "gold": {("med", "флуоксетин"), ("dx_icd10", "F33.1"), ("egfr_ml_min", "71")}},
]


def keyset(items):
    out = set()
    for i in items:
        k, v = i["kind"], i["value"]
        if k == "scale_total":
            out.add((k, "%s:%s" % (v["scale"], v["total"])))
        elif k in ("med_mentioned_not_current",):
            continue
        else:
            out.add((k, str(v).lower() if k in ("med", "allergy_mention") else str(v)))
    return out


def main():
    cfg = load_config(strict=False)
    tp = fp = fn = 0
    rows = []
    for c in CASES:
        got = keyset(IMP.extract(cfg, c["text"])["items"])
        gold = {(k, v.lower() if k in ("med", "allergy_mention") else v) for k, v in c["gold"]}
        tp += len(got & gold)
        fp += len(got - gold)
        fn += len(gold - got)
        rows.append({"text": c["text"][:60], "missed": sorted(gold - got), "extra": sorted(got - gold)})
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    res = {"cases": len(CASES), "tp": tp, "fp": fp, "fn": fn, "precision": round(p, 3), "recall": round(r, 3),
           "note": "оценка на малом синтетическом наборе; на реальных историях метрики будут ниже, поэтому врач проверяет каждого кандидата", "details": rows}
    print(json.dumps(res, ensure_ascii=False, indent=2))
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "import_eval.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
