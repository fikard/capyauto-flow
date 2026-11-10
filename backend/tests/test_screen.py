import io
import time

from PIL import Image

from app.device.screen import ScreencapPoller


class FakeAdb:
    def __init__(self) -> None:
        self.calls = 0

    def exec_out(self, serial: str, *args) -> bytes:
        self.calls += 1
        image = Image.new("RGB", (108, 240), (10, 20, 30))
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()


def test_poller_produces_jpeg_frames():
    adb = FakeAdb()
    poller = ScreencapPoller(adb, "SERIAL", 108, 240, fps=10, jpeg_quality=70, display_width=720)
    poller.start()
    time.sleep(0.35)
    poller.stop()

    frame = poller.latest()
    assert frame is not None
    assert frame.jpeg[:2] == b"\xff\xd8"
    assert frame.width == 108
    assert adb.calls >= 2
