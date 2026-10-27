"""API-тесты: роли, согласие, подтверждение врача, алерты и очередь, рабочее время, админ без клинического доступа."""
import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

CFG_SRC = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "config"
    shutil.copytree(CFG_SRC, cfg_dir)
    monkeypatch.setenv("KK_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("KK_WORKER", "0")
    monkeypatch.setenv("KK_SEED", "1")
    monkeypatch.setenv("KK_DATA_DIR", str(tmp_path))
    from app import clock, db as DB, deps, queue as Q
    DB.init("sqlite:///%s" % (tmp_path / "t.db"))
    deps._cfg = None
    clock.set_now(datetime(2026, 10, 21, 7, 0))  # среда 10:00 по Москве — рабочее время
    Q.reset_channels()
    from app.main import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    clock.set_now(None)
    Q.reset_channels()


class Api:
    def __init__(self, c):
        self.c = c
        self.h = {}

    def as_(self, login, pw="Kompas2026x"):
        r = self.c.post("/api/auth/login", json={"login": login, "password": pw})
        assert r.status_code == 200, r.text
        self.h[login] = {"Authorization": "Bearer " + r.json()["token"]}
        return self.h[login]

    def get(self, login, url, **kw):
        return self.c.get(url, headers=self.h.get(login) or self.as_(login), **kw)

    def post(self, login, url, json=None, **kw):
        return self.c.post(url, headers=self.h.get(login) or self.as_(login), json=json, **kw)

    def put(self, login, url, json=None):
        return self.c.put(url, headers=self.h.get(login) or self.as_(login), json=json)


@pytest.fixture()
def api(env):
    return Api(env)


def pid(api, code):
    return next(p["id"] for p in api.get("doctor1", "/api/doctor/patients").json() if p["code"] == code)


def run_queue():
    from app import db as DB, deps, queue as Q
    with DB.session_scope() as s:
        return Q.process_due(s, deps.get_cfg())


def drain():
    """Обработать очередь до тех пор, пока появляются новые задачи (эскалация ставит уведомления отдельными задачами)."""
    for _ in range(3):
        run_queue()


def alert_id(api, code, rule):
    p = pid(api, code)
    return next(a["id"] for a in api.get("doctor1", f"/api/doctor/patients/{p}/card").json()["alerts"] if a["rule_id"] == rule)


# ------------------------------------------------------------------ вход и роли

def test_requires_auth(api):
    assert api.c.get("/api/doctor/patients").status_code == 401
    assert api.c.post("/api/auth/login", json={"login": "doctor1", "password": "bad"}).status_code == 401


def test_roles_are_separated(api):
    assert api.get("admin", "/api/doctor/patients").status_code == 403
    assert api.get("admin", "/api/alerts").status_code == 403
    assert api.get("patient_s1", "/api/doctor/patients").status_code == 403
    assert api.get("psychiatrist", "/api/doctor/patients").status_code == 403
    assert api.get("doctor1", "/api/admin/config/summary").status_code == 403


def test_other_doctor_cannot_see_patient(api):
    p = pid(api, "S1")
    assert api.get("doctor2", f"/api/doctor/patients/{p}/card").status_code == 404
    assert not {"S1", "S2", "S3", "S4", "S5"} & {x["code"] for x in api.get("doctor2", "/api/doctor/patients").json()}


def test_admin_audit_has_no_clinical_detail(api):
    p = pid(api, "S1")
    api.get("doctor1", f"/api/doctor/patients/{p}/card")
    rows = api.get("admin", "/api/admin/audit").json()
    assert rows and all(set(r) == {"id", "ts", "actor_id", "actor_role", "action", "entity"} for r in rows)


# ------------------------------------------------------------------ подтверждение врача — единственный путь

def test_orders_created_only_in_proposals_module():
    src = Path(__file__).resolve().parents[1] / "app"
    pat = re.compile(r"M\.(TherapyOrder|Referral|StatusChange)\(")
    bad = [str(f.relative_to(src)) for f in src.rglob("*.py") if f.name != "proposals.py" and pat.search(f.read_text(encoding="utf-8"))]
    assert not bad, "назначения/направления/статусы создаются вне proposals.py: %s" % bad


def test_nothing_is_ordered_without_confirmation(api):
    from app import db as DB, models as M
    for p in api.get("doctor1", "/api/doctor/patients").json():
        api.get("doctor1", f"/api/doctor/patients/{p['id']}/card")
    with DB.session_scope() as s:
        # статусов в начальных данных нет; направления и назначения — только через подтверждённое врачом предложение
        assert s.execute(select(M.StatusChange)).first() is None
        for r in s.execute(select(M.Referral)).scalars():
            prop = s.get(M.Proposal, r.proposal_id)
            assert prop is not None and prop.kind == "routing" and prop.status == "confirmed" and s.get(M.User, r.confirmed_by).role == "doctor"
        for o in s.execute(select(M.TherapyOrder)).scalars():
            prop = s.get(M.Proposal, o.proposal_id)
            assert prop is not None and prop.kind == "therapy" and prop.status == "confirmed"
            assert prop.decided_by == o.confirmed_by and s.get(M.User, o.confirmed_by).role == "doctor"
            assert s.execute(select(M.AuditLog).where(M.AuditLog.action == "proposal.confirm", M.AuditLog.entity_id == str(prop.id))).first()


def test_decision_permissions_and_reason(api):
    p = pid(api, "S1")
    prop = api.get("doctor1", f"/api/doctor/patients/{p}/card").json()["proposals"][0]
    url = f"/api/doctor/proposals/{prop['id']}/decision"
    assert api.post("patient_s1", url, {"decision": "confirm"}).status_code == 403
    assert api.post("psychiatrist", url, {"decision": "confirm"}).status_code == 403
    assert api.post("duty", url, {"decision": "confirm"}).status_code == 403
    assert api.post("doctor2", url, {"decision": "confirm"}).status_code == 403
    assert api.post("doctor1", url, {"decision": "reject"}).status_code == 422
    assert api.post("doctor1", url, {"decision": "reject", "reason": "  "}).status_code == 422
    assert api.post("doctor1", url, {"decision": "modify"}).status_code == 422


def test_confirm_therapy_creates_order_once(api):
    p = pid(api, "S1")
    prop = api.get("doctor1", f"/api/doctor/patients/{p}/card").json()["proposals"][0]
    assert prop["kind"] == "therapy"
    url = f"/api/doctor/proposals/{prop['id']}/decision"
    assert api.post("doctor1", url, {"decision": "confirm"}).status_code == 200
    assert api.post("doctor1", url, {"decision": "confirm"}).status_code == 409
    card = api.get("doctor1", f"/api/doctor/patients/{p}/card").json()
    assert len(card["orders"]) == 1


def test_confirm_rechecks_drug_safety(api):
    p = pid(api, "S1")
    prop = api.get("doctor1", f"/api/doctor/patients/{p}/card").json()["proposals"][0]
    # после появления противопоказания подтверждение должно отказать
    r = api.put("doctor1", f"/api/doctor/patients/{p}/profile/hypersensitivity", {"value": "yes"})
    assert r.status_code == 200 and r.json()["drug_state"] == "contraindicated"
    r = api.post("doctor1", f"/api/doctor/proposals/{prop['id']}/decision", {"decision": "confirm"})
    assert r.status_code in (409, 422)
    assert api.get("doctor1", f"/api/doctor/patients/{p}/card").json()["orders"] == []


def test_unknown_stays_unknown(api):
    p = pid(api, "S1")
    api.put("doctor1", f"/api/doctor/patients/{p}/profile/epilepsy", {"value": "unknown"})
    card = api.get("doctor1", f"/api/doctor/patients/{p}/card").json()
    assert card["assessment"]["drug_check"]["state"] == "safety_check_incomplete"
    assert card["assessment"]["therapy_suggestion"] is None


def test_confirm_routing_creates_referral_and_psychiatrist_sees_it(api):
    p = pid(api, "S5")
    card = api.get("doctor1", f"/api/doctor/patients/{p}/card").json()
    m01 = next(x for x in card["proposals"] if x["key"] == "M-01")
    assert api.post("doctor1", f"/api/doctor/proposals/{m01['id']}/decision", {"decision": "confirm"}).status_code == 200
    refs = api.get("psychiatrist", "/api/psychiatrist/referrals").json()
    refs = [x for x in refs if x["patient"] == "S5"]
    assert len(refs) == 1 and refs[0]["status"] == "awaiting_acceptance"
    rid = refs[0]["id"]
    assert api.get("psychiatrist", f"/api/psychiatrist/referrals/{rid}").json()["summary"]["sections"]["scales"]
    r = api.get("psychiatrist", f"/api/psychiatrist/referrals/{rid}/summary.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert api.get("psychiatrist", f"/api/psychiatrist/referrals/{rid}/summary.fhir").json()["resourceType"] == "Bundle"
    assert api.post("psychiatrist", f"/api/psychiatrist/referrals/{rid}/accept").json()["status"] == "accepted"
    assert api.get("doctor2", "/api/psychiatrist/referrals").status_code == 403


# ------------------------------------------------------------------ алерты

def test_red_alert_close_rules(api):
    a = alert_id(api, "S5", "R-RED-01")
    # «не удалось связаться» не закрывает
    bad = {"close_reason": "assessment_done_plan_agreed", "data": {
        "contact_method": "не удалось связаться", "safety_assessment": {"thoughts": "?", "intent": "?", "plan": "?", "behavior": "?", "can_stay_safe": "?"},
        "decision": "повторить", "handed_to": "дежурный", "next_contact_due": "через 15 минут", "comment": "нет ответа"}}
    r = api.post("doctor1", f"/api/alerts/{a}/close", bad)
    assert r.status_code == 409
    # без обязательных полей
    r = api.post("doctor1", f"/api/alerts/{a}/close", {"close_reason": "assessment_done_plan_agreed", "data": {"contact_method": "телефон"}})
    assert r.status_code == 422 and "обязательные" in r.json()["detail"]
    # попытка связи без результата алерт не закрывает
    assert api.post("doctor1", f"/api/alerts/{a}/contact", {"result": "unreachable", "method": "телефон"}).json()["still_open"] is True
    ok = dict(bad)
    ok["data"] = dict(bad["data"], contact_method="телефон, дозвонились")
    r = api.post("doctor1", f"/api/alerts/{a}/close", ok)
    assert r.status_code == 200, r.text
    d = api.get("doctor1", f"/api/alerts/{a}").json()
    assert d["status"] == "closed_with_documented_result" and d["close_data"]["assessed_by"]["user"] == "doctor1"


def test_red_alert_notifies_immediately_and_is_idempotent(api):
    p = pid(api, "S5")
    api.get("doctor1", f"/api/doctor/patients/{p}/card")
    st = run_queue()
    assert st["sent"] >= 2
    api.get("doctor1", f"/api/doctor/patients/{p}/card")  # повторная оценка не плодит алерты и задачи
    st2 = run_queue()
    assert st2["sent"] == 0
    from app import db as DB, models as M
    with DB.session_scope() as s:
        logs = s.execute(select(M.NotificationLog).where(M.NotificationLog.status == "delivered")).scalars().all()
        keys = [(l.alert_id, l.recipient, l.channel) for l in logs if l.alert_id]
        recipients = {l.recipient for l in logs}
        assert "doctor1" in recipients and "duty" in recipients  # отдельного ответственного сотрудника нет — получает дежурный
        assert len(keys) == len(set(keys))


def test_red_escalation_chain_and_acceptance_stops_it(api):
    from app import clock, db as DB, models as M
    p = pid(api, "S5")
    api.get("doctor1", f"/api/doctor/patients/{p}/card")
    run_queue()
    clock.advance(minutes=6)
    drain()
    with DB.session_scope() as s:
        who = {l.recipient for l in s.execute(select(M.NotificationLog)).scalars()}
        steps = [e.data for e in s.execute(select(M.AlertEvent).where(M.AlertEvent.kind == "escalated")).scalars()]
    assert "duty" in who and any(x["to"] == "duty_doctor" for x in steps) and not any(x["to"] == "clinic_admin_on_duty" for x in steps)
    clock.advance(minutes=5)
    drain()
    with DB.session_scope() as s:
        steps = [e.data for e in s.execute(select(M.AlertEvent).where(M.AlertEvent.kind == "escalated")).scalars()]
    # второй шаг цепочки (администратор смены): отдельной учётной записи нет — уведомление получает дежурный врач
    assert any(x["to"] == "clinic_admin_on_duty" and x["recipients"] == ["duty"] for x in steps)


def test_acceptance_cancels_escalation(api):
    from app import clock, db as DB, models as M
    p = pid(api, "S5")
    card = api.get("doctor1", f"/api/doctor/patients/{p}/card").json()
    run_queue()
    for a in card["alerts"]:
        if a["level"] == "red":
            assert api.post("doctor1", f"/api/alerts/{a['id']}/accept").status_code == 200
    clock.advance(minutes=12)
    drain()
    with DB.session_scope() as s:
        steps = [e.data for e in s.execute(select(M.AlertEvent).where(M.AlertEvent.kind == "escalated")).scalars()]
    assert not [x for x in steps if str(x.get("step", "")).startswith("s")]  # шаги цепочки s0/s1 не сработали


def test_channel_failure_retries_then_falls_back_and_escalates(api):
    from app import clock, db as DB, models as M, queue as Q
    Q.CHANNELS["push"].always_fail = True
    p = pid(api, "S5")
    api.get("doctor1", f"/api/doctor/patients/{p}/card")
    run_queue()
    for _ in range(8):
        clock.advance(minutes=20)
        drain()
    with DB.session_scope() as s:
        logs = s.execute(select(M.NotificationLog)).scalars().all()
        assert any(l.channel == "push" and l.status == "failed" for l in logs)
        assert any(l.channel == "sms" and l.status == "delivered" for l in logs)  # запасной канал
        assert any(l.recipient == "duty" and l.status == "delivered" for l in logs)  # эскалация при сбое
        dead = s.execute(select(M.Outbox).where(M.Outbox.status == "dead")).scalars().all()
        assert dead and all(j.attempts == Q.MAX_ATTEMPTS for j in dead)


def test_orange_after_hours_is_queued_to_next_working_start(api):
    from app import clock, db as DB, models as M
    drain()  # доставить всё, что накопилось при сидинге (среда, рабочее время)
    clock.set_now(datetime(2026, 10, 24, 15, 0))  # суббота
    with DB.session_scope() as s0:
        before = len(s0.execute(select(M.NotificationLog).where(M.NotificationLog.recipient == "doctor1")).scalars().all())
    p = pid(api, "S1")
    api.put("doctor1", f"/api/doctor/patients/{p}/flags/secondary_cause_suspected", {"value": True})
    # оранжевый алерт: пациент нажал кнопку
    tok = api.as_("patient_s1")
    r = api.c.post("/api/patient/need-support", headers=tok)
    assert r.status_code == 200 and r.json()["after_hours_notice"]
    assert "112" in json.dumps(r.json(), ensure_ascii=False)
    run_queue()
    with DB.session_scope() as s:
        delivered = s.execute(select(M.NotificationLog).where(M.NotificationLog.status == "delivered")).scalars().all()
        assert len([l for l in delivered if l.recipient == "doctor1"]) == before  # врачу — в начале рабочего дня
        assert any(l.recipient == "duty" for l in delivered)  # дежурный получил информацию
    clock.set_now(datetime(2026, 10, 26, 6, 30))  # понедельник 09:30 МСК
    run_queue()
    with DB.session_scope() as s:
        assert len([l for l in s.execute(select(M.NotificationLog).where(M.NotificationLog.status == "delivered")).scalars() if l.recipient == "doctor1"]) > before


def test_orange_in_hours_notifies_doctor_now(api):
    from app import db as DB, models as M
    tok = api.as_("patient_s2")
    assert api.c.post("/api/patient/need-support", headers=tok).json()["after_hours_notice"] is None
    run_queue()
    with DB.session_scope() as s:
        assert any(l.recipient == "doctor1" for l in s.execute(select(M.NotificationLog)).scalars())


# ------------------------------------------------------------------ пациент

FORBIDDEN = re.compile(r"R-RED|R-ORANGE|R-YELLOW|\"level\"|красн|оранжев|red_|orange|alert", re.I)


def test_patient_never_sees_levels(api):
    for path in ("/api/patient/home", "/api/patient/support", "/api/patient/support/details", "/api/patient/trend"):
        txt = api.get("patient_s5", path).text
        assert not FORBIDDEN.search(txt), (path, FORBIDDEN.search(txt).group(0))
    sup = api.get("patient_s5", "/api/patient/support").json()
    assert sup["screen"] == "support_short"
    assert {b["id"] for b in sup["buttons"]} >= {"call_112", "call_103"}


def test_consent_gate_and_flow(api):
    p = api.post("doctor1", "/api/doctor/patients", {"code": "N1", "sex": "ж", "birth_date": "1990-05-05"})
    assert p.status_code == 200
    code = p.json()["invite_code"]
    assert "<svg" in p.json()["qr_svg"]
    assert api.c.get(f"/api/public/invitation/{code}").status_code == 200
    r = api.c.post(f"/api/public/invitation/{code}/accept", json={"consent": False, "login": "newp", "password": "longpassword1"})
    assert r.status_code == 422
    r = api.c.post(f"/api/public/invitation/{code}/accept", json={"consent": True, "login": "newp", "password": "longpassword1"})
    assert r.status_code == 200
    h = {"Authorization": "Bearer " + r.json()["token"]}
    assert api.c.get("/api/patient/home", headers=h).status_code == 200
    assert api.c.post(f"/api/public/invitation/{code}/accept", json={"consent": True, "login": "x2x2x", "password": "longpassword1"}).status_code == 404
    # отзыв согласия закрывает ввод данных
    assert api.c.post("/api/patient/consent/revoke", headers=h).status_code == 200
    assert api.c.get("/api/patient/home", headers=h).status_code == 403
    assert api.c.put("/api/patient/intake/q1", headers=h, json={"answer": ["o1"]}).status_code == 403


def _new_patient(api, code="N2"):
    p = api.post("doctor1", "/api/doctor/patients", {"code": code, "sex": "м", "birth_date": "1985-03-03"}).json()
    r = api.c.post(f"/api/public/invitation/{p['invite_code']}/accept", json={"consent": True, "login": "u_" + code.lower(), "password": "longpassword1"})
    return p["patient_id"], {"Authorization": "Bearer " + r.json()["token"]}


def test_intake_q12_current_raises_orange_and_requires_followup(api):
    pid_, h = _new_patient(api)
    q12 = next(q for q in api.c.get("/api/patient/intake", headers=h).json()["questions"] if q["id"] == "q12")
    cur = next(o["id"] for o in q12["options"] if "присутствуют сейчас" in o["label"])
    assert api.c.put("/api/patient/intake/q12", headers=h, json={"answer": "zzz"}).status_code == 422
    assert api.c.put("/api/patient/intake/q12", headers=h, json={"answer": cur}).status_code == 200
    card = api.get("doctor1", f"/api/doctor/patients/{pid_}/card").json()
    assert any(a["level"] == "orange" for a in card["alerts"])
    # подтверждённые намерение и план -> красный
    sf = {f"sf{i}": "no" for i in range(1, 10)}
    sf.update(sf1="yes", sf2="yes", sf4="yes", sf5="yes", sf8="no")
    assert api.c.post("/api/patient/safety-followup", headers=h, json={"answers": sf}).status_code == 200
    card = api.get("doctor1", f"/api/doctor/patients/{pid_}/card").json()
    assert card["level"] == "red"


def test_unsure_answer_does_not_lower_and_is_not_red(api):
    pid_, h = _new_patient(api, "N3")
    q12 = next(q for q in api.c.get("/api/patient/intake", headers=h).json()["questions"] if q["id"] == "q12")
    rec = next(o["id"] for o in q12["options"] if "последние дни" in o["label"])
    api.c.put("/api/patient/intake/q12", headers=h, json={"answer": rec})
    sf = {f"sf{i}": "unsure" for i in range(1, 10)}
    api.c.post("/api/patient/safety-followup", headers=h, json={"answers": sf})
    card = api.get("doctor1", f"/api/doctor/patients/{pid_}/card").json()
    assert card["level"] == "orange"  # не красный и не ниже оранжевого


def test_phq9_partial_has_no_total_and_unresolved_item9_flag(api):
    pid_, h = _new_patient(api, "N4")
    sc = api.c.get("/api/patient/scales/phq9", headers=h).json()
    ids = [i["id"] for i in sc["items"]]
    part = {i: 1 for i in ids[:5]}
    r = api.c.post("/api/patient/scales/phq9", headers=h, json={"answers": part, "finish": True}).json()
    assert r["complete"] is False and "result" not in r
    assert "score" not in json.dumps(r) and "total" not in json.dumps(r)
    rest = {i: 1 for i in ids[5:]}
    r = api.c.post("/api/patient/scales/phq9", headers=h, json={"answers": rest}).json()
    assert r["complete"] is True
    assert r["safety_followup_needed"] is True  # пункт 9 >= 1
    card = api.get("doctor1", f"/api/doctor/patients/{pid_}/card").json()
    assert card["dynamics"]["series"]["phq9"]["latest"] == 9


def test_checkin_requires_enabling_and_c6_yes_triggers_followup(api):
    pid_, h = _new_patient(api, "N5")
    assert api.c.get("/api/patient/checkin", headers=h).status_code == 409
    api.put("doctor1", f"/api/doctor/patients/{pid_}/checkin", {"enabled": True})
    r = api.c.post("/api/patient/checkin", headers=h, json={"answers": {"c6": "да"}, "finish": False})
    assert r.status_code == 200 and r.json()["safety_followup_needed"] is True and r.json()["complete"] is False
    assert api.c.post("/api/patient/checkin", headers=h, json={"answers": {"c1": 11}}).status_code == 422


# ------------------------------------------------------------------ администратор и конфигурация

def test_admin_config_views(api):
    s = api.get("admin", "/api/admin/config/summary").json()
    assert s["rules_total"] > 0 and s["rules_executable"] > 0
    w = api.get("admin", "/api/admin/config/waiting").json()
    assert w["count"] > 0
    assert any(r["id"] == "R-RED-01" and r["executable"] for r in api.get("admin", "/api/admin/config/rules").json())


def test_bad_config_is_rejected_and_good_one_applies_without_code_change(api):
    cur = api.get("admin", "/api/admin/config/files/scales").json()
    r = api.put("admin", "/api/admin/config/files/scales", {"content": {"broken": True}, "comment": "ломаем"})
    assert r.status_code == 422
    assert api.get("admin", "/api/admin/config/files/scales").json() == cur
    # добавление шкалы без изменения кода
    new = json.loads(json.dumps(cur))
    new["scales"].append({"id": "demo_scale", "title": "Демо-шкала", "enabled": True, "administered_by": "patient", "answers": [{"value": 0, "label": "нет"}, {"value": 1, "label": "да"}],
                          "items": [{"id": "d1", "text": "Вопрос 1"}, {"id": "d2", "text": "Вопрос 2"}], "scoring": {"type": "sum", "range": [0, 2]},
                          "interpretation": [{"from": 0, "to": 2, "severity_band": "демо", "doctor_label": "демо"}], "status": "draft_demo", "source_ids": []})
    r = api.put("admin", "/api/admin/config/files/scales", {"content": new, "comment": "демо: новая шкала"})
    assert r.status_code == 200, r.text
    assert any(s["id"] == "demo_scale" for s in api.get("admin", "/api/scales/registry").json())
    tok = api.as_("patient_s1")
    r = api.c.post("/api/patient/scales/demo_scale", headers=tok, json={"answers": {"d1": 1, "d2": 0}})
    assert r.status_code == 200 and r.json()["complete"] is True


def test_sources_registry_shows_unverified_honestly(api):
    srcs = api.get("doctor1", "/api/sources").json()["sources"]
    buckets = {s["bucket"] for s in srcs}
    assert "confirmed" in buckets
    ids = {s["id"] for s in srcs}
    assert not ids & {"SRC-RASS", "SRC-PDSS", "SRC-ISI", "SRC-KOP25", "SRC-SPRAS", "SRC-AVIANDR-SECONDARY"}  # ТЗ: удалены
    assert all(s.get("ui_text_allowed") is False for s in srcs if s["id"] in ("SRC-LSAS", "SRC-RUSAUDIT"))


def test_integration_stub(api):
    p = pid(api, "S1")
    assert api.post("doctor1", f"/api/integration/mis/push/{p}").json()["accepted"] is True
    assert api.get("admin", "/api/integration/status").json()["sent_count"] == 1


# ------------------------------------------------------------------ импорт

def test_import_requires_doctor_review(api):
    p = pid(api, "S1")
    text = "Диагноз F41.1. Принимает сертралин 50 мг в сутки. СКФ 90. PHQ-9: 8."
    job = api.post("doctor1", f"/api/doctor/patients/{p}/import", {"text": text}).json()
    kinds = [it["kind"] for _, it in job["items"]]
    assert {"dx_icd10", "med", "egfr_ml_min", "scale_total"} <= set(kinds)
    # до проверки врачом в карточке ничего не изменилось
    assert api.get("doctor1", f"/api/doctor/patients/{p}/meds").json() == []
    med_idx = next(i for i, it in job["items"] if it["kind"] == "med")
    sc_idx = next(i for i, it in job["items"] if it["kind"] == "scale_total")
    r = api.post("doctor1", f"/api/doctor/patients/{p}/import/{job['job_id']}/apply", {"accept": [med_idx, sc_idx]})
    assert r.json()["applied"] == [med_idx]  # справочные кандидаты в расчёт не входят
    assert [m["name"] for m in api.get("doctor1", f"/api/doctor/patients/{p}/meds").json()] == ["сертралин"]
    card = api.get("doctor1", f"/api/doctor/patients/{p}/card").json()
    assert card["assessment"]["drug_check"]["state"] != "indicated_pending_doctor"  # список препаратов снова не подтверждён
    assert api.post("doctor1", f"/api/doctor/patients/{p}/import/{job['job_id']}/apply", {"accept": []}).status_code == 409
