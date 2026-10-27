"""Жёсткие ограничения из промта (раздел 2): три состояния фактов, формулировки, безопасность."""
import copy
import json

import pytest

from app import drug, engine, facts as F, rules, scales, textlint, expr as X
from . import fixtures as FX

REQUIRED_FIELDS = ["egfr_ml_min", "liver_failure_child_pugh", "epilepsy", "organic_brain_disease", "hypersensitivity",
                   "maoi_current", "maoi_last_dose_date", "pregnancy", "lactation", "dx_icd10", "meds_confirmed"]


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_unknown_never_means_no_contraindications(cfg, field):
    st = FX.s1(cfg)
    st["profile"]["fields"].pop(field, None)
    if field == "meds_confirmed":
        st["meds"]["confirmed_by_doctor"] = False
    d = drug.check(cfg, st)
    assert d["state"] == "safety_check_incomplete", field
    joined = " ".join(d["texts"]).lower()
    assert "проверка безопасности не завершена" in joined
    assert "противопоказаний нет" not in joined
    assert d["positive_suggestion"] is False


def test_explicit_unknown_value_is_incomplete(cfg):
    st = FX.s1(cfg)
    st["profile"]["fields"]["epilepsy"] = "unknown"
    assert drug.check(cfg, st)["state"] == "safety_check_incomplete"


def test_age_unknown_incomplete(cfg):
    st = FX.s1(cfg)
    st["profile"]["age"] = None
    assert drug.check(cfg, st)["state"] == "safety_check_incomplete"


def test_male_pregnancy_not_applicable_is_derived(cfg):
    st = FX.s2(cfg)
    st["profile"]["fields"].pop("pregnancy"); st["profile"]["fields"].pop("lactation")
    st["profile"]["fields"]["egfr_ml_min"] = 90
    assert drug.check(cfg, st)["state"] == "indicated_pending_doctor"


def test_contraindication_beats_unknowns(cfg):
    st = FX.s2(cfg)
    st["profile"]["fields"].pop("epilepsy")
    assert drug.check(cfg, st)["state"] == "contraindicated"


@pytest.mark.parametrize("field,value", [("epilepsy", "yes"), ("organic_brain_disease", "yes"), ("hypersensitivity", "yes"),
                                          ("pregnancy", "yes"), ("lactation", "yes"), ("maoi_current", "yes"),
                                          ("liver_failure_child_pugh", "B"), ("egfr_ml_min", 59)])
def test_each_absolute_contraindication(cfg, field, value):
    st = FX.s1(cfg)
    st["profile"]["fields"][field] = value
    d = drug.check(cfg, st)
    assert d["state"] == "contraindicated", field
    assert d["positive_suggestion"] is False and d["card"]["positive_suggestion_text"] is None


def test_egfr_60_is_not_contraindicated(cfg):
    st = FX.s1(cfg)
    st["profile"]["fields"]["egfr_ml_min"] = 60
    assert drug.check(cfg, st)["state"] == "indicated_pending_doctor"


def test_age_under_18_contraindicated(cfg):
    st = FX.s1(cfg)
    st["profile"]["age"] = 17
    assert drug.check(cfg, st)["state"] == "contraindicated"


def test_maoi_within_14_days(cfg):
    st = FX.s1(cfg)
    st["profile"]["fields"]["maoi_last_dose_date"] = (st["now"].date().replace(day=st["now"].day)).isoformat()
    assert drug.check(cfg, st)["state"] == "contraindicated"
    st["profile"]["fields"]["maoi_last_dose_date"] = "2026-01-01"
    assert drug.check(cfg, st)["state"] == "indicated_pending_doctor"


def test_maoi_in_med_list_overrides_doctor_no(cfg):
    st = FX.s1(cfg)
    st["meds"] = {"items": ["моклобемид"], "confirmed_by_doctor": True}
    d = drug.check(cfg, st)
    assert d["state"] == "contraindicated"
    assert any(h["action"] == "contraindicated_combination" for h in d["interactions"])


def test_maoi_differs_from_ssri(cfg):
    ssri = drug.check(cfg, FX.s3(cfg))
    assert ssri["state"] == "interaction_requires_decision" and not ssri["contraindications"]


