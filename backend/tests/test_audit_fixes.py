from tests.test_api import api, env, Api, pid, alert_id  # noqa: F401
import pytest

def test_confirmed_routing_is_not_proposed_again(api):
    p = pid(api, "S5")
    card = api.get("doctor1", f"/api/doctor/patients/{p}/card").json()
    m01 = [x for x in card["proposals"] if x["kind"] == "routing" and x["key"] == "M-01"]
    assert m01
    r = api.post("doctor1", f"/api/doctor/proposals/{m01[0]['id']}/decision", {"decision": "confirm"})
    assert r.status_code == 200, r.text
    card2 = api.get("doctor1", f"/api/doctor/patients/{p}/card").json()
    assert not [x for x in card2["proposals"] if x["kind"] == "routing" and x["key"] == "M-01"]
    assert any(r["rule_id"] == "M-01" for r in card2["referrals"])

def test_sla_due_for_new_red_alert(api):
    rows = api.get("duty", "/api/alerts").json()
    red = [a for a in rows if a["level"] == "red" and a["accepted_at"] is None]
    assert red
    assert all("sla_due_at" in a for a in rows)
    a = red[0]
    d = api.get("duty", f"/api/alerts/{a['id']}").json()
    assert d["sla_due_at"] is not None
    assert api.post("duty", f"/api/alerts/{a['id']}/accept").status_code == 200
    d2 = api.get("duty", f"/api/alerts/{a['id']}").json()
    assert d2["sla_due_at"] is None

def test_psychiatrist_notes(api):
    p = pid(api, "S5")
    card = api.get("doctor1", f"/api/doctor/patients/{p}/card").json()
    m01 = [x for x in card["proposals"] if x["kind"] == "routing" and x["key"] == "M-01"][0]
    api.post("doctor1", f"/api/doctor/proposals/{m01['id']}/decision", {"decision": "confirm"})
    refs = api.get("psychiatrist", "/api/psychiatrist/referrals").json()
    rid = [r for r in refs if r["rule_id"] == "M-01"][0]["id"]
    b = api.get("psychiatrist", f"/api/psychiatrist/referrals/{rid}/basis").json()
    assert b["confirmed_by"] and b["title"]
    assert api.post("psychiatrist", f"/api/psychiatrist/referrals/{rid}/notes", {"decision": "bad", "comment": "тест"}).status_code == 422
    r = api.post("psychiatrist", f"/api/psychiatrist/referrals/{rid}/notes", {"decision": "consult_scheduled", "comment": "Консультация завтра"})
    assert r.status_code == 200, r.text
    notes = api.get("psychiatrist", f"/api/psychiatrist/referrals/{rid}/notes").json()
    assert len(notes) == 1 and notes[0]["decision_label"]
    assert api.get("doctor1", f"/api/psychiatrist/referrals/{rid}/notes").status_code == 403
    dn = api.get("doctor1", f"/api/doctor/patients/{p}/psy-notes").json()
    assert dn and dn[0]["rule_id"] == "M-01"