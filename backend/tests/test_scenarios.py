"""Пять сценариев демо (config/scenarios.json): эталонные результаты из поля expected."""
import pytest

from app import engine
from . import fixtures as FX


def ids(cards):
    return [c["rule_id"] for c in cards]


def test_s1_aviandr_fits(cfg):
    for week in (0, 2, 4, 6):
        a = engine.assess(cfg, FX.s1(cfg, week))
        assert a["drug_check"]["state"] == "indicated_pending_doctor", week
        assert a["level"] == "green"
        assert not a["routing"]["mandatory"]
    a = engine.assess(cfg, FX.s1(cfg, 0))
    texts = " ".join(a["drug_check"]["texts"])
    assert "Показание подтверждено врачом" in texts
    assert "противопоказания не обнаружены; проверка завершена врачом" in texts
    assert "рассмотреть маритупирдин как один из вариантов" in texts
    # предложение, а не назначение
    assert a["therapy_suggestion"]["state"] == "ожидает подтверждения врача"
    assert a["hypothesis"]["gad_criteria"] is True


def test_s1_week4_no_yellow_no_alert(cfg):
    a = engine.assess(cfg, FX.s1(cfg, 4))
    assert "R-YELLOW-05" not in ids(a["alerts"])
    assert a["alerts"] == []


def test_s2_contraindication(cfg):
    a = engine.assess(cfg, FX.s2(cfg, 0))
    d = a["drug_check"]
    assert d["state"] == "contraindicated"
    assert any("Маритупирдин противопоказан при СКФ < 60 мл/мин" in c["text"] for c in d["contraindications"])
    assert a["therapy_suggestion"] is None and d["positive_suggestion"] is False
    assert d["emergency_signal_triggered"] is False
    assert a["alerts"] == [], "противопоказание не запускает экстренный сигнал"
    assert "D-DRUG-CI" in ids(a["routing"]["desirable"])


def test_s3_interaction(cfg):
    a = engine.assess(cfg, FX.s3(cfg, 0))
    d = a["drug_check"]
    assert d["state"] == "interaction_requires_decision"
    assert a["therapy_suggestion"] is None
    txt = " ".join(d["texts"])
    assert "Сертралин" in txt and "серотонин" in txt.lower()
    ix = {h["ix_id"] for h in d["interactions"]}
    assert "ix_serotonergic" in ix and "ix_cyp2d6" in ix  # СИОЗС: оба предупреждения
    assert not d["contraindications"], "не абсолютное противопоказание, равное ИМАО"
    assert a["level"] != "red", "красный только при соответствующих симптомах, а не по факту сертралина"
    assert "D-DRUG-IX" in ids(a["routing"]["desirable"])


def test_s4_out_of_indication_mandatory_psychiatrist(cfg):
    a = engine.assess(cfg, FX.s4(cfg, 0))
    assert a["drug_check"]["state"] == "out_of_indication"
    assert a["therapy_suggestion"] is None
    assert "M-02" in ids(a["routing"]["mandatory"])
    assert a["level"] == "green"
    m02 = next(c for c in a["routing"]["mandatory"] if c["rule_id"] == "M-02")
    assert m02["timing_tier"] == "soon"
    assert any("вне инструкции" in t.lower() for t in a["drug_check"]["texts"])


def test_s5_red_alert(cfg):
    a = engine.assess(cfg, FX.s5(cfg, 3))
    assert a["level"] == "red"
    assert "R-RED-01" in ids(a["alerts"])
    assert "M-01" in ids(a["routing"]["mandatory"])
    # при красном алерте положительное предложение скрыто
    assert a["therapy_suggestion"] is None
    assert a["drug_check"]["gating"]["show_positive"] is False
    first = a["alerts"][0]
    assert first["level"] == "red" and first["basis"]["source"]
