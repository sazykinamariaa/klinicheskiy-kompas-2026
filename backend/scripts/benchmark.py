"""Замеры технических метрик: время ответа, время доставки красного алерта, нагрузка, резервная копия и восстановление.

Запуск:  python scripts/benchmark.py            (поднимает сервер на временной БД, пишет docs/benchmarks.json и docs/benchmarks.md)
Числа зависят от машины; в отчёт попадают как измеренные на этой машине, а не как гарантия.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
PORT = int(os.environ.get("KK_BENCH_PORT", "8765"))
BASE = "http://127.0.0.1:%d" % PORT


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def stats_ms(xs):
    return {"n": len(xs), "p50_ms": round(pct(xs, 50) * 1000, 1), "p95_ms": round(pct(xs, 95) * 1000, 1), "max_ms": round(max(xs) * 1000, 1),
            "mean_ms": round(statistics.mean(xs) * 1000, 1)}


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="kkbench_"))
    cfg = tmp / "config"
    shutil.copytree(ROOT / "config", cfg)
    env = dict(os.environ, KK_DATA_DIR=str(tmp), KK_CONFIG_DIR=str(cfg), KK_SEED="1", KK_WORKER="1", KK_WORKER_INTERVAL="0.5")
    srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"], cwd=BACKEND, env=env)
    out = {"machine": {"python": sys.version.split()[0], "cpus": os.cpu_count()}, "db": "SQLite (WAL), один процесс uvicorn"}
    try:
        for _ in range(120):
            try:
                if httpx.get(BASE + "/api/health", timeout=1).status_code == 200:
                    break
            except Exception:
                time.sleep(0.25)
        cl = httpx.Client(base_url=BASE, timeout=30)

        def login(u):
            r = cl.post("/api/auth/login", json={"login": u, "password": "Kompas2026x"})
            return {"Authorization": "Bearer " + r.json()["token"]}

        d = login("doctor1")
        pats = cl.get("/api/doctor/patients", headers=d).json()
        # 1. время ответа
        lat = {"card": [], "patients_list": [], "inbox": []}
        for i in range(60):
            p = pats[i % len(pats)]["id"]
            for key, url in (("card", f"/api/doctor/patients/{p}/card"), ("patients_list", "/api/doctor/patients"), ("inbox", "/api/doctor/inbox")):
                t = time.perf_counter()
                r = cl.get(url, headers=d)
                assert r.status_code == 200
                lat[key].append(time.perf_counter() - t)
        out["response_time"] = {k: stats_ms(v) for k, v in lat.items()}
        out["response_time"]["note"] = "карточка включает полную оценку правил и проверку препарата"

        # 2. доставка красного алерта: от ответа пациента до записи «доставлено» в журнале
        samples = []
        db = tmp / "kk.sqlite3"
        for i in range(8):
            cr = cl.post("/api/doctor/patients", headers=d, json={"code": "B%d" % i, "sex": "м", "birth_date": "1988-01-01"}).json()
            acc = cl.post("/api/public/invitation/%s/accept" % cr["invite_code"], json={"consent": True, "login": "bench%d" % i, "password": "benchpass123"}).json()
            h = {"Authorization": "Bearer " + acc["token"]}
            _r = cl.get("/api/patient/intake", headers=h)
            assert _r.status_code == 200, (acc, _r.text)
            qs = _r.json()["questions"]
            q12 = next(q for q in qs if q["id"] == "q12")
            cur = next(o["id"] for o in q12["options"] if "присутствуют сейчас" in o["label"])
            cl.put("/api/patient/intake/q12", headers=h, json={"answer": cur})
            sf = {"sf%d" % k: "no" for k in range(1, 10)}
            sf.update(sf1="yes", sf2="yes", sf4="yes", sf5="yes", sf8="no")
            t0 = time.perf_counter()
            r = cl.post("/api/patient/safety-followup", headers=h, json={"answers": sf})
            assert r.status_code == 200
            while time.perf_counter() - t0 < 30:
                con = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=5)
                n = con.execute("select count(*) from notification_log nl join alerts a on a.id = nl.alert_id "
                                "where a.patient_id=? and a.level='red' and nl.status='delivered'", (cr["patient_id"],)).fetchone()[0]
                con.close()
                if n:
                    samples.append(time.perf_counter() - t0)
                    break
                time.sleep(0.05)
        out["red_alert_delivery"] = stats_ms(samples) if samples else {"error": "не доставлено за 30 с"}
        out["red_alert_delivery"]["note"] = "от ответа пациента до первой доставленной записи; в демо каналы push/sms — адаптеры-заглушки, поэтому время не включает сеть оператора"

        # 3. нагрузка
        users, per = 30, 15
        errs, times = [], []
        lock = threading.Lock()

        def worker(k):
            c = httpx.Client(base_url=BASE, timeout=60)
            hh = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"login": "doctor1", "password": "Kompas2026x"}).json()["token"]}
            for j in range(per):
                p = pats[(k + j) % len(pats)]["id"]
                t = time.perf_counter()
                r = c.get(f"/api/doctor/patients/{p}/card", headers=hh)
                dt = time.perf_counter() - t
                with lock:
                    times.append(dt)
                    if r.status_code != 200:
                        errs.append(r.status_code)

        t0 = time.perf_counter()
        ths = [threading.Thread(target=worker, args=(k,)) for k in range(users)]
        [t.start() for t in ths]
        [t.join() for t in ths]
        wall = time.perf_counter() - t0
        out["load"] = dict(stats_ms(times), concurrent_users=users, requests=len(times), errors=len(errs), wall_s=round(wall, 1),
                           throughput_rps=round(len(times) / wall, 1))

        # 4. резервная копия и восстановление
        t0 = time.perf_counter()
        bak = tmp / "backup.sqlite3"
        src = sqlite3.connect(str(db))
        dst = sqlite3.connect(str(bak))
        src.backup(dst)
        dst.close()
        backup_s = time.perf_counter() - t0
        counts_src = {t: src.execute("select count(*) from %s" % t).fetchone()[0] for t in ("users", "patients", "alerts", "scale_runs", "audit_log", "proposals")}
        src.close()
        t0 = time.perf_counter()
        restored = tmp / "restored.sqlite3"
        shutil.copy2(bak, restored)
        con = sqlite3.connect(str(restored))
        ok = con.execute("pragma integrity_check").fetchone()[0] == "ok"
        counts_dst = {t: con.execute("select count(*) from %s" % t).fetchone()[0] for t in counts_src}
        con.close()
        restore_s = time.perf_counter() - t0
        out["backup_restore"] = {"backup_s": round(backup_s, 3), "restore_and_check_s": round(restore_s, 3), "integrity_ok": ok,
                                 "row_counts_match": all(counts_dst[k] == counts_src[k] for k in counts_src),
                                 "counts": counts_dst,
                                 "RPO": "равен интервалу резервного копирования; при копии каждые 15 минут (cron + sqlite .backup / pg_dump) потеря не более 15 минут данных",
                                 "RTO": "измеренное время восстановления на демо-объёме см. restore_and_check_s; на боевом объёме замерить отдельно",
                                 "note": "в демо журнал WAL уменьшает потерю до последней зафиксированной транзакции при сбое процесса"}
    finally:
        srv.terminate()
        try:
            srv.wait(10)
        except Exception:
            srv.kill()
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "benchmarks.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# Замеры технических метрик", "", "Измерено скриптом `backend/scripts/benchmark.py` на машине: Python %s, %s CPU. БД: %s." % (out["machine"]["python"], out["machine"]["cpus"], out["db"]), ""]
    rt = out["response_time"]
    md += ["## Время ответа (последовательные запросы)", "", "| запрос | n | p50, мс | p95, мс | max, мс |", "|---|---|---|---|---|"]
    for k in ("card", "patients_list", "inbox"):
        s = rt[k]
        md.append("| %s | %d | %s | %s | %s |" % (k, s["n"], s["p50_ms"], s["p95_ms"], s["max_ms"]))
    md += ["", rt["note"], "", "## Доставка красного алерта", ""]
    ra = out["red_alert_delivery"]
    md.append(json.dumps(ra, ensure_ascii=False))
    md += ["", "## Нагрузка", "", json.dumps(out["load"], ensure_ascii=False), "", "## Резервная копия и восстановление", "", json.dumps(out["backup_restore"], ensure_ascii=False, indent=2), ""]
    (ROOT / "docs" / "benchmarks.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