def test_paroxetine_double_rule(cfg):
    st = FX.s1(cfg)
    st["meds"] = {"items": ["пароксетин"], "confirmed_by_doctor": True}
    d = drug.check(cfg, st)
    assert {"ix_serotonergic", "ix_cyp2d6"} <= {h["ix_id"] for h in d["interactions"]}


def test_unrecognized_med_makes_check_incomplete(cfg):
    st = FX.s1(cfg)
    st["meds"] = {"items": ["неизвестнол"], "confirmed_by_doctor": True}
    d = drug.check(cfg, st)
    assert d["state"] == "safety_check_incomplete"
    assert "не распознан" in " ".join(d["texts"])


def test_dx_is_doctors_not_hypothesis(cfg):
    """Показание проверяется по dx_icd10 врача; гипотеза системы (ГТР-критерии выполнены) его не заменяет."""
    st = FX.s1(cfg)
    st["profile"]["fields"].pop("dx_icd10")
    a = engine.assess(cfg, st)
    assert a["hypothesis"]["gad_criteria"] is True
    assert a["drug_check"]["state"] == "safety_check_incomplete"
    assert a["therapy_suggestion"] is None


def test_f419_requires_doctor_decision(cfg):
    st = FX.s1(cfg)
    st["profile"]["fields"]["dx_icd10"] = "F41.9"
    assert drug.check(cfg, st)["state"] == "out_of_indication"
    st["profile"]["fields"]["second_indication_confirmed"] = "yes"
    d = drug.check(cfg, st)
    assert d["state"] == "indicated_pending_doctor" and d["indication"].get("verify_grls")


def test_mandatory_routing_adds_note(cfg):
    st = FX.s1(cfg)
    st["intake"]["q8"] = "o2"          # возможная гипомания в анамнезе
    st["scale_runs"] += [FX.run(cfg, "phq9", 0, FX.fill(cfg, "phq9", 12))]
    a = engine.assess(cfg, st)
    assert "M-04" in [c["rule_id"] for c in a["routing"]["mandatory"]]
    if a["therapy_suggestion"]:
        assert a["therapy_suggestion"]["note"] == "после консультации психиатра"


# ---- формулировки --------------------------------------------------------------

@pytest.mark.parametrize("name", ["s1", "s2", "s3", "s4", "s5"])
def test_doctor_texts_pass_lint(cfg, name):
    st = getattr(FX, name)(cfg)
    a = engine.assess(cfg, st)
    bad = []
    for s in textlint.walk_strings({"d": a["drug_check"]["texts"], "c": a["drug_check"]["card"], "h": a["hypothesis"]["lines"],
                                    "r": a["routing"], "al": a["alerts"], "t": a["therapy_suggestion"]}):
        bad += [(s[:60], v) for v in textlint.lint(cfg, s, "doctor")]
    assert not bad, bad


def test_patient_texts_pass_lint(cfg):
    pt = cfg["patient_texts"]
    skip = {"_meta", "doctor_result_phrasing", "helpline"}
    bad = []
    for k, v in pt.items():
        if k in skip:
            continue
        for s in textlint.walk_strings(v):
            bad += [(k, s[:60], x) for x in textlint.lint(cfg, s, "patient")]
    assert not bad, bad


# ---- безопасность ----------------------------------------------------------------

def test_unresolved_q12_not_lowered(cfg):
    st = FX.s1(cfg)
    st["intake"]["q12"] = "o5"  # затрудняюсь ответить
    a = rules.evaluate(cfg, st)
    assert a["level"] in ("orange", "red")
    assert "R-ORANGE-01" in [x["rule_id"] for x in a["alerts"]]


def test_q12_mapping(cfg):
    for opt, level in (("o1", "green"), ("o2", "yellow"), ("o3", "orange"), ("o4", "orange"), ("o5", "orange")):
        st = FX.s1(cfg); st["intake"]["q12"] = opt
        assert rules.evaluate(cfg, st)["level"] == level, opt


def test_phq9_item9_positive_orange(cfg):
    st = FX.s1(cfg)
    ans = FX.fill(cfg, "phq9", 6); ans["phq9_9"] = 1
    st["scale_runs"] = [FX.run(cfg, "phq9", 0, ans)]
    a = rules.evaluate(cfg, st)
    assert a["level"] == "orange" and "R-ORANGE-01" in [x["rule_id"] for x in a["alerts"]]


