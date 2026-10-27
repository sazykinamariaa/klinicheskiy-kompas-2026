"""Синтетические пациенты для сценариев S1–S5 (scenarios.json). Все данные вымышленные.

scenarios.json задаёт профиль кратко; здесь он раскрыт до полного набора фактов по тексту `history`
(например «беременности и лактации нет» -> pregnancy=no). Оставшиеся клинические факты, которых
сценарий не называет, в сценарии S3 и S4 НЕ заполняются намеренно: так видно, как работают «неизвестно» и маршрутизация.
"""
from datetime import datetime, timedelta

T0 = datetime(2026, 9, 1, 10, 0)


def vec(cfg, scale_id, values):
    items = [i["id"] for i in cfg.scales[scale_id]["items"]]
    assert len(items) == len(values), (scale_id, len(items), len(values))
    return dict(zip(items, values))


def fill(cfg, scale_id, total):
    """Равномерно распределить итог по пунктам PHQ-9/GAD-7 (0–3)."""
    n = len(cfg.scales[scale_id]["items"])
    vals = [0] * n
    skip = n - 1 if scale_id == "phq9" else None  # пункт 9 (безопасность) не заполняем «для круглого счёта»
    i = 0
    while sum(vals) < total:
        k = i % n
        if k != skip and vals[k] < 3:
            vals[k] += 1
        i += 1
    return vec(cfg, scale_id, vals)


def run(cfg, sid, weeks, answers):
    return {"scale_id": sid, "at": T0 + timedelta(weeks=weeks), "answers": answers}


FULL_NO = {  # полный набор клинических фактов «нет» (врач проверил)
    "hypersensitivity": "no", "epilepsy": "no", "organic_brain_disease": "no",
    "maoi_current": "no", "maoi_last_dose_date": "none",
    "pregnancy": "no", "lactation": "no",
    "cardiovascular_disease": "no", "diabetes_or_endocrine": "no", "alcohol_or_drug_dependence": "no",
    "galactose_lactase_intolerance": "no", "liver_failure_child_pugh": "нет", "meds_confirmed": "yes",
}


def s1(cfg, week=0):
    """S1: ГТР 8 мес, F41.1, всё чисто. Авиандр подходит."""
    t = {0: (6, 14), 2: (5, 10), 4: (3, 7), 6: (2, 5)}
    runs = [run(cfg, "phq9", w, fill(cfg, "phq9", t[w][0])) for w in t if w <= week] + \
           [run(cfg, "gad7", w, fill(cfg, "gad7", t[w][1])) for w in t if w <= week]
    fields = dict(FULL_NO, dx_icd10="F41.1", egfr_ml_min=96)
    st = {
        "now": T0 + timedelta(weeks=week),
        "profile": {"sex": "ж", "age": 36, "fields": fields},
        "intake": {"q2": "o4", "q4": "o1", "q5": ["o8"], "q6": "o3", "q7": "o1", "q8": "o1", "q12": "o1", "q13": "o2",
                   "q14": ["o5"], "q16": "o1", "q21": "o1"},
        "scale_runs": runs,
        "meds": {"items": [], "confirmed_by_doctor": True},
        "symptoms": {n: {"present": "yes", "duration_weeks": 35} for n in
                     ["сердцебиение", "потливость", "тремор (дрожь)", "трудности с засыпанием из-за беспокойства", "мышечное напряжение или боли"]},
    }
    if week >= 0:
        st["therapy"] = {"started_on": T0.date()} if week > 0 else {}
    return st


