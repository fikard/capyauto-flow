import pytest

from app.core.geometry import clamp, normalize_to_device
from app.errors import OutOfBounds


def test_half_maps_to_center():
    assert normalize_to_device(0.5, 0.5, 1080, 2340) == (540, 1170)


def test_edges():
    assert normalize_to_device(0.0, 0.0, 1080, 2340) == (0, 0)
    assert normalize_to_device(1.0, 1.0, 1080, 2340) == (1079, 2339)


@pytest.mark.parametrize("x,y", [(-0.01, 0.5), (0.5, 1.01), (1.2, 0.3)])
def test_out_of_bounds_raises(x, y):
    with pytest.raises(OutOfBounds):
        normalize_to_device(x, y, 1080, 2340)


def test_clamp():
    assert clamp(-5, 0, 100) == 0
    assert clamp(105, 0, 100) == 100
    assert clamp(50, 0, 100) == 50
