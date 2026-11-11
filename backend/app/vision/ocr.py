from __future__ import annotations

import importlib.util
import io
import os
import threading
from dataclasses import dataclass

from PIL import Image

_engine = None
_engine_lock = threading.Lock()

# 超过 6 线程在 CPU 推理上会因线程争用反而变慢（实测 12 线程比 6 慢 40% 以上）
_MAX_INFERENCE_THREADS = 6


@dataclass(frozen=True)
class OcrItem:
    text: str
    confidence: float
    bounds: tuple[float, float, float, float]


def engine_available() -> bool:
    return importlib.util.find_spec("rapidocr_onnxruntime") is not None


def engine_name() -> str | None:
    return "rapidocr-onnxruntime" if engine_available() else None


def get_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR(
                # 游戏截图固定正向，关闭 180° 方向分类可省一次分类推理
                use_cls=False,
                intra_op_num_threads=min(os.cpu_count() or 4, _MAX_INFERENCE_THREADS),
            )
    return _engine


def normalize_result(raw, width: int, height: int) -> list[OcrItem]:
    items: list[OcrItem] = []
    for entry in raw or []:
        box, text, score = entry
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        items.append(
            OcrItem(
                text=str(text),
                confidence=float(score),
                bounds=(
                    min(xs) / width,
                    min(ys) / height,
                    max(xs) / width,
                    max(ys) / height,
                ),
            )
        )
    return items


def ocr_image(image: Image.Image, engine=None, region=None) -> list[OcrItem]:
    import numpy as np

    width, height = image.size
    offset_x = offset_y = 0
    if region is not None:
        left, top, right, bottom = region
        offset_x = int(round(max(0.0, left) * width))
        offset_y = int(round(max(0.0, top) * height))
        crop_right = int(round(min(1.0, right) * width))
        crop_bottom = int(round(min(1.0, bottom) * height))
        image = image.crop((offset_x, offset_y, crop_right, crop_bottom))
    array = np.array(image.convert("RGB"))
    result, _elapse = (engine or get_engine())(array)
    crop_width, crop_height = image.size
    return [
        OcrItem(
            text=item.text,
            confidence=item.confidence,
            bounds=(
                (item.bounds[0] * crop_width + offset_x) / width,
                (item.bounds[1] * crop_height + offset_y) / height,
                (item.bounds[2] * crop_width + offset_x) / width,
                (item.bounds[3] * crop_height + offset_y) / height,
            ),
        )
        for item in normalize_result(result, crop_width, crop_height)
    ]


def ocr_png(png: bytes, region=None) -> list[OcrItem]:
    with Image.open(io.BytesIO(png)) as image:
        return ocr_image(image, region=region)
