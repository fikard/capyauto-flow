from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter

from app.deps import get_adapter
from app.errors import OcrUnavailable
from app.schemas import OcrRequest
from app.vision.ocr import engine_available, engine_name, ocr_png

router = APIRouter(prefix="/api/vision", tags=["vision"])


@router.post("/ocr")
async def ocr(req: OcrRequest) -> dict:
    adapter = get_adapter()
    adapter.get_session(req.sessionId)
    if not engine_available():
        raise OcrUnavailable("未安装 OCR 引擎，请执行：pip install rapidocr-onnxruntime")
    png = await adapter.screenshot(req.sessionId)
    started = time.perf_counter()
    items = await asyncio.to_thread(ocr_png, png, req.region)
    took_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "tookMs": took_ms,
        "engine": engine_name(),
        "items": [
            {
                "text": item.text,
                "confidence": item.confidence,
                "bounds": {
                    "left": item.bounds[0],
                    "top": item.bounds[1],
                    "right": item.bounds[2],
                    "bottom": item.bounds[3],
                },
            }
            for item in items
        ],
    }
