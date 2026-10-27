"""Демо: регистрация нового пациента по ссылке-приглашению (без телефона), повторное открытие, сброс; диагнозы у психиатра."""
from tests.test_api import api, env, Api, pid, alert_id  # noqa: F401

URL = "/api/public/demo-invite/DEMO-2026"
OK = {"full_name": "Соколова Анна Сергеевна", "birth_date": "1994-05-17", "password": "kompas2026", "consent": True}


def test_invite_register_reuse_reset(api):
    c = api.c
    info = c.get(URL).json()
    assert info["used"] is False and info["prefill"]["full_name"] and info["clinic"]
    assert c.get("/api/public/demo-invite/WRONG").status_code == 404
    bad = c.post(URL + "/register", json=dict(OK, full_name="анна", birth_date="2015-01-01", password="short", consent=False))
    assert bad.status_code == 422 and set(bad.json()["detail"]["fields"]) == {"full_name", "birth_date", "password", "consent"}
    r = c.post(URL + "/register", json=OK)
    assert r.status_code == 200
    tok = r.json()["token"]
    h = {"Authorization": "Bearer " + tok}
    assert c.get("/api/patient/home", headers=h).status_code == 200
    assert c.get(URL).json()["used"] is True
    assert c.post(URL + "/register", json=OK).status_code == 409  # без дубликата
    new = api.get("duty", "/api/duty/new-patients").json()
    assert len(new) == 1 and "по ссылке" in new[0]["status_label"]
    card = api.get("doctor1", f"/api/doctor/patients/{new[0]['patient_id']}/card").json()
    assert card["patient"]["status"] == "new" and not card["referrals"]
    assert c.post(URL + "/reset").json()["removed"] is True
    assert c.get(URL).json()["used"] is False and api.get("duty", "/api/duty/new-patients").json() == []
    assert c.post(URL + "/register", json=OK).status_code == 200  # сценарий можно показать снова


def test_removed_logins_and_psy_diagnoses(api):
    for login in ("clinic_admin", "staff"):
        assert api.c.post("/api/auth/login", json={"login": login, "password": "Kompas2026x"}).status_code == 401
    rows = {x["code"]: x for b in api.get("psychiatrist", "/api/psychiatrist/overview").json()["buckets"] if b["id"] == "confirmed" for x in b["patients"]}
    notes = {k: str(v) for k, v in rows.items() if k in ("S6", "S7", "S8")}
    assert "F41.1" in notes["S6"] and "F41.9" in notes["S7"] and "F43.9" in notes["S8"]
    assert all("Авиандр с" in n for n in notes.values())  # все трое на Авиандре, других препаратов нет
