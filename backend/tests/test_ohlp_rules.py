from datetime import timedelta
from app import engine
from app import seed_data as FX

def test_egfr_below_60_contraindicated_with_ohlp_section(cfg):
    st = FX.s1(cfg, 0)
    st["profile"]["fields"]["egfr_ml_min"] = 59
    d = engine.assess(cfg, st)["drug_check"]
    assert d["state"] == "contraindicated"
    ci = [c for c in d["contraindications"] if c["id"] == "ci_renal"]
    assert ci and ci[0]["ohlp_section"] == "4.3"

def test_egfr_60_not_contraindicated(cfg):
    st = FX.s1(cfg, 0)
    st["profile"]["fields"]["egfr_ml_min"] = 60
    d = engine.assess(cfg, st)["drug_check"]
    assert not any(c["id"] == "ci_renal" for c in d["contraindications"])

def test_maoi_stopped_less_than_2_weeks(cfg):
    st = FX.s1(cfg, 0)
    st["profile"]["fields"]["maoi_last_dose_date"] = (st["now"] - timedelta(days=10)).date().isoformat()
    d = engine.assess(cfg, st)["drug_check"]
    assert d["state"] == "contraindicated"
    assert any(c["id"] == "ci_maoi_after" for c in d["contraindications"])

def test_maoi_stopped_more_than_2_weeks(cfg):
    st = FX.s1(cfg, 0)
    st["profile"]["fields"]["maoi_last_dose_date"] = (st["now"] - timedelta(days=20)).date().isoformat()
    d = engine.assess(cfg, st)["drug_check"]
    assert not any(c["id"] == "ci_maoi_after" for c in d["contraindications"])

def test_maoi_in_med_list_red(cfg):
    st = FX.s1(cfg, 0)
    st["meds"]["items"] = ["моклобемид"]
    d = engine.assess(cfg, st)["drug_check"]
    assert d["state"] == "contraindicated"
    ix = [h for h in d["interactions"] if h["ix_id"] == "ix_maoi"]
    assert ix and ix[0]["level"] == "red" and ix[0]["ohlp_section"] == "4.5"

def test_serotonergic_yellow_requires_decision(cfg):
    for med in ("сертралин", "трамадол"):
        st = FX.s1(cfg, 0)
        st["meds"]["items"] = [med]
        d = engine.assess(cfg, st)["drug_check"]
        assert d["state"] == "interaction_requires_decision", med
        ix = [h for h in d["interactions"] if h["ix_id"] == "ix_serotonergic"]
        assert ix and ix[0]["level"] == "yellow" and ix[0]["title"] == "Риск серотонинового синдрома"

def test_cyp2d6_inhibitor_from_ohlp(cfg):
    st = FX.s1(cfg, 0)
    st["meds"]["items"] = ["тербинафин"]
    d = engine.assess(cfg, st)["drug_check"]
    assert any(h["ix_id"] == "ix_cyp2d6" and h["level"] == "yellow" for h in d["interactions"])