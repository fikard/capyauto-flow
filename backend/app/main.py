from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import config
from app.api import devices, health
from app.errors import ApiError

app = FastAPI(title="CapyAuto Flow Device Bridge", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{config.settings.frontend_port}",
        f"http://127.0.0.1:{config.settings.frontend_port}",
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
