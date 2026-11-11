from PIL import Image

from app.vision.ocr import normalize_result, ocr_image


def _box(left, top, right, bottom):
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


def test_normalize_result_maps_pixels_to_unit_square():
    raw = [(_box(10, 20, 50, 40), "越战越硬", 0.93)]
    items = normalize_result(raw, width=100, height=200)
    assert items[0].text == "越战越硬"
    assert items[0].confidence == 0.93
    assert items[0].bounds == (0.1, 0.1, 0.5, 0.2)


def test_ocr_image_crops_region_and_keeps_full_image_coordinates():
    seen = {}

    def fake_engine(array):
        seen["size"] = (array.shape[1], array.shape[0])
        return ([(_box(5, 5, 25, 15), "冰刺", 0.88)], None)

    image = Image.new("RGB", (100, 200), (0, 0, 0))
    items = ocr_image(image, engine=fake_engine, region=(0.5, 0.5, 1.0, 1.0))
    assert seen["size"] == (50, 100)
    assert items[0].bounds == (0.55, 0.525, 0.75, 0.575)


def test_ocr_image_empty_result_returns_empty_list():
    image = Image.new("RGB", (10, 10))
    assert ocr_image(image, engine=lambda _: (None, None)) == []
