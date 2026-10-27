"""Психиатр: «Мои пациенты», карточка, динамика, «что изменилось», рекомендации с решением, план, сообщения."""
from tests.test_api import api, env, Api, pid, alert_id  # noqa: F401


def refer(api, code, key):
    """Направление создаёт только лечащий врач — подтверждением предложения системы."""
    c = api.get("doctor1", f"/api/doctor/patients/{pid(api, code)}/card").json()
    pr = next(x for x in c["proposals"] if x["kind"] == "routing" and x["key"] == key)
    assert api.post("doctor1", f"/api/doctor/proposals/{pr['id']}/decision", {"decision": "confirm"}).status_code == 200


def bucket(api, bid):
    return next(b for b in api.get("psychiatrist", "/api/psychiatrist/overview").json()["buckets"] if b["id"] == bid)


def test_only_referred_patients(api):
    assert api.get("doctor1", "/api/psychiatrist/overview").status_code == 403
    before = {x["code"] for x in api.get("psychiatrist", "/api/psychiatrist/patients").json()}
    assert "S4" not in before
    refer(api, "S4", "M-08")
    assert "S4" in {x["code"] for x in api.get("psychiatrist", "/api/psychiatrist/patients").json()}
    assert "S4" in {x["code"] for x in bucket(api, "new")["patients"]}
    assert [b["id"] for b in api.get("psychiatrist", "/api/psychiatrist/overview").json()["buckets"]] == \
        ["new", "worsening", "adverse_events", "confirmed", "risks", "reassessment", "overdue"]
    assert {"S6", "S7", "S8"} <= {x["code"] for x in bucket(api, "confirmed")["patients"]}
    assert api.get("psychiatrist", f"/api/psychiatrist/patients/{pid(api, 'S1')}/card").status_code == 404


def test_card_dynamics_what_changed(api):
    refer(api, "S4", "M-08")
    s4 = pid(api, "S4")
    c = api.get("psychiatrist", f"/api/psychiatrist/patients/{s4}/card").json()
    assert {"anamnesis", "functioning", "treatment", "risks", "exams"} <= set(c)
    assert c["treatment"]["order"] and c["treatment"]["ae"]
    d = api.get("psychiatrist", f"/api/psychiatrist/patients/{s4}/dynamics").json()
    assert "phq9" in d["series"] and d["checkins"] and d["therapy"]
    assert any(e["kind"] == "therapy" for e in d["events"]) and any(e["kind"] == "ae" for e in d["events"])
    w = api.get("psychiatrist", f"/api/psychiatrist/patients/{s4}/what-changed").json()
    assert w["lines"] and w["period"]["to"]


def test_recommendation_decision_needs_comment(api):
    refer(api, "S4", "M-08")
    r = next(x for x in api.get("psychiatrist", "/api/psychiatrist/recommendations").json() if x["code"] == "S4")
    it = r["items"][0]
    url = f"/api/psychiatrist/recommendations/{r['patient_id']}/decision"
    assert api.post("psychiatrist", url, {"item_key": it["key"], "decision": "reject"}).status_code == 422
    assert api.post("psychiatrist", url, {"item_key": it["key"], "decision": "maybe", "comment": "ok ok"}).status_code == 422
    assert api.post("psychiatrist", url, {"item_key": it["key"], "decision": "modify", "comment": "снизить дозу, контроль через неделю"}).status_code == 200
    r2 = next(x for x in api.get("psychiatrist", "/api/psychiatrist/recommendations").json() if x["code"] == "S4")
    dec = next(x for x in r2["items"] if x["key"] == it["key"])["decision"]
    assert dec["decision"] == "modify" and "дозу" in dec["comment"]
    plan = api.get("psychiatrist", f"/api/psychiatrist/patients/{r['patient_id']}/plan").json()
    assert any("Рекомендация системы" in h["text"] for h in plan["history"])
    assert plan["therapy"] and "next_assessment" in plan


def test_messages_and_read_mark(api):
    refer(api, "S4", "M-08")
    s4 = pid(api, "S4")
    assert api.post("doctor1", f"/api/doctor/patients/{s4}/messages", {"body": "Как вы себя чувствуете на фоне сонливости?"}).status_code == 200
    assert api.post("patient_s4", "/api/patient/messages", {"body": "Сонливость днём мешает работать, можно ли что-то изменить?"}).status_code == 200
    m = next(x for x in api.get("psychiatrist", "/api/psychiatrist/messages").json() if x["code"] == "S4")
    assert m["unread"] >= 1
    first = next(i for i in m["items"] if i["id"] and not i["read"])
    assert api.post("psychiatrist", f"/api/psychiatrist/messages/{first['id']}/read", {}).status_code == 200
    m2 = next(x for x in api.get("psychiatrist", "/api/psychiatrist/messages").json() if x["code"] == "S4")
    assert m2["unread"] == m["unread"] - 1
