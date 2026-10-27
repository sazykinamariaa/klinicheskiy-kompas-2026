from app import rules, drug
from . import fixtures as FX


def test_load(cfg):
    assert cfg.errors == [], cfg.errors


def test_s1(cfg):
    st = FX.s1(cfg)
    r = rules.evaluate(cfg, st)
    print(r["level"], [a["rule_id"] for a in r["alerts"]], [m["rule_id"] for m in r["routing"]["mandatory"]], [m["rule_id"] for m in r["routing"]["desirable"]])
    d = drug.check(cfg, st)
    print(d["state"], d["texts"], d["missing"])
    assert d["state"] == "indicated_pending_doctor"


def test_all(cfg):
    for name in ("s1", "s2", "s3", "s4", "s5"):
        st = getattr(FX, name)(cfg, *( [3] if name == "s5" else []))
        r = rules.evaluate(cfg, st)
        d = drug.check(cfg, st, red_alert_active=r["level"] == "red", mandatory_routing=r["routing"]["mandatory"])
        print(name, "level=", r["level"], [a["rule_id"] for a in r["alerts"]], "M=", [m["rule_id"] for m in r["routing"]["mandatory"]], "D=", [m["rule_id"] for m in r["routing"]["desirable"]], "drug=", d["state"], "positive=", d["positive_suggestion"])