def s2(cfg, week=0):
    """S2: ГТР, СКФ 48 -> противопоказание."""
    t = {0: (7, 13), 2: (7, 12), 4: (5, 9)}
    runs = [run(cfg, "phq9", w, fill(cfg, "phq9", t[w][0])) for w in t if w <= week] + \
           [run(cfg, "gad7", w, fill(cfg, "gad7", t[w][1])) for w in t if w <= week]
    fields = dict(FULL_NO, dx_icd10="F41.1", egfr_ml_min=48)
    return {
        "now": T0 + timedelta(weeks=week),
        "profile": {"sex": "м", "age": 57, "fields": fields},
        "intake": {"q2": "o4", "q4": "o1", "q5": ["o8"], "q6": "o3", "q7": "o1", "q8": "o1", "q12": "o1", "q13": "o3",
                   "q14": ["o5"], "q16": "o1", "q21": "o1"},
        "scale_runs": runs,
        "meds": {"items": ["амлодипин"], "confirmed_by_doctor": True},
        "symptoms": {n: {"present": "yes", "duration_weeks": 52} for n in
                     ["сердцебиение", "потливость", "тремор (дрожь)", "трудности с засыпанием из-за беспокойства"]},
    }


def s3(cfg, week=0):
    """S3: сертралин; код диагноза врача ещё не внесён (в сценарии «[ЖДЁМ: код врача]»)."""
    t = {0: (11, 13), 2: (9, 11), 4: (7, 8)}
    runs = [run(cfg, "phq9", w, fill(cfg, "phq9", t[w][0])) for w in t if w <= week] + \
           [run(cfg, "gad7", w, fill(cfg, "gad7", t[w][1])) for w in t if w <= week]
    fields = dict(FULL_NO, egfr_ml_min=88)  # dx_icd10 не внесён
    return {
        "now": T0 + timedelta(weeks=week),
        "profile": {"sex": "ж", "age": 42, "fields": fields},
        "intake": {"q2": "o4", "q4": "o1", "q5": ["o8"], "q6": "o3", "q7": "o3", "q8": "o1", "q12": "o1", "q13": "o2",
                   "q14": ["o5"], "q16": "o1", "q21": "o1"},
        "scale_runs": runs,
        "meds": {"items": [{"name": "сертралин", "dose": "100 мг/сут"}], "confirmed_by_doctor": True},
    }


S4_PHQ = [3, 3, 2, 3, 2, 2, 2, 2, 0]  # сумма 19, пункт 9 = 0


def s4(cfg, week=0):
    """S4: 7 недель депрессивных симптомов, PHQ-9=19, преобладает депрессия."""
    t = {0: 19, 2: 17, 4: 12, 6: 8}
    g = {0: 8, 2: 7, 4: 5, 6: 4}
    runs = []
    for w in t:
        if w <= week:
            ans = vec(cfg, "phq9", S4_PHQ) if w == 0 else fill(cfg, "phq9", t[w])
            runs.append(run(cfg, "phq9", w, ans))
            runs.append(run(cfg, "gad7", w, fill(cfg, "gad7", g[w])))
    return {
        "now": T0 + timedelta(weeks=week),
        "profile": {"sex": "м", "age": 31, "fields": {"predominant_syndrome": "преобладает депрессивная симптоматика"}},
        "intake": {"q2": "o2", "q4": "o1", "q5": ["o8"], "q6": "o4", "q7": "o1", "q8": "o1", "q12": "o1", "q13": "o3",
                   "q14": ["o5"], "q16": "o1", "q21": "o1"},
        "scale_runs": runs,
        "meds": {"items": [], "confirmed_by_doctor": True},
    }


