import random
import statistics

from app.core.dither import bezier_points, gaussian_click, random_gaussian


def test_gaussian_zero_stdev_is_deterministic():
    plan = gaussian_click(0.5, 0.5, 1080, 2340, sigma=0.0, press_mean=80, press_stdev=0.0)
    assert (plan.target_x, plan.target_y) == (540, 1170)
    assert (plan.real_x, plan.real_y) == (540, 1170)
    assert plan.press_ms == 80


def test_gaussian_statistics():
    rng = random.Random(42)
    samples = [random_gaussian(100.0, 6.0, rng.random) for _ in range(5000)]
    assert abs(statistics.fmean(samples) - 100.0) < 0.6
    assert abs(statistics.pstdev(samples) - 6.0) < 0.4


def test_click_stays_in_bounds():
    rng = random.Random(7)
    for _ in range(500):
        plan = gaussian_click(0.0, 0.0, 1080, 2340, sigma=30.0, rng=rng.random)
        assert 0 <= plan.real_x <= 1079
        assert 0 <= plan.real_y <= 2339


def test_press_duration_floor():
    rng = random.Random(1)
    for _ in range(200):
        plan = gaussian_click(0.5, 0.5, 1080, 2340, press_mean=40, press_stdev=50, rng=rng.random)
        assert plan.press_ms >= 40


def test_bezier_endpoints_and_length():
    rng = random.Random(3)
    points = bezier_points(100, 200, 900, 1600, steps=10, rng=rng.random)
    assert len(points) == 11
    assert points[0] == (100, 200)
    assert points[-1] == (900, 1600)
    xs = [p[0] for p in points]
    assert all(isinstance(v, int) for v in xs)