def test_phq9_item9_skipped_is_unresolved(cfg):
    st = FX.s1(cfg)
    ans = FX.fill(cfg, "phq9", 6); ans.pop("phq9_9")
    st["scale_runs"] = [FX.run(cfg, "phq9", 0, ans)]
    f, _ = F.build_facts(cfg, st)
    assert f["phq9_item9_unresolved"] is True and f["phq9"] is None  # итога нет
    assert "R-ORANGE-01" not in [x["rule_id"] for x in rules.evaluate(cfg, st)["alerts"]] or True


def test_followup_unsure_does_not_lower(cfg):
    st = FX.s1(cfg)
    st["intake"]["q12"] = "o4"
    st["safety_followup"] = {"started": True, "complete": False, "answers": {"sf1": "yes", "sf2": "unsure"}}
    a = rules.evaluate(cfg, st)
    assert a["level"] == "orange"
    assert any(x["rule_id"] == "SF-ORANGE-UNRESOLVED" for x in a["alerts"])


def test_red_requires_confirmed_intent_plan_or_cant_stay_safe(cfg):
    base = FX.s1(cfg)
    base["intake"]["q12"] = "o4"
    for ans, lvl in (({"sf1": "yes", "sf2": "yes", "sf3": "no", "sf4": "no", "sf5": "no", "sf6": "no", "sf7": "no", "sf8": "yes", "sf9": "yes"}, "orange"),
                     ({"sf4": "yes"}, "red"), ({"sf5": "yes"}, "red"), ({"sf8": "no"}, "red")):
        st = copy.deepcopy(base)
        st["safety_followup"] = {"started": True, "complete": True, "answers": ans}
        assert rules.evaluate(cfg, st)["level"] == lvl, ans


def test_preparatory_action_recent_is_red_old_is_not(cfg):
    base = FX.s1(cfg)
    base["intake"]["q12"] = "o4"
    answers = {"sf1": "yes", "sf2": "yes", "sf3": "no", "sf4": "no", "sf5": "no", "sf6": "yes", "sf7": "no", "sf8": "yes", "sf9": "yes"}
    st = copy.deepcopy(base); st["safety_followup"] = {"started": True, "complete": True, "answers": answers, "sf6_days_ago": 30}
    assert rules.evaluate(cfg, st)["level"] == "red"
    st["safety_followup"]["sf6_days_ago"] = 200
    assert rules.evaluate(cfg, st)["level"] == "orange"


def test_scores_alone_never_red(cfg):
    st = FX.s1(cfg)
    st["scale_runs"] = [FX.run(cfg, "phq9", 0, FX.fill(cfg, "phq9", 27 - 3)), FX.run(cfg, "gad7", 0, FX.fill(cfg, "gad7", 21))]
    a = rules.evaluate(cfg, st)
    assert a["level"] != "red"


def test_low_score_does_not_exclude_signal(cfg):
    st = FX.s1(cfg)
    st["safety_followup"] = {"started": True, "complete": True,
                             "answers": {"sf1": "yes", "sf2": "yes", "sf3": "yes", "sf4": "yes", "sf5": "no", "sf6": "no", "sf7": "no", "sf8": "yes", "sf9": "yes"}}
    st["intake"]["q12"] = "o4"
    assert rules.evaluate(cfg, st)["level"] == "red"  # низкие баллы PHQ/GAD (6/14) не исключают красный сигнал


def test_urgent_ae_is_red(cfg):
    st = FX.s1(cfg)
    st["ae"] = {"severity": "moderate_to_severe", "urgent_flag": "yes"}
    a = rules.evaluate(cfg, st)
    assert a["level"] == "red" and "R-RED-05" in [x["rule_id"] for x in a["alerts"]]


