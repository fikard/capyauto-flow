from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.api import (
    accounts,
    app_control,
    automation,
    control,
    devices,
    health,
    mirror,
    network,
    verify_run,
    vision,
)
from app.errors import ApiError

app = FastAPI(title="CapyAuto Flow Device Bridge", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{config.settings.frontend_port}",
        f"http://127.0.0.1:{config.settings.frontend_port}",
        "http://frontend.capyauto-flow.test",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ApiError)
async def handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


app.include_router(health.router)
app.include_router(devices.router)
app.include_router(mirror.router)
app.include_router(control.router)
app.include_router(app_control.router)
app.include_router(network.router)
app.include_router(vision.router)
app.include_router(automation.router)
app.include_router(accounts.router)
app.include_router(verify_run.router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/debug/mirror", include_in_schema=False)
async def debug_mirror() -> FileResponse:
    return FileResponse(STATIC_DIR / "debug_mirror.html")
