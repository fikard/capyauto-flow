from __future__ import annotations

import math

from app.errors import OutOfBounds


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def js_round(value: float) -> int:
    """与 JS Math.round 一致：.5 向正无穷方向进位（Python round 是银行家舍入）。"""
    return math.floor(value + 0.5)


def normalize_to_device(x: float, y: float, width: int, height: int) -> tuple[int, int]:
    """归一化坐标（0–1）→ 设备像素坐标。

    越界直接抛 OutOfBounds，不做静默 clamp（规格第 9 节）。
    映射规则：舍入(x * 边长)，再 clamp 到 [0, 边长-1]。
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"设备分辨率非法: {width}x{height}")
    if not (0.0 <= x <= 1.0) or not (0.0 <= y <= 1.0):
        raise OutOfBounds(f"归一化坐标超出 0–1 范围: x={x}, y={y}", detail={"x": x, "y": y})
    px = int(clamp(js_round(x * width), 0, width - 1))
    py = int(clamp(js_round(y * height), 0, height - 1))
    return px, py
