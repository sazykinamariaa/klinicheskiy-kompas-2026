"""Первичная анкета по документу медиков: вопрос 14 и уточнения («Если ответ «Да», уточните…», «укажите какие»)."""
from tests.test_api import api, env, Api, pid, alert_id  # noqa: F401


def intake(api, login="patient_s1"):
    return {q["id"]: q for q in api.get(login, "/api/patient/intake").json()["questions"]}


def fu(q, fid):
    return next(f for f in q["followups"] if f["id"] == fid)


def test_q14_matches_medics_document(api):
    q = intake(api)["q14"]
    assert q["text"].startswith("Употребляете ли вы алкоголь, никотин или другие психоактивные вещества?")
    assert [o["label"] for o in q["options"]] == ["Алкоголь.", "Никотин.", "Другие психоактивные вещества.",
                                                  "Лекарства вне согласованной схемы.", "Ничего из перечисленного."]
    assert q["type"] == "multi" and q["exclusive_options"] == ["o5"]
    assert fu(q, "q14a")["show_if"] == {"q": "q14", "any": ["o1", "o2", "o3", "o4"]}
    assert "Трудности контроля" in fu(q, "q14a")["fields"]
    assert api.put("patient_s1", "/api/patient/intake/q14", {"answer": ["o1", "o5"]}).status_code == 422


def test_followups_listed(api):
    qs = intake(api)
    assert fu(qs["q4"], "q4a")["show_if"] == {"q": "q4", "any": ["o2", "o3"]}
    assert fu(qs["q7"], "q7a")["show_if"] == {"q": "q7", "not": ["o1", "o5"]}
    assert fu(qs["q1"], "q1_other")["show_if"] == {"q": "q1", "any": ["o13"]}
    assert fu(qs["q10"], "q10a")["show_if"] == {"q": "q10"}
    assert fu(qs["q14"], "q14c")["show_if"] == {"q": "q14b", "any": ["o2"]}
    assert not any(f["id"] == "q21a" for f in qs["q21"]["followups"])  # доверенный контакт — отдельный экран


def test_followup_answers_reach_doctor(api):
    assert api.put("patient_s1", "/api/patient/intake/q4", {"answer": "o3"}).status_code == 200
    assert api.put("patient_s1", "/api/patient/intake/q4a", {"answer": ["o9"]}).status_code == 422
    assert api.put("patient_s1", "/api/patient/intake/q4a", {"answer": ["o1", "o2"]}).status_code == 200
    assert api.put("patient_s1", "/api/patient/intake/q7a", {"answer": {"неизвестное поле": "x"}}).status_code == 422
    assert api.put("patient_s1", "/api/patient/intake/q1", {"answer": ["o3", "o13"]}).status_code == 200
    assert api.put("patient_s1", "/api/patient/intake/q1_other", {"answer": "шум в ушах"}).status_code == 200
    assert fu(intake(api)["q4"], "q4a")["answer"] == ["o1", "o2"]
    b = api.get("doctor1", f"/api/doctor/patients/{pid(api, 'S1')}/brief").json()
    row = next(r for r in b["intake"] if r["id"] == "q4")
    assert "Сопутствующие ощущения: Сердцебиение, Нехватка воздуха" in row["a"]
    card = api.get("doctor1", f"/api/doctor/patients/{pid(api, 'S1')}/card").json()
    q1 = next(x for x in card["intake"] if x["id"] == "q1")
    assert {"q": "Другие симптомы", "a": "шум в ушах"} in q1["details"]
    assert api.put("patient_s1", "/api/patient/intake/q1_other", {"answer": ""}).status_code == 200  # очистка
    assert fu(intake(api)["q1"], "q1_other")["answer"] is None


def test_q14_other_substances_signal_doctor(api):
    """«Другие психоактивные вещества» → R-ORANGE-04 (возможная связь симптомов с веществами), как прежнее уточнение q14d."""
    assert api.put("patient_s1", "/api/patient/intake/q14", {"answer": ["o3"]}).status_code == 200
    assert alert_id(api, "S1", "R-ORANGE-04")
    b = api.get("doctor1", f"/api/doctor/patients/{pid(api, 'S1')}/brief").json()
    assert any(r["text"].startswith("Алкоголь, никотин") for r in b["risks"]["risk_factors"])
