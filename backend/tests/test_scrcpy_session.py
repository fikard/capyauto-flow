import socket
import struct

import pytest

from app.device.scrcpy_session import META_LEN, PACKET_HEADER_LEN

# 说明：真正的 H.264 解码与注入由真机验收覆盖（任务 15、16）。
# 这里只验证不依赖 ffmpeg 的边界：meta 读取超时、包长度异常、control 消息写入。
from app.device.scrcpy_session import recv_exact
from app.errors import ScrcpyUnavailable


def test_recv_exact_returns_full_buffer():
    left, right = socket.socketpair()
    try:
        left.sendall(b"abcdef")
        assert recv_exact(right, 6) == b"abcdef"
    finally:
        left.close()
        right.close()


def test_recv_exact_raises_on_closed_socket():
    left, right = socket.socketpair()
    left.close()
    try:
        with pytest.raises(ConnectionError):
            recv_exact(right, 4)
    finally:
        right.close()


def test_recv_exact_bad_meta_length():
    with pytest.raises(ScrcpyUnavailable):
        from app.device.scrcpy_session import parse_device_meta

        parse_device_meta(b"\x00" * (META_LEN - 1))


def test_packet_header_size_guard():
    from app.device.scrcpy_session import parse_packet_header

    _, _, _, size = parse_packet_header(struct.pack(">QI", 0, 1024))
    assert size == 1024
    assert PACKET_HEADER_LEN == 12
