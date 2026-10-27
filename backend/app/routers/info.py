"""Реестр источников (честно показывает статусы: подтверждено / проверить / ждём), справка о конфигурации и слой интеграции (адаптер МИС)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import audit, core, models as M
from ..config_loader import Config, classify_status
from ..deps import current_user, get_cfg, get_db, patient_for_doctor, require_roles
from ..summary import build_summary, to_fhir_like

router = APIRouter(prefix="/api", tags=["Источники и интеграция"])


@router.get("/sources", summary="Реестр источников: к каждому предложению системы привязан источник; статус показывается как есть")
def sources(user: M.User = Depends(current_user), cfg: Config = Depends(get_cfg)):
    out = []
    for s in cfg["sources"]["sources"]:
        used_by = [sid for sid, sc in cfg.scales.items() if s["id"] in sc.get("source_ids", [])]
        out.append(dict(s, bucket=classify_status(s.get("status")), scales=used_by))
    return {"sources": out, "kr_findings": cfg["sources"].get("kr_findings"),
            "note": "Статусы «verify» и «waiting» не скрываются: в карточке пациента такие основания помечаются."}


@router.get("/scales/registry", summary="Шкалы: версия, источник, статус лицензии на цифровое использование")
def scale_registry(user: M.User = Depends(current_user), cfg: Config = Depends(get_cfg)):
    return [{"id": s["id"], "title": s["title"], "enabled": s.get("enabled", True), "administered_by": s.get("administered_by"),
             "version_ru": s.get("version_ru"), "license_status": s.get("license_status"), "source_ids": s.get("source_ids", []),
             "status": s.get("status"), "enabled_reason": s.get("enabled_reason")} for s in cfg["scales"]["scales"]]


@router.get("/drug/reference", summary="Справочная карточка препарата с источником и редакцией (для врача)")
def drug_reference(user: M.User = Depends(require_roles("doctor", "psychiatrist")), cfg: Config = Depends(get_cfg)):
    d = cfg.drug
    return {"id": d["id"], "inn": d.get("inn"), "trade_name": d.get("trade_name"), "edition": d.get("edition"), "source_ids": d.get("source_ids"),
            "indications": d.get("indications"), "contraindications": d.get("contraindications"), "interactions": d.get("interactions"),
            "dosing_reference": d.get("dosing_reference"), "status": d.get("status")}


# ---- слой интеграции с МИС --------------------------------------------------------------------

class MISAdapter:
    """Обмен с МИС через папку обмена: каждая сводка — JSON-файл (FHIR-подобный Bundle) в data/mis_outbox.
    МИС организации забирает файлы из этой папки; адаптер HL7 FHIR REST реализует тот же метод push."""

    name = "mis-file-exchange"

    @property
    def folder(self):
        import os
        from pathlib import Path
        d = Path(os.environ.get("KK_DATA_DIR", Path(__file__).resolve().parents[3] / "data")) / "mis_outbox"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def sent_count(self) -> int:
        return len(list(self.folder.glob("*.json")))

    def push(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        import json
        from datetime import datetime
        code = str(((bundle.get("entry") or [{}])[0].get("resource") or {}).get("identifier", [{}])[0].get("value", "patient"))
        name = "%s_%s.json" % ("".join(ch for ch in code if ch.isalnum()) or "patient", datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        (self.folder / name).write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"accepted": True, "external_id": name}


MIS = MISAdapter()


@router.get("/integration/status", summary="Статус интеграции")
def integration_status(user: M.User = Depends(require_roles("doctor", "admin"))):
    return {"adapter": MIS.name, "mode": "файловый обмен: папка data/mis_outbox", "sent_count": MIS.sent_count(),
            "format": "FHIR-подобный Bundle (не заявляет соответствия профилям FHIR)"}


@router.post("/integration/mis/push/{patient_id}", summary="Отправить сводку пациента в МИС (папка обмена)")
def push(patient: M.Patient = Depends(patient_for_doctor), user: M.User = Depends(require_roles("doctor")),
         db: Session = Depends(get_db, scope="function"), cfg: Config = Depends(get_cfg)):
    a = core.assess_patient(db, cfg, patient, persist=False)
    bundle = to_fhir_like(build_summary(db, cfg, patient, a), a)
    res = MIS.push(bundle)
    audit.log(db, user, "integration.mis_push", "patient", patient.id, patient.id, external_id=res["external_id"])
    return res