def s5(cfg, week=3):
    """S5 (ЧЕРНОВИК разработки): ухудшение, ответ «да» в чек-ине, намерение и план подтверждены."""
    t = {0: (8, 15), 2: (12, 14), 3: (17, 16)}
    runs = []
    for w in t:
        if w <= week:
            p = fill(cfg, "phq9", t[w][0])
            if w == 3:
                p = dict(p)
                # итог 17 при пункте 9 = 2
                vals = [2, 2, 2, 2, 2, 2, 2, 1, 2]
                p = vec(cfg, "phq9", vals)
            runs.append(run(cfg, "phq9", w, p))
            runs.append(run(cfg, "gad7", w, fill(cfg, "gad7", t[w][1])))
    fields = dict(FULL_NO, dx_icd10="F41.1", egfr_ml_min=90)
    d = (T0 + timedelta(weeks=week)).date()
    return {
        "now": T0 + timedelta(weeks=week, hours=1),
        "profile": {"sex": "ж", "age": 28, "fields": fields},
        "intake": {"q2": "o4", "q4": "o1", "q5": ["o8"], "q6": "o3", "q7": "o1", "q8": "o1", "q12": "o1", "q13": "o2",
                   "q14": ["o5"], "q16": "o1", "q21": "o1"},
        "scale_runs": runs,
        "meds": {"items": [{"name": "маритупирдин", "dose": "20 мг 2 р/сут"}], "confirmed_by_doctor": True},
        "therapy": {"started_on": T0.date()},
        "checkin": {"enabled_on": T0.date(), "entries": [{"date": d, "answers": {"c6": "да"}}]},
        "adherence_events": [
            {"date": d - timedelta(days=8), "kind": "confirmed_missed_partial"},
            {"date": d - timedelta(days=7), "kind": "confirmed_missed_partial"},
        ],
        "safety_followup": {
            "started": True, "complete": True,
            "answers": {"sf1": "yes", "sf2": "yes", "sf3": "yes", "sf4": "yes", "sf5": "yes", "sf6": "no", "sf7": "yes", "sf8": "no", "sf9": "yes"},
        },
    }


# ---- раскладка по трём сценариям ТЗ (лечение Авиандром); исходные s3/s4 остаются эталонами тестов ----

INTAKE_GAD = {"q2": "o4", "q4": "o1", "q5": ["o8"], "q6": "o3", "q7": "o1", "q8": "o1", "q12": "o1", "q13": "o2", "q14": ["o5"], "q16": "o1", "q21": "o1"}
AVIANDR = {"name": "маритупирдин", "dose": "20 мг 2 р/сут"}

def _ck_entries(days, skip, answers_for_day):
    result = []
    for d in range(1, days + 1):
        if not skip(d):
            result.append({"date": (T0 + timedelta(days=d)).date(), "answers": answers_for_day(d)})
    return result

