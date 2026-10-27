"""Разделы врача: «Мои пациенты», краткая карточка, подсказки, направления со статусами, лекарственная безопасность."""
from tests.test_api import api, env, Api, pid, alert_id  # noqa: F401


def bucket(api, bid, login="doctor1"):
    o = api.get(login, "/api/doctor/overview").json()
    return next(b for b in o["buckets"] if b["id"] == bid)


def codes(b):
    return {x["code"] for x in b["patients"]}


def test_overview_buckets(api):
    assert codes(bucket(api, "on_treatment")) == {"S3", "S4", "S5"}
    assert "S1" in codes(bucket(api, "new_intake"))
    assert {"S4", "S5"} <= codes(bucket(api, "worsening"))
    assert len(bucket(api, "visits")["patients"]) >= 4
    assert not {"S1", "S2", "S3", "S4", "S5"} & {x["code"] for b in api.get("doctor2", "/api/doctor/overview").json()["buckets"] for x in b["patients"]}


def test_brief_and_review(api):
    b = api.get("doctor1", f"/api/doctor/patients/{pid(api, 'S2')}/brief").json()
    assert any(c["ohlp_section"] == "4.3" for c in b["risks"]["contraindications"])
    assert b["intake"][0]["q"] == "Изменения самочувствия"
    r = api.post("doctor1", f"/api/doctor/patients/{pid(api, 'S1')}/intake-reviewed", {})
    assert r.status_code == 200
    assert "S1" not in codes(bucket(api, "new_intake"))
    assert api.get("doctor2", f"/api/doctor/patients/{pid(api, 'S1')}/brief").status_code == 404


def test_hints_structure(api):
    h = api.get("doctor1", "/api/doctor/hints").json()
    by = {x["code"]: x for x in h}
    for x in h:
        for it in x["items"]:
            assert {"kind", "found", "why", "clarify", "risks", "next_step", "source"} <= set(it)
    assert any(it["kind"] == "drug" and it["source"]["id"] == "SRC-AVIANDR-GRLS" for it in by["S2"]["items"])
    assert all(it["basis"] and "медики" not in it["basis"] and "правило" not in it["basis"] for x in h for it in x["items"])
    assert any(it["kind"] == "routing" and it["tier"] == "mandatory" for it in by["S5"]["items"])
    for code in ("S3", "S4"):  # уже на лечении — «можно рассмотреть» не показываем
        assert not any(it["kind"] == "drug" and it["found"].startswith("Авиандр можно рассмотреть") for it in by.get(code, {"items": []})["items"])


def test_manual_referral_statuses(api):
    base = next(b for b in api.get("doctor1", "/api/doctor/referrals").json()["bases"] if b["kind"] == "desirable")
    p3 = pid(api, "S3")
    r = api.post("doctor1", f"/api/doctor/patients/{p3}/referrals", {"rule_id": base["id"], "comment": "Оценка переносимости"})
    assert r.status_code == 200, r.text
    ref = r.json()
    assert ref["status_label"] == "Создано" and ref["transmitted"]
    assert api.post("doctor1", f"/api/doctor/patients/{p3}/referrals", {"rule_id": base["id"]}).status_code == 409
    assert api.post("doctor2", f"/api/doctor/patients/{p3}/referrals", {"rule_id": base["id"]}).status_code == 404
    rid = ref["id"]

    def status():
        return next(x for x in api.get("doctor1", "/api/doctor/referrals").json()["referrals"] if x["id"] == rid)

    assert api.get("psychiatrist", f"/api/psychiatrist/referrals/{rid}").status_code == 200
    assert status()["status_label"] == "Получено"
    assert api.post("psychiatrist", f"/api/psychiatrist/referrals/{rid}/accept", {}).status_code == 200
    assert status()["status_label"] == "Подтверждено психиатром"
    assert api.post("psychiatrist", f"/api/psychiatrist/referrals/{rid}/complete", {"note": "Консультация проведена"}).status_code == 200
    s = status()
    assert s["status_label"] == "Завершено"
    assert [e["kind"] for e in s["events"]] == ["created", "received", "accepted", "completed"]
    assert api.post("psychiatrist", f"/api/psychiatrist/referrals/{rid}/complete", {}).status_code == 409


def test_drug_safety(api):
    ds = {x["code"]: x for x in api.get("doctor1", "/api/doctor/drug-safety").json()}
    assert ds["S2"]["contraindications"]
    assert any(a["symptom"] == "сонливость" for a in ds["S4"]["ae"])
    assert ds["S3"]["order"] is not None
    assert not any(m["name"].startswith("маритупирдин") for m in ds["S3"]["meds"])
    assert ds["S3"]["state_label"] == "Принимает Авиандр по назначению врача"


def test_next_visit(api):
    p1 = pid(api, "S1")
    assert api.put("doctor1", f"/api/doctor/patients/{p1}/next-visit", {"at": "завтра"}).status_code == 422
    assert api.put("doctor1", f"/api/doctor/patients/{p1}/next-visit", {"at": "2099-01-15T10:30", "note": "контроль"}).status_code == 200
