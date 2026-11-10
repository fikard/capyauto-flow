import struct

import pytest

from app.device.base import keycode_for
from app.device.scrcpy_session import (
    ACTION_DOWN,
    ACTION_UP,
    build_key,
    build_touch,
    parse_device_meta,
    parse_packet_header,
)
from app.errors import ScrcpyUnavailable, UnknownKey


def _meta_blob(name: str, codec_id: int, width: int, height: int) -> bytes:
    raw = name.encode("utf-8")
    assert len(raw) <= 64
    return raw.ljust(64, b"\x00") + struct.pack(">III", codec_id, width, height)


def test_parse_device_meta_h264():
    meta = parse_device_meta(_meta_blob("SM-G9730", 0x68323634, 1080, 2340))
    assert meta.device_name == "SM-G9730"
    assert meta.codec == "h264"
    assert (meta.width, meta.height) == (1080, 2340)


def test_parse_device_meta_rejects_unknown_codec():
    with pytest.raises(ScrcpyUnavailable):
        parse_device_meta(_meta_blob("x", 0x12345678, 1080, 2340))


def test_parse_packet_header_flags():
    header = struct.pack(">QI", (1 << 63) | (1 << 62) | 4242, 512)
    pts, is_config, is_key, size = parse_packet_header(header)
    assert (pts, is_config, is_key, size) == (4242, True, True, 512)


def test_build_touch_layout():
    msg = build_touch(ACTION_DOWN, 0, 540, 1200, 1080, 2400)
    assert len(msg) == 32
    msg_type, action, pointer, x, y, width, height, pressure, action_button, buttons = struct.unpack(
        ">BBQiiHHHII", msg
    )
    assert msg_type == 2
    assert action == ACTION_DOWN
    assert (pointer, x, y, width, height) == (0, 540, 1200, 1080, 2400)
    assert pressure == 0xFFFF
    assert (action_button, buttons) == (0, 0)
    assert struct.unpack(">BBQiiHHHII", build_touch(ACTION_UP, 0, 540, 1200, 1080, 2400))[7] == 0


def test_build_key_layout():
    msg = build_key(0, 4)
    assert len(msg) == 14
    assert struct.unpack(">BBIII", msg) == (0, 0, 4, 0, 0)


def test_keycode_mapping():
    assert keycode_for("back") == 4
    assert keycode_for("home") == 3
    assert keycode_for("app_switch") == 187
    with pytest.raises(UnknownKey):
        keycode_for("nope")
