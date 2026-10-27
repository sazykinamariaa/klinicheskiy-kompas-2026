"""Дежурный: центр оповещений, контекст сигнала, маршрутизация и эскалация, протоколы, передача смены."""
from tests.test_api import api, env, Api, pid, alert_id  # noqa: F401


def cat(api, cid, login="duty"):
    return next(c for c in api.get(login, "/api/duty/center").json()["categories"] if c["id"] == cid)


def test_center_categories(api):
    ids = [c["id"] for c in api.get("duty", "/api/duty/center").json()["categories"]]
    assert ids == ["critical", "urgent_requests", "deterioration", "adverse_events", "unconfirmed", "no_action"]
    crit = cat(api, "critical")["items"]
    assert crit and all(a["level"] == "red" for a in crit)
    a = crit[0]
    assert {"patient", "created_at", "basis", "responsible", "status_label", "sla"} <= set(a)
    assert a["sla"]["minutes"] == 5  # красный: подтвердить за 5 минут (утверждено медиками)
    assert any(x["rule_id"] == "R-ORANGE-02" for x in cat(api, "adverse_events")["items"])
    assert api.get("patient_s1", "/api/duty/center").status_code == 403


def test_context_timeline_and_protocol(api):
    a = cat(api, "critical")["items"][0]
    c = api.get("duty", f"/api/duty/alerts/{a['id']}/context").json()
    assert [s["step"] for s in c["timeline"]] == ["created", "notified", "accepted", "actions", "handed"]
    assert c["timeline"][0]["done"] and not c["timeline"][2]["done"]
    assert c["priority"]["ack_minutes"] == 5 and c["protocol"]
    assert {"112", "103"} <= {n["tel"] for n in c["protocol"]["emergency"]["numbers"]}
    assert api.post("duty", f"/api/alerts/{a['id']}/accept", {}).status_code == 200
    c2 = api.get("duty", f"/api/duty/alerts/{a['id']}/context").json()
    assert c2["timeline"][2]["done"]
    assert a["id"] in {x["id"] for x in cat(api, "no_action")["items"]}  # принят, но действий ещё нет


def test_assign_handover_escalate(api):
    a = cat(api, "critical")["items"][0]
    staff = api.get("duty", "/api/duty/staff").json()
    psy = next(s for s in staff if s["role"] == "psychiatrist")
    r = api.post("duty", f"/api/duty/alerts/{a['id']}/assign", {"user_id": psy["id"]})
    assert r.status_code == 200 and r.json()["responsible"]["how"] == "назначен"
    assert api.post("duty", f"/api/duty/alerts/{a['id']}/handover-confirm", {"by": "Психиатр"}).status_code == 409
    assert api.post("duty", f"/api/alerts/{a['id']}/status", {"status": "handed_over_awaiting_confirmation", "handed_to": "психиатр"}).status_code == 200
    assert api.post("duty", f"/api/duty/alerts/{a['id']}/handover-confirm", {"by": "Психиатр (демо)"}).status_code == 200
    assert api.post("duty", f"/api/duty/alerts/{a['id']}/escalate", {"to": "nobody"}).status_code == 422
    assert api.post("duty", f"/api/duty/alerts/{a['id']}/escalate", {"to": "clinic_admin_on_duty", "note": "нет ответа"}).status_code == 200
    red = next(L for L in api.get("duty", "/api/duty/routing").json()["levels"] if L["id"] == "red")
    item = next(x for x in red["items"] if x["id"] == a["id"])
    assert item["handover"]["confirmed_by"] == "Психиатр (демо)"
    assert any(e["manual"] for e in item["escalations"])
    assert [c["after_minutes"] for c in item["chain"]] == [5, 10]


def test_protocols(api):
    pr = api.get("duty", "/api/duty/protocols").json()["protocols"]
    assert {p["id"] for p in pr} == {"immediate_threat", "suicidal_thoughts", "sharp_deterioration", "severe_ae", "lost_contact"}
    for p in pr:
        assert p["algorithm"] and p["actions"] and p["responsible"] and p["escalation"]


def test_shift_handover(api):
    staff = api.get("duty", "/api/duty/staff").json()
    assert not [s for s in staff if s["name"] in ("Администратор смены", "Ответственный сотрудник")]
    nxt = next(s for s in staff if s["name"] == "Врач-терапевт 1")
    d = api.get("duty", "/api/duty/handover/draft").json()
    assert d["open_cases"] and {"open_cases", "waiting", "done"} <= set(d)
    assert api.post("duty", "/api/duty/handover", {"next_steps": "ок", "next_responsible_id": nxt["id"]}).status_code == 422  # слишком коротко
    r = api.post("duty", "/api/duty/handover", {"next_steps": "Проверить ответ психиатра", "next_responsible_id": nxt["id"]})
    assert r.status_code == 200
    h = r.json()
    assert h["data"]["open_cases"] and h["confirmed_at"] is None
    assert api.post("duty", f"/api/duty/handover/{h['id']}/confirm", {}).status_code == 422  # сам себе не подтверждает
    assert api.post("doctor1", f"/api/duty/handover/{h['id']}/confirm", {}).status_code == 200
    assert api.post("doctor1", f"/api/duty/handover/{h['id']}/confirm", {}).status_code == 409
    rows = api.get("duty", "/api/duty/handovers").json()
    assert rows[0]["id"] == h["id"] and rows[0]["confirmed_by"]
