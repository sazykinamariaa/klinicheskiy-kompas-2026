"""Загрузчик и валидатор конфигураций (config/*.json).

Ядро не содержит клинических значений: всё читается отсюда. Загрузчик
  * проверяет структуру файлов и ссылочную целостность (id шкал, источников, правил);
  * собирает сводку по статусам (confirmed / approved_by_physician / verify_grls / verify / waiting);
  * находит все места «ЖДЁМ» и честно выводит их в панель администратора;
  * проверяет, какие правила исполнимы (условие разобрано и все факты известны движку).
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import expr as X

CONFIG_FILES = [
    "scales", "intake_questionnaire", "daily_checkin", "clinical_profile_fields",
    "alert_rules", "routing_rules", "drug_aviandr", "monitoring", "patient_texts",
    "scenarios", "sources", "clinic_settings", "my_plan", "approval",
]
EXTRA_FILES = ["rule_bindings"]

WAIT_STATUSES = {"waiting", "verify", "verify_grls", "draft_by_dev_pending_review"}
APPROVED_STATUSES = {"approved_by_physician"}
CONFIRMED_STATUSES = {"confirmed", "confirmed_by_medics"}
PLACEHOLDER_RE = re.compile(r"ЖДЁМ|\[данные уточняются\]")


class ConfigError(Exception):
    pass


def default_config_dir() -> Path:
    env = os.environ.get("KK_CONFIG_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for cand in (here.parents[2] / "config", here.parents[1] / "config"):
        if cand.is_dir():
            return cand
    raise ConfigError("не найдена папка config/")


def classify_status(s: Any) -> str:
    """Свести разнообразные значения status к пяти группам."""
    if not isinstance(s, str):
        return "other"
    low = s.lower()
    if low.startswith("approved"):
        return "approved_by_physician"
    if low.startswith("waiting") or "pending" in low or "waiting" in low:
        return "waiting"
    if "verify" in low or "verified" in low:
        return "verify"
    if low.startswith("confirmed") or low in CONFIRMED_STATUSES:
        return "confirmed"
    return "other"


class Config:
    def __init__(self, data: Dict[str, Any], path: Path):
        self.data = data
        self.path = path
        self.scales: Dict[str, dict] = {s["id"]: s for s in data["scales"]["scales"]}
        self.intake_q: Dict[str, dict] = {q["id"]: q for q in data["intake_questionnaire"]["questions"]}
        self.drug: dict = data["drug_aviandr"]["drug"]
        self.alert_rules: List[dict] = data["alert_rules"]["rules"]
        self.routing_mandatory: List[dict] = data["routing_rules"]["mandatory"]
        self.routing_desirable: List[dict] = data["routing_rules"]["desirable"]
        self.sources: Dict[str, dict] = {s["id"]: s for s in data["sources"]["sources"]}
        self.bindings: dict = data.get("rule_bindings", {})
        self.profile_fields: Dict[str, dict] = {f["id"]: f for f in data["clinical_profile_fields"]["fields"]}
        self.exec_report: Dict[str, dict] = {}

    def __getitem__(self, name: str) -> Any:
        return self.data[name]

    # ---- правила: исполняемое выражение ------------------------------------
    def rule_expr(self, rule: dict) -> Optional[str]:
        ov = self.bindings.get("rule_overrides", {}).get(rule["id"])
        if ov:
            return ov["expr"]
        return rule.get("when")

    def timing_tier(self, rule: dict) -> Optional[str]:
        t = rule.get("timing_tier")
        return t.get("value") if isinstance(t, dict) else None

    # ---- сводки для панели администратора ----------------------------------
    def status_summary(self) -> Dict[str, Any]:
        per_file: Dict[str, Counter] = {}
        total: Counter = Counter()

        def walk(node: Any, fname: str) -> None:
            if isinstance(node, dict):
                st = node.get("status")
                if isinstance(st, str):
                    c = classify_status(st)
                    per_file.setdefault(fname, Counter())[c] += 1
                    total[c] += 1
                for v in node.values():
                    walk(v, fname)
            elif isinstance(node, list):
                for v in node:
                    walk(v, fname)

        for fname, d in self.data.items():
            walk(d, fname)
        return {
            "total": dict(total),
            "per_file": {k: dict(v) for k, v in sorted(per_file.items())},
        }

    def waiting_items(self) -> List[Dict[str, str]]:
        """Всё, что ждёт данных: значения «ЖДЁМ», статусы waiting / verify / verify_grls / draft."""
        items: List[Dict[str, str]] = []

        def label_of(node: dict) -> str:
            for k in ("title", "label", "text", "id", "trade_name", "note", "description"):
                v = node.get(k)
                if isinstance(v, str):
                    return v[:140]
            return ""

        def walk(node: Any, fname: str, path: str, parent: Optional[dict]) -> None:
            if isinstance(node, dict):
                st = node.get("status")
                if isinstance(st, str) and classify_status(st) in ("waiting", "verify") and not path.endswith("status_values"):
                    items.append({"file": fname, "path": path or "/", "status": st, "what": label_of(node)})
                for k, v in node.items():
                    if isinstance(v, str) and PLACEHOLDER_RE.search(v) and k != "status":
                        items.append({"file": fname, "path": "%s/%s" % (path, k), "status": "placeholder", "what": v[:160]})
                    else:
                        walk(v, fname, "%s/%s" % (path, k), node)
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    if isinstance(v, str) and PLACEHOLDER_RE.search(v):
                        items.append({"file": fname, "path": "%s[%d]" % (path, i), "status": "placeholder", "what": v[:160]})
                    else:
                        walk(v, fname, "%s[%d]" % (path, i), None)

        for fname, d in self.data.items():
            walk(d, fname, "", None)
        return items

    def unexecutable_rules(self) -> List[Dict[str, str]]:
        return [dict(id=k, **v) for k, v in self.exec_report.items() if not v["executable"]]


def _load_json(p: Path) -> Any:
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise ConfigError("нет файла конфигурации: %s" % p.name)
    except json.JSONDecodeError as e:
        raise ConfigError("%s: некорректный JSON (%s)" % (p.name, e))


def validate(cfg: Config, known_facts: Optional[set] = None) -> List[str]:
    """Возвращает список ошибок (пустой — конфигурация корректна). Предупреждения идут в exec_report."""
    errs: List[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errs.append(msg)

    d = cfg.data
    need("scales" in d["scales"], "scales.json: нет ключа scales")
    for sid, s in cfg.scales.items():
        if s.get("enabled") is False:
            continue
        if s.get("id") == "safety_screen":
            continue
        need("items" in s and s["items"], "scales.json: у шкалы %s нет пунктов" % sid)
        need("scoring" in s, "scales.json: у шкалы %s нет scoring" % sid)
        need("source_ids" in s, "scales.json: у шкалы %s нет source_ids" % sid)
        for src in s.get("source_ids", []):
            need(src in cfg.sources, "scales.json: %s ссылается на неизвестный источник %s" % (sid, src))
    seen = set()
    for r in cfg.alert_rules:
        need(r["id"] not in seen, "alert_rules.json: повтор id %s" % r["id"])
        seen.add(r["id"])
        need(r.get("level") in {"red", "orange", "yellow", "green"}, "alert_rules.json: %s без уровня" % r["id"])
        need("when" in r, "alert_rules.json: %s без when" % r["id"])
    for r in cfg.routing_mandatory + cfg.routing_desirable:
        need("when" in r, "routing_rules.json: %s без when" % r["id"])
    ids = {r["id"] for r in cfg.alert_rules}
    for r in cfg.routing_mandatory + cfg.routing_desirable:
        ids.add(r["id"])
    # исполнимость правил
    cfg.exec_report = {}
    for r in cfg.alert_rules + cfg.routing_mandatory + cfg.routing_desirable:
        src = cfg.rule_expr(r)
        rep = {"executable": True, "why": "", "expr": src or ""}
        if r.get("status") == "waiting":
            rep.update(executable=False, why="status=waiting: значение ждёт данных, правило не исполняется")
        elif not src:
            rep.update(executable=False, why="нет условия")
        else:
            try:
                node = X.parse(src)
                refs = X.collect_refs(node)
                if known_facts is not None:
                    unknown = sorted(n for n in refs if n not in known_facts)
                    if unknown:
                        rep.update(executable=False, why="неизвестные факты: " + ", ".join(unknown))
            except X.ExprError as e:
                rep.update(executable=False, why="условие написано прозой: %s" % e)
        cfg.exec_report[r["id"]] = rep
    for c in cfg.drug["contraindications"] + cfg.drug["cautions"]:
        need("check" in c, "drug_aviandr.json: %s без check" % c["id"])
        try:
            X.parse(c["check"])
        except X.ExprError as e:
            errs.append("drug_aviandr.json: %s: %s" % (c["id"], e))
    states = set(d["drug_aviandr"]["_meta"]["result_states"])
    need(states == {"indicated_pending_doctor", "contraindicated", "safety_check_incomplete", "out_of_indication", "interaction_requires_decision"},
         "drug_aviandr.json: набор result_states изменён — движок рассчитан на 5 состояний")
    for f in d["clinical_profile_fields"]["fields"]:
        need("id" in f and "type" in f, "clinical_profile_fields.json: поле без id/type")
    return errs


def load_config(path: Optional[Path] = None, known_facts: Optional[set] = None, strict: bool = True) -> Config:
    path = Path(path) if path else default_config_dir()
    data: Dict[str, Any] = {}
    for name in CONFIG_FILES + EXTRA_FILES:
        p = path / (name + ".json")
        if name in EXTRA_FILES and not p.exists():
            data[name] = {}
            continue
        data[name] = _load_json(p)
    cfg = Config(data, path)
    errs = validate(cfg, known_facts)
    if errs and strict:
        raise ConfigError("конфигурация не прошла проверку:\n  - " + "\n  - ".join(errs))
    cfg.errors = errs  # type: ignore[attr-defined]
    return cfg
