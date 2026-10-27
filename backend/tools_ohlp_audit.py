import copy, datetime, sys
from datetime import timedelta
from app.config_loader import load_config
from app import engine
from app import seed_data as FX

cfg = load_config(strict=False)
BASE = FX.s1(cfg, 0)
ok = 0; total = 0

def check(name, cond, detail=""):
    global ok, total
    total += 1
    if cond: ok += 1
    print(("OK   " if cond else "FAIL ") + name + (" | " + detail if detail else ""))

def case(fields=None, meds=None, age=None, intake=None):
    st = copy.deepcopy(BASE)
    if fields: st["profile"]["fields"].update(fields)
    if meds is not None: st["meds"]["items"] = list(meds)
    if age is not None: st["profile"]["age"] = age
    if intake: st["intake"].update(intake)
    return st, engine.assess(cfg, st)["drug_check"]

def ci_ids(d): return [c["id"] for c in d["contraindications"]]
def ci_sec(d, cid): return next((c.get("ohlp_section") for c in d["contraindications"] if c["id"] == cid), None)
def ix(d, iid): return next((h for h in d["interactions"] if h["ix_id"] == iid), None)

def caut_ids(d): return [c["id"] for c in d["cautions"]]
def dago(n): return (BASE["now"] - timedelta(days=n)).date().isoformat()

# (название, поля, id противопоказания, должно ли быть)
CASES = [
    ("СКФ 59 -> ci_renal (4.3)", {"egfr_ml_min": 59}, "ci_renal", True),
    ("СКФ 60 -> ci_renal нет", {"egfr_ml_min": 60}, "ci_renal", False),
    ("эпилепсия -> ci_epilepsy", {"epilepsy": "yes"}, "ci_epilepsy", True),
    ("Чайлд-Пью A -> ci_hepatic", {"liver_failure_child_pugh": "A"}, "ci_hepatic", True),
    ("Чайлд-Пью B -> ci_hepatic", {"liver_failure_child_pugh": "B"}, "ci_hepatic", True),
    ("Чайлд-Пью C -> ci_hepatic", {"liver_failure_child_pugh": "C"}, "ci_hepatic", True),
    ("ИМАО сейчас -> ci_maoi_concurrent", {"maoi_current": "yes"}, "ci_maoi_concurrent", True),
    ("ИМАО отменён 10 дн. назад -> ci_maoi_after", {"maoi_last_dose_date": dago(10)}, "ci_maoi_after", True),
    ("ИМАО отменён 20 дн. назад -> ci_maoi_after нет", {"maoi_last_dose_date": dago(20)}, "ci_maoi_after", False),
]

print("Проверка правил Авиандра по ОХЛП", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))

print("\n== ОХЛП 4.3 — противопоказания (красный, блокировка)")
for name, f, cid, must in CASES:
    st, d = case(fields=f)
    if must:
        check(name, cid in ci_ids(d) and d["state"] == "contraindicated" and ci_sec(d, cid) == "4.3", "состояние " + d["state"])
    else:
        check(name, cid not in ci_ids(d), "состояние " + d["state"])

print("\n== ОХЛП 4.5 — взаимодействия")
meds_list = ["моклобемид"]
for meds in meds_list:
    st, d = case(meds=[meds])
    h = ix(d, "ix_maoi")
    check(f"meds={meds} -> h[ix_maoi] is red", h and h["level"] == "red")

serotonergics = ["сертралин", "трамадол", "литий", "зверобой"]
for meds in serotonergics:
    st, d = case(meds=[meds])
    h = ix(d, "ix_serotonergic")
    check(f"meds={meds} -> h[ix_serotonergic] is yellow", h and h["level"] == "yellow" and h["title"] == "Риск серотонинового синдрома" and d["state"] == "interaction_requires_decision")

sedatives = ["диазепам", "алпразолам", "кветиапин", "галоперидол"]
for meds in sedatives:
    st, d = case(meds=[meds])
    h = ix(d, "ix_sedatives")
    check(f"meds={meds} -> h[ix_sedatives] is yellow", h and h["level"] == "yellow")

cyp2d6 = ["тербинафин", "дифенгидрамин", "хинидин"]
for meds in cyp2d6:
    st, d = case(meds=[meds])
    h = ix(d, "ix_cyp2d6")
    check(f"meds={meds} -> h[ix_cyp2d6] is yellow", h and h["level"] == "yellow")

intake_list = [{"q14": "o2"}]
for intake in intake_list:
    st, d = case(intake=intake)
    check("intake q14 o2 -> ix_alcohol", "ix_alcohol" in caut_ids(d))

print("\n== ОХЛП 4.2/4.4 — 65 лет и старше")
st, d = case(age=70)
check("age=70 -> ci_age not in ci_ids and caut_age65 in caut_ids", "ci_age" not in ci_ids(d) and "caut_age65" in caut_ids(d))

print("\n== Сценарий S2")
st = FX.s2(cfg, 0)
res = engine.assess(cfg, st)
d = res["drug_check"]
print("СКФ:", st["profile"]["fields"]["egfr_ml_min"], "Состояние:", d["state"], "Противопоказания:", ci_ids(d), "Уровни алертов:", [a.get("level") for a in res["alerts"]])
check("S2: назначение заблокировано", d["state"] == "contraindicated")
check("S2: ci_renal, раздел 4.3", ci_sec(d, "ci_renal") == "4.3")
check("S2: нет экстренного красного алерта", not any(a.get("level") == "red" for a in res["alerts"]))
check("S2: красный блок в карточке, положительное предложение не формируется", d["gating"]["show_positive"] is False and d["card"]["positive_suggestion_text"] is None, d["texts"][0])

print(f"\nИТОГ: {ok} из {total}")
sys.exit(0 if ok == total else 1)
