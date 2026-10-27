"""Клинический компас: приложение FastAPI. Запуск: uvicorn app.main:app  (см. README.md)."""
from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db as DB, deps, queue as Q

log = logging.getLogger("kk")
WORKER_INTERVAL = float(os.environ.get("KK_WORKER_INTERVAL", "5"))
_stop = threading.Event()


def _worker() -> None:
    """Фоновый обработчик очереди: доставка уведомлений, повторы, эскалации. Устойчив к исключениям."""
    while not _stop.is_set():
        try:
            with DB.session_scope() as s:
                Q.process_due(s, deps.get_cfg())
        except Exception:  # noqa: BLE001  — воркер не должен умирать
            log.exception("сбой обработчика очереди")
        _stop.wait(WORKER_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    DB.init()
    cfg = deps.get_cfg()
    if os.environ.get("KK_SEED", "1") == "1":  # начальные данные: недостающие пользователи и пациенты S1–S8
        from .seed import seed_initial
        with DB.session_scope() as s:
            seed_initial(s, cfg)
    t = None
    if os.environ.get("KK_WORKER", "1") == "1":
        _stop.clear()
        t = threading.Thread(target=_worker, name="kk-queue", daemon=True)
        t.start()
    yield
    _stop.set()
    if t:
        t.join(timeout=5)


def create_app() -> FastAPI:
    from .routers import admin, alerts, auth, demo_invite, devauth, psy_notes, doctor, doctor_extra, doctor_sections, duty, info, patient, patient_extra, psy_sections, psychiatrist
    app = FastAPI(title="Клинический компас", version="0.1.0", lifespan=lifespan,
                  description="Инструмент поддержки принятия клинических решений: все предложения системы подтверждает врач. "
                              "Диагноз устанавливает врач. Система скорую помощь не вызывает.")
    for r in (auth.router, patient.public, patient.router, doctor.router, doctor_extra.router, alerts.router, psychiatrist.router,
              admin.router, info.router, devauth.public, devauth.auth, devauth.dev, psy_notes.router, patient_extra.router, doctor_sections.router, duty.router, psy_sections.router, demo_invite.public, demo_invite.pages):
        app.include_router(r)
    # страница «Клинический компас.html», открытая как файл (Origin: null), обращается к этому серверу; доступ к данным — только по токену
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware, allow_origins=["null"], allow_methods=["*"], allow_headers=["Authorization", "Content-Type"])

    @app.get("/api/health", tags=["Служебное"], summary="Проверка работоспособности")
    def health():
        return {"status": "ok"}

    @app.exception_handler(Exception)
    async def _unhandled(request, exc):  # не отдаём внутренности наружу
        log.exception("необработанная ошибка")
        return JSONResponse({"detail": "внутренняя ошибка"}, status_code=500)

    dist = Path(os.environ.get("KK_FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets") if (dist / "assets").is_dir() else None

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = dist / path
            if path and f.is_file() and dist in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html")
    return app


app = create_app()
