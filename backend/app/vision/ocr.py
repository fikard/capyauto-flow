from __future__ import annotations

import importlib.util
import io
import json
import os
import threading
from dataclasses import dataclass

from PIL import Image

_engine = None
_engine_lock = threading.Lock()

# 超过 6 线程在 CPU 推理上会因线程争用反而变慢（实测 12 线程比 6 慢 40% 以上）
_MAX_INFERENCE_THREADS = 6

# 知识库：OCR UI 属性词典（中文术语 → 英文字段键）
# 路径兼容两种启动方式：
#   python -m app（backend/ 目录启动，__file__=backend/app/vision/ocr.py → ../.. 到 backend，再 .. 到仓库根）
#   pytest backend/tests/（repo 根启动，__file__=repo/backend/app/vision/ocr.py → 三次 .. 到仓库根）
_HERE = os.path.dirname(os.path.abspath(__file__))
_CANDIDATE_ROOTS = [
    os.path.abspath(os.path.join(_HERE, "..", "..", "..", "capy-knowledge")),
    os.path.abspath(os.path.join(_HERE, "..", "..", "capy-knowledge")),
]
_KNOWLEDGE_ROOT = os.environ.get(
    "CAPYAUTO_KNOWLEDGE_DIR",
    next((p for p in _CANDIDATE_ROOTS if os.path.isfile(os.path.join(p, "ocr_attr_index.json"))), _CANDIDATE_ROOTS[0]),
)

# kind × rarity 识别（中文短语）
_KIND_RARITY_HINTS = [
    # kind 优先级：核心 → 守护 → 图腾（与游戏实际上场规则一致）
    ("核心", "神话", "核心"), ("核心", "传说", "核心"),
    ("守护", "神话", "守护"), ("守护", "传说", "守护"),
    ("图腾", "神话", "图腾"), ("图腾", "传说", "图腾"),
]
_RARITY_KEYWORDS = {
    "神话": "神话", "传说": "传说", "史诗": "史诗", "稀有": "稀有",
    "超越": "超越", "至宝": "至宝", "不朽": "不朽", "绝世": "绝世",
}
_KIND_KEYWORDS = {"核心": "核心", "守护": "守护", "图腾": "图腾"}


def _load_json_cached(path: str):
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


_ui_attr_index = _load_json_cached(os.path.join(_KNOWLEDGE_ROOT, "ocr_attr_index.json"))


@dataclass(frozen=True)
class OcrItem:
    text: str
    confidence: float
    bounds: tuple[float, float, float, float]
    # 知识库标注：kind/rarity/lexicon_ref 全为可选，未命中时为 None
    kind: str | None = None
    rarity: str | None = None
    lexicon_ref: str | None = None


def _annotate_item(text: str) -> tuple[str | None, str | None, str | None]:
    """对一条 OCR 文本做知识库后处理，返回 (kind, rarity, lexicon_ref)"""
    kind = rarity = lexicon_ref = None

    for kw, val in _RARITY_KEYWORDS.items():
        if kw in text:
            rarity = val
            break

    for kw, val in _KIND_KEYWORDS.items():
        if kw in text:
            kind = val
            break

    # ui_attr_index：中文术语 → 英文字段键。首个命中的键即 lexicon_ref
    if _ui_attr_index:
        for cn_term, en_key in _ui_attr_index.items():
            if cn_term and cn_term in text:
                lexicon_ref = en_key
                break
    return kind, rarity, lexicon_ref


def _annotate_items(items: list[OcrItem]) -> list[OcrItem]:
    if not _ui_attr_index:  # 知识库没加载就跳过，保持向后兼容
        return items
    annotated: list[OcrItem] = []
    for item in items:
        kind, rarity, lexicon_ref = _annotate_item(item.text)
        if kind or rarity or lexicon_ref:
            annotated.append(
                OcrItem(
                    text=item.text,
                    confidence=item.confidence,
                    bounds=item.bounds,
                    kind=kind,
                    rarity=rarity,
                    lexicon_ref=lexicon_ref,
                )
            )
        else:
            annotated.append(item)
    return annotated


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
    return _annotate_items(items)


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
    items = [
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
    return items


def ocr_png(png: bytes, region=None) -> list[OcrItem]:
    with Image.open(io.BytesIO(png)) as image:
        return ocr_image(image, region=region)