def s3_treatment(cfg, week=6):
    """S3: ГТР, лечение Авиандром с недели 0, хорошая динамика; лёгкое головокружение в первые дни прошло."""
    t = {0: (8, 15), 2: (6, 11), 4: (4, 8), 6: (3, 6)}
    runs = [run(cfg, "phq9", w, fill(cfg, "phq9", t[w][0])) for w in t if w <= week] + [run(cfg, "gad7", w, fill(cfg, "gad7", t[w][1])) for w in t if w <= week]
    def answers(d):
        c1 = round(6 - 4 * d / max(1, week * 7))
        c2 = round(7 - 5 * d / max(1, week * 7))
        c3 = "плохо" if d <= 7 else ("удовлетворительно" if d <= 21 else "хорошо")
        c4 = "часть приёмов пропущена" if d == 9 else "всё принято"
        c5 = "были, почти не мешали" if d <= 4 else "нет"
        c6 = "нет"
        return {"c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5, "c6": c6}
    def skip(d):
        return d % 5 == 4
    return {
        "now": T0 + timedelta(weeks=week),
        "profile": {"sex": "ж", "age": 42, "fields": dict(FULL_NO, dx_icd10="F41.1", egfr_ml_min=88)},
        "intake": dict(INTAKE_GAD),
        "scale_runs": runs,
        "meds": {"items": [dict(AVIANDR)], "confirmed_by_doctor": True},
        "therapy": {"started_on": T0.date()},
        "symptoms": {n: {"present": "yes", "duration_weeks": 44} for n in ["сердцебиение", "потливость", "мышечное напряжение или боли", "трудности с засыпанием из-за беспокойства"]},
        "checkin": {"enabled_on": T0.date(), "entries": _ck_entries(week * 7, skip, answers)},
        "adherence_events": [{"date": (T0 + timedelta(days=9)).date(), "kind": "confirmed_missed_partial"}],
        "goal": {"text": "Спокойно засыпать и без страха ездить на работу", "by": "patient"},
    }

def s4_treatment_ae(cfg, week=4):
    """S4: ГТР, лечение Авиандром с недели 0; со 2-й недели сонливость мешает работе и сохраняется; заметного улучшения нет."""
    t = {0: (7, 14), 2: (7, 13), 4: (6, 12)}
    runs = [run(cfg, "phq9", w, fill(cfg, "phq9", t[w][0])) for w in t if w <= week] + [run(cfg, "gad7", w, fill(cfg, "gad7", t[w][1])) for w in t if w <= week]
    def answers(d):
        c1 = 5 if d <= 14 else 4
        c2 = 6 if d <= 14 else 5
        c3 = "удовлетворительно"
        c4 = "часть приёмов пропущена" if d in (15, 16) else "всё принято"
        c5 = "мешали обычным делам" if d >= 11 else "нет"
        c6 = "нет"
        return {"c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5, "c6": c6}
    def skip(d):
        return d % 4 == 3
    return {
        "now": T0 + timedelta(weeks=week),
        "profile": {"sex": "м", "age": 47, "fields": dict(FULL_NO, dx_icd10="F41.1", egfr_ml_min=92)},
        "intake": dict(INTAKE_GAD, q6="o4", q13="o3"),
        "scale_runs": runs,
        "meds": {"items": [dict(AVIANDR)], "confirmed_by_doctor": True},
        "therapy": {"started_on": T0.date()},
        "symptoms": {n: {"present": "yes", "duration_weeks": 40} for n in ["сердцебиение", "тремор (дрожь)", "мышечное напряжение или боли", "трудности с засыпанием из-за беспокойства"]},
        "checkin": {"enabled_on": T0.date(), "entries": _ck_entries(week * 7, skip, answers)},
        "adherence_events": [{"date": (T0 + timedelta(days=15)).date(), "kind": "confirmed_missed_partial"}],
        "ae": {"severity": "moderate", "urgent_flag": False, "persists": True, "worsening": False, "days_ago": 17, "details": {"symptom": "сонливость", "by": "patient", "note": "мешает работе, сохраняется со 2-й недели"}},
        "goal": {"text": "Вернуться к работе без постоянной усталости и тревоги", "by": "doctor"},
    }


# Ответы анкеты, которые не используются правилами (полнота анкеты и карточки врача).
INTAKE_DISPLAY = {
    "S1": {"q1": ["o3", "o4", "o9", "o11"], "q3": ["o1", "o2", "o3", "o5"], "q9": ["o1"], "q10": [], "q11": "o2", "q15": "o4",
           "q17": ["o4"], "q18": ["o7"], "q19": ["o4"], "q20": "o1", "q6a": "o1"},
    "S2": {"q1": ["o3", "o4", "o9"], "q3": ["o1", "o3", "o5"], "q9": ["o1"], "q10": [{"name": "амлодипин", "dose": "5 мг/сут"}],
           "q11": {"choice": "o1", "text": "хроническая болезнь почек"}, "q15": "o5", "q17": ["o4"], "q18": ["o7"], "q19": ["o4"], "q20": "o1",
           "q10a": {"Безрецептурные средства и биологически активные добавки": "магний курсами", "Известные лекарственные аллергии": "не знаю о таких"}},
    "S3": {"q1": ["o3", "o4", "o8", "o9"], "q3": ["o1", "o2", "o3", "o5"], "q9": ["o3"], "q10": [], "q11": "o2", "q15": "o4",
           "q17": ["o4"], "q18": ["o7"], "q19": ["o4"], "q20": "o1",
           "q7a": {"когда": "в 2019 и 2022 годах", "сколько длился": "около трёх месяцев", "полное восстановление между эпизодами": "да", "длительность улучшения": "около двух лет"},
           "q9a": {"что помогало": "психотерапия, регулярный сон", "причина завершения или изменения": "курс завершён по плану"}},
    "S4": {"q1": ["o3", "o4", "o9", "o11"], "q3": ["o1", "o2", "o4", "o5"], "q9": ["o1"], "q10": [], "q11": "o2", "q15": "o5",
           "q17": ["o4"], "q18": ["o7"], "q19": ["o4"], "q20": "o3", "q6a": {"choice": "o1", "text": "трудно сосредоточиться на работе"}},
    "S5": {"q1": ["o1", "o3", "o4", "o9", "o12"], "q3": ["o1", "o2", "o3"], "q9": ["o2", "o4"], "q10": [], "q11": "o2", "q15": "o4",
           "q17": ["o4"], "q18": ["o7"], "q19": ["o4"], "q20": "o1",
           "q9a": {"что помогало": "консультации психотерапевта", "что не помогло": "препарат, названия не помню", "причина завершения или изменения": "прекратила приём из-за сонливости"}},
}

# Повторные приёмы: (через сколько дней, время, цель визита)
VISITS = {
    "S1": (2, "10:30", "обсудить анкету, шкалы и решение по терапии"),
    "S2": (5, "12:00", "выбор тактики с учётом функции почек"),
    "S3": (12, "09:30", "контроль эффективности и переносимости"),
    "S4": (1, "15:00", "оценка переносимости: сонливость"),
}

# Анкеты, которые врач уже просмотрел (S1 — первичное обращение: анкета только что заполнена)
INTAKE_REVIEWED = {"S2", "S3", "S4", "S5"}



# ---- пациенты на лечении, подтверждённые психиатром (группа «Подтверждённые психиатром / на лечении») ----
# У каждого свой диагноз в пределах показаний Авиандра: S6 — F41.1 (ГТР), S7 — F41.9 (тревожное расстройство неуточнённое),
# S8 — F43.9 (реакция на тяжёлый стресс). Для F41.9/F43.9 соответствие второму показанию подтверждает врач (second_indication_confirmed).
# Других препаратов нет; Авиандр назначен штатным путём: предложение системы → подтверждение врача.

CONFIRMED_INTAKE_DISPLAY = {
    "S6": {"q1": ["o3", "o4", "o9"], "q3": ["o1", "o2", "o3", "o5"], "q9": ["o2"], "q10": [], "q11": "o2", "q15": "o4",
           "q17": ["o4"], "q18": ["o7"], "q19": ["o4"], "q20": "o1",
           "q7a": {"когда": "в 2021 году", "сколько длился": "около четырёх месяцев", "полное восстановление между эпизодами": "да"}},
    "S7": {"q1": ["o3", "o8", "o9"], "q3": ["o3", "o4", "o5"], "q9": ["o1"], "q10": [], "q11": "o2", "q15": "o5",
           "q17": ["o4"], "q18": ["o7"], "q19": ["o4"], "q20": "o1"},
    "S8": {"q1": ["o3", "o8", "o9", "o11"], "q3": ["o2", "o3", "o4"], "q9": ["o1"], "q10": [], "q11": "o2", "q15": "o4",
           "q17": ["o4"], "q18": ["o7"], "q19": ["o4"], "q20": "o1"},
}
INTAKE_DISPLAY.update(CONFIRMED_INTAKE_DISPLAY)


def treated(cfg, week, sex, age, dx, phq, gad, goal, intake=None, symptoms=None, sym_weeks=30, fields=None, ae=None):
    """Лечение Авиандром с недели 0 (диагноз dx в пределах показаний); phq/gad — {неделя: балл}."""
    weeks = sorted(phq)
    runs = [run(cfg, "phq9", w, fill(cfg, "phq9", phq[w])) for w in weeks if w <= week] + [run(cfg, "gad7", w, fill(cfg, "gad7", gad[w])) for w in weeks if w <= week]
    def answers(d):
        k = d / max(1, week * 7)
        return {"c1": round(6 - 3 * k), "c2": round(7 - 4 * k), "c3": "удовлетворительно" if k < .5 else "хорошо", "c4": "всё принято",
                "c5": "нет", "c6": "нет"}
    st = {
        "now": T0 + timedelta(weeks=week),
        "profile": {"sex": sex, "age": age, "fields": dict(FULL_NO, dx_icd10=dx, egfr_ml_min=90, **(fields or {}))},
        "intake": dict(INTAKE_GAD, **(intake or {})),
        "scale_runs": runs,
        "meds": {"items": [dict(AVIANDR)], "confirmed_by_doctor": True},
        "therapy": {"started_on": T0.date()},
        "symptoms": {n: {"present": "yes", "duration_weeks": sym_weeks} for n in (symptoms or ["мышечное напряжение или боли", "трудности с засыпанием и прерывистый сон"])},
        "checkin": {"enabled_on": T0.date(), "entries": _ck_entries(week * 7, lambda d: d % 6 == 5, answers)},
        "adherence_events": [],
        "goal": {"text": goal, "by": "patient"},
    }
    if ae:
        st["ae"] = ae
    return st


SECOND_INDICATION = {"second_indication_confirmed": "yes"}  # врач подтвердил: тревожное состояние со стрессовой реакцией / нарушением адаптации


def s6(cfg, week=8):
    """S6: генерализованное тревожное расстройство (F41.1), один прежний эпизод с полным восстановлением; хорошая динамика."""
    return treated(cfg, week, "ж", 35, "F41.1", {0: 9, 2: 7, 4: 5, 6: 4, 8: 3}, {0: 15, 2: 12, 4: 9, 6: 7, 8: 6}, "Вернуться к пробежкам по утрам",
                   {"q7": "o2"}, ["мышечное напряжение или боли", "трудности с засыпанием и прерывистый сон", "сердцебиение", "потливость"], 34)


def s7(cfg, week=6):
    """S7: тревожное расстройство неуточнённое (F41.9): тревога несколько месяцев, критериев ГТР по длительности нет; головокружение в первые дни прошло."""
    return treated(cfg, week, "м", 52, "F41.9", {0: 8, 2: 7, 4: 5, 6: 4}, {0: 14, 2: 11, 4: 9, 6: 7}, "Спокойно проводить совещания на работе",
                   {"q2": "o3"}, ["мышечное напряжение или боли", "трудности с засыпанием и прерывистый сон"], 16, SECOND_INDICATION,
                   ae={"severity": "mild", "urgent_flag": False, "persists": False, "worsening": False, "days_ago": 38,
                       "details": {"symptom": "головокружение", "by": "patient", "note": "в первые дни приёма, прошло"}})


def s8(cfg, week=4):
    """S8: реакция на тяжёлый стресс (F43.9) после внезапного увольнения и переезда, нарушение адаптации средней степени; ответ медленный."""
    return treated(cfg, week, "ж", 29, "F43.9", {0: 11, 2: 10, 4: 9}, {0: 16, 2: 15, 4: 13}, "Спокойно пройти собеседования на новую работу",
                   {"q2": "o2"}, ["трудности с засыпанием и прерывистый сон", "мышечное напряжение или боли"], 10, SECOND_INDICATION)


# Подтверждение психиатром: основание направления, через сколько дней после начала лечения направлен и подтверждён, заключение
PSY_CONFIRMED = {
    "S6": ("D-04", 20, 22, "Диагноз F41.1 подтверждён: генерализованное тревожное расстройство, один прежний эпизод с полным восстановлением. "
                           "Продолжить терапию, PHQ-9 и GAD-7 раз в две недели."),
    "S7": ("D-06", 10, 12, "Диагноз F41.9 подтверждён: тревожное расстройство неуточнённое, критериев ГТР по длительности нет. "
                           "Головокружение в первые дни прошло, терапию продолжить без изменений."),
    "S8": ("D-01", 21, 23, "Диагноз F43.9 подтверждён: реакция на тяжёлый стресс (внезапное увольнение и переезд), нарушение адаптации средней степени. "
                           "Ответ на лечение медленный: повторная консультация через 2 недели, при отсутствии динамики — пересмотр тактики."),
}
