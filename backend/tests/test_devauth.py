from tests.test_api import api, env, Api  # noqa: F401  (фикстуры)
import pytest
from app.routers import devauth

def test_quick_registration_gives_public_id(api):
    p = api.post("doctor1", "/api/doctor/patients", {"code": "Q1", "sex": "ж", "birth_date": "1991-01-01"}).json()
    code = p["invite_code"]
    r = api.c.post(f"/api/public/invitation/{code}/accept-quick", json={"consent": False})
    assert r.status_code == 422
    r = api.c.post(f"/api/public/invitation/{code}/accept-quick", json={"consent": True})
    assert r.status_code == 200
    d = r.json()
    assert d["public_id"].startswith("KK-") and len(d["public_id"]) == 9
    assert d["login"] == d["public_id"].lower()
    h = {"Authorization": "Bearer " + d["token"]}
    assert api.c.get("/api/patient/home", headers=h).status_code == 200
    r2 = api.c.post("/api/auth/login", json={"login": d["login"], "password": d["password"]})
    assert r2.status_code == 200
    assert api.c.post(f"/api/public/invitation/{code}/accept-quick", json={"consent": True}).status_code == 404

def test_patient_lands_in_own_doctor_list(api):
    p = api.post("doctor1", "/api/doctor/patients", {"code": "Q2", "sex": "ж", "birth_date": "1991-01-01"}).json()
    code = p["invite_code"]
    r = api.c.post(f"/api/public/invitation/{code}/accept-quick", json={"consent": True})
    assert r.status_code == 200
    codes = [x["code"] for x in api.get("doctor1", "/api/doctor/patients").json()]
    assert "Q2" in codes

def test_auth_config_default(api):
    import os
    os.unsetenv("KK_DEV_MODE")
    os.unsetenv("KK_GOOGLE_CLIENT_ID")
    assert api.c.get("/api/public/auth-config").json() == {"dev_mode": False, "google_client_id": None}

def test_dev_endpoints_closed_by_default(api):
    import os
    os.unsetenv("KK_DEV_MODE")
    assert api.c.get("/api/dev/users").status_code == 404
    assert api.c.post("/api/dev/impersonate", json={"login": "doctor1"}).status_code == 404

def test_dev_impersonate_when_enabled(api, monkeypatch):
    monkeypatch.setenv("KK_DEV_MODE", "1")
    users = api.c.get("/api/dev/users").json()
    logins = [u["login"] for u in users]
    assert "doctor1" in logins and "duty" in logins
    r = api.c.post("/api/dev/impersonate", json={"login": "duty"})
    assert r.status_code == 200 and r.json()["role"] == "duty"
    h = {"Authorization": "Bearer " + r.json()["token"]}
    assert api.c.get("/api/auth/me", headers=h).json()["role"] == "duty"

def test_google_not_configured(api):
    import os
    os.unsetenv("KK_GOOGLE_CLIENT_ID")
    assert api.c.post("/api/auth/google", json={"id_token": "x"}).status_code == 503

def test_google_register_and_login(api, monkeypatch):
    monkeypatch.setenv("KK_GOOGLE_CLIENT_ID", "cid-test")
    monkeypatch.setattr(devauth, "verify_google_token", lambda t: {"sub": "g-123", "aud": "cid-test", "email_verified": "true"} if t == "good" else (_ for _ in ()).throw(devauth.HTTPException(401, "bad")))
    
    p = api.post("doctor1", "/api/doctor/patients", {"code": "Q3", "sex": "ж", "birth_date": "1991-01-01"}).json()
    code = p["invite_code"]
    
    r = api.c.post(f"/api/public/invitation/{code}/accept-google", json={"consent": True, "id_token": "good"})
    assert r.status_code == 200
    d = r.json()
    assert d["public_id"].startswith("KK-")
    
    r2 = api.c.post("/api/auth/google", json={"id_token": "good"})
    assert r2.status_code == 200 and r2.json()["role"] == "patient"
    
    assert api.c.post("/api/auth/google", json={"id_token": "bad"}).status_code == 401

def test_google_unknown_account(api, monkeypatch):
    monkeypatch.setenv("KK_GOOGLE_CLIENT_ID", "cid-test")
    monkeypatch.setattr(devauth, "verify_google_token", lambda t: {"sub": "unknown-sub"})
    assert api.c.post("/api/auth/google", json={"id_token": "any"}).status_code == 401