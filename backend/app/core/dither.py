from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass
from typing import Callable

from app.core.geometry import clamp, js_round, normalize_to_device

Rng = Callable[[], float]


def random_gaussian(mean: float, stdev: float, rng: Rng = random.random) -> float:
    """Box-Muller 变换，与 TS randomGaussian 逐式对齐。"""
    u1 = rng()
    u2 = rng()
    while u1 <= sys.float_info.epsilon:
        u1 = rng()
    rand_std_normal = math.sqrt(-2.0 * math.log(u1)) * math.sin(2.0 * math.pi * u2)
    return mean + rand_std_normal * stdev


@dataclass(frozen=True)
class ClickPlan:
    target_x: int
    target_y: int
    real_x: int
    real_y: int
    press_ms: int


def gaussian_click(
    x_norm: float,
    y_norm: float,
    width: int,
    height: int,
    sigma: float = 6.0,
    press_mean: float = 80.0,
    press_stdev: float = 20.0,
    rng: Rng = random.random,
) -> ClickPlan:
    target_x, target_y = normalize_to_device(x_norm, y_norm, width, height)
    real_x = int(clamp(js_round(random_gaussian(target_x, sigma, rng)), 0, width - 1))
    real_y = int(clamp(js_round(random_gaussian(target_y, sigma, rng)), 0, height - 1))
    press_ms = max(40, js_round(random_gaussian(press_mean, press_stdev, rng)))
    return ClickPlan(
        target_x=target_x,
        target_y=target_y,
        real_x=real_x,
        real_y=real_y,
        press_ms=press_ms,
    )


def bezier_points(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    steps: int = 10,
    offset: float = 40.0,
    rng: Rng = random.random,
) -> list[tuple[int, int]]:
    """二次贝塞尔轨迹，控制点带有机偏移，与 TS generateBezierPoints 对齐。"""
    cx = (x1 + x2) / 2 + (rng() * offset * 2 - offset)
    cy = (y1 + y2) / 2 + (rng() * offset * 2 - offset)
    points: list[tuple[int, int]] = []
    for i in range(steps + 1):
        t = i / steps
        px = js_round((1 - t) * (1 - t) * x1 + 2 * (1 - t) * t * cx + t * t * x2)
        py = js_round((1 - t) * (1 - t) * y1 + 2 * (1 - t) * t * cy + t * t * y2)
        points.append((px, py))
    return points