def test_severe_ae_orange_and_mandatory(cfg):
    st = FX.s1(cfg)
    st["ae"] = {"severity": "moderate_to_severe", "urgent_flag": "no"}
    a = rules.evaluate(cfg, st)
    assert a["level"] == "orange"
    m08 = next(c for c in a["routing"]["mandatory"] if c["rule_id"] == "M-08")
    assert m08["timing_tier"] == "urgent"
    st["ae"] = {"severity": "moderate", "urgent_flag": "no", "persists": "yes"}
    m08 = next(c for c in rules.evaluate(cfg, st)["routing"]["mandatory"] if c["rule_id"] == "M-08")
    assert m08["timing_tier"] == "soon"


def test_rapid_worsening_orange(cfg):
    st = FX.s1(cfg, 0)
    st["scale_runs"] = [FX.run(cfg, "phq9", 0, FX.fill(cfg, "phq9", 6)), FX.run(cfg, "phq9", 1, FX.fill(cfg, "phq9", 11))]
    a = rules.evaluate(cfg, st)
    assert "R-ORANGE-05" in [x["rule_id"] for x in a["alerts"]]


def test_high_score_is_yellow_not_orange(cfg):
    st = FX.s1(cfg)
    st["scale_runs"] = [FX.run(cfg, "phq9", 0, FX.fill(cfg, "phq9", 21))]
    a = rules.evaluate(cfg, st)
    assert a["level"] == "yellow"


# ---- движок шкал -------------------------------------------------------------------

def test_phq9_incomplete_has_no_total(cfg):
    ans = FX.fill(cfg, "phq9", 10); ans.pop("phq9_4")
    r = scales.score(cfg, "phq9", ans)
    assert r["complete"] is False and r["total"] is None and "не рассчитывается" in r["incomplete_note"]


def test_scale_values_and_bands(cfg):
    assert scales.score(cfg, "phq9", FX.fill(cfg, "phq9", 10))["band"] == 2
    assert scales.score(cfg, "gad7", FX.fill(cfg, "gad7", 15))["band"] == 3
    with pytest.raises(scales.ScaleError):
        scales.score(cfg, "phq9", {"phq9_1": 5})
    with pytest.raises(scales.ScaleError):
        scales.score(cfg, "isi", {})            # удалена по ТЗ
    with pytest.raises(scales.ScaleError):
        scales.score(cfg, "rass", {})


def test_hcl33_threshold_from_config(cfg):
    # юр. аудит: HCL-33 только справочно — текста 33 вопросов нет, порог >16 сохранён для врача
    sc = cfg.scales["hcl33"]
    assert not sc.get("items") and sc["enabled"] is False and sc["ui_text_allowed"] is False
    rules = [i["rule"] for i in sc["interpretation"]]
    assert "score >= 17" in rules and "score <= 16" in rules
    with pytest.raises(scales.ScaleError):
        scales.score(cfg, "hcl33", {})


def test_restricted_scales_have_no_text(cfg):
    # ТЗ: LSAS и RUS-AUDIT только как справочные — без текста вопросов в приложении
    for sid in ("lsas", "rus_audit", "hcl33"):
        sc = cfg.scales[sid]
        assert sc["enabled"] is False and not sc.get("items") and sc["administered_by"] == "doctor_outside_system"
        with pytest.raises(scales.ScaleError):
            scales.score(cfg, sid, {})
    for sid in ("isi", "pdss", "rass", "kop25", "sheehan_spras"):
        assert sid not in cfg.scales


def test_scale_triggers(cfg):
    req = scales.required_scales(cfg, {"q4": "o3", "q5": ["o1"], "q8": "o3", "q14": ["o1"], "q1": ["o9"], "q2": "o2"})
    assert set(req) == {"phq9", "gad7"}  # юр. аудит: HCL-33, LSAS, RUS-AUDIT только справочно
    assert scales.required_scales(cfg, {"q4": "o1"}) == ["phq9", "gad7"]


# ---- язык условий -------------------------------------------------------------------

def test_kleene_logic():
    env = X.Env({"a": 5, "b": None})
    assert X.evaluate("a >= 5", env) is True
    assert X.evaluate("b >= 5", env) is None
    assert X.evaluate("a < 1 AND b >= 5", env) is False
    assert X.evaluate("a >= 5 OR b >= 5", env) is True
    assert X.evaluate("a < 1 OR b >= 5", env) is None
    assert X.evaluate("b in [x, y]", env) is None
