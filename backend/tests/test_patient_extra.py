"""Пациент: опросники, цель, «маленькие шаги», приём лекарства; раскладка демо по трём сценариям."""
from tests.test_api import api, env, Api, pid, alert_id  # noqa: F401
from app import db as DB, models as M
from sqlalchemy import select

def test_methods_reference_without_questions(api):
    r = api.get("patient_s3", "/api/patient/methods").json()
    assert [x["id"] for x in r["regular"]] == ["phq9", "gad7"]
    for x in r["reference"]:
        assert set(x) == {"id", "title", "text", "by", "suggested", "suggested_text", "why"}
        assert "items" not in x and "answers" not in x
    assert r["regular"][0]["count"] >= 2
    assert r["regular"][0]["vs_first"] == "better"


def test_methods_compare_needs_two_fills(api):
    r = api.get("patient_s1", "/api/patient/methods").json()
    assert [x["id"] for x in r["regular"]] == ["phq9", "gad7"]
    for x in r["regular"]:
        assert x["vs_first"] == "none" and x["vs_prev"] == "none"


def test_medication_only_with_confirmed_order(api):
    r = api.get("patient_s1", "/api/patient/medication").json()
    assert r["active"] is False
    assert api.post("patient_s1", "/api/patient/medication/dose", {"slot": "morning"}).status_code == 409
    r = api.get("patient_s3", "/api/patient/medication").json()
    assert r["active"] is True
    assert [s["id"] for s in r["slots"]] == ["morning", "evening"]
    assert "ОХЛП" in r["source"]

def test_dose_mark_is_idempotent(api):
    api.post("patient_s3", "/api/patient/medication/dose", {"slot": "evening"})
    api.post("patient_s3", "/api/patient/medication/dose", {"slot": "evening"})
    with DB.session_scope() as session:
        count = session.execute(select(M.AdherenceEvent).where(
            M.AdherenceEvent.patient_id == pid(api, "S3"),
            M.AdherenceEvent.kind == "confirmed_taken",
            M.AdherenceEvent.reason == "evening"
        )).scalars().all()
        assert len(count) == 1
    assert api.post("patient_s3", "/api/patient/medication/dose", {"slot": "noon"}).status_code == 422

def test_goal_set_by_patient(api):
    r = api.put("patient_s1", "/api/patient/goal", {"text": "Высыпаться и гулять по вечерам"})
    assert r.status_code == 200
    g = api.get("patient_s1", "/api/patient/goal").json()
    assert g["text"] == "Высыпаться и гулять по вечерам"
    assert g["by"] == "patient"
    assert api.put("patient_s1", "/api/patient/goal", {"text": "a"}).status_code == 422

def test_achievements_no_streaks_and_can_hide(api):
    a = api.get("patient_s3", "/api/patient/achievements").json()
    assert a["visible"] is True
    assert all("streak" not in item for item in a["items"])
    assert all("lost" not in item for item in a["items"])
    assert all(0 <= item.get("done", 0) <= item.get("need", 0) for item in a["items"])
    api.put("patient_s3", "/api/patient/achievements", {"enabled": False})
    assert api.put("patient_s3", "/api/patient/achievements", {"enabled": True}).json()["visible"] is True

def test_achievements_hidden_on_hard_day(api):
    assert api.get("patient_s5", "/api/patient/achievements").json()["visible"] is False

def test_visit_counted_once_per_day(api):
    api.get("patient_s2", "/api/patient/home")
    api.get("patient_s2", "/api/patient/home")
    with DB.session_scope() as session:
        count = session.execute(select(M.AuditLog).where(
            M.AuditLog.action == "patient.visit",
            M.AuditLog.patient_id == pid(api, "S2")
        )).scalars().all()
        assert len(count) == 1

def test_on_therapy_not_proposed_again(api):
    for code in ["S3", "S4"]:
        card = api.get("doctor1", f"/api/doctor/patients/{pid(api, code)}/card").json()
        assert len(card["orders"]) == 1
        assert not any(p["kind"] == "therapy" for p in card["proposals"])

def test_demo_layout_three_scenarios(api):
    card = api.get("doctor1", f"/api/doctor/patients/{pid(api, 'S1')}/card").json()
    assert card["orders"] == []
    assert any(p["kind"] == "therapy" for p in card["proposals"])
    card = api.get("doctor1", f"/api/doctor/patients/{pid(api, 'S2')}/card").json()
    assert card["assessment"]["drug_check"]["state"] == "contraindicated"
    card = api.get("doctor1", f"/api/doctor/patients/{pid(api, 'S4')}/card").json()
    assert any(a["rule_id"] == "R-YELLOW-05" for a in card["alerts"])
    assert any(a["rule_id"] == "R-ORANGE-02" for a in card["alerts"])
    card = api.get("doctor1", f"/api/doctor/patients/{pid(api, 'S5')}/card").json()
    assert card["level"] == "red"