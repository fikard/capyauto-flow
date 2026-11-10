from __future__ import annotations

import socket
import struct
from dataclasses import dataclass

from app.errors import ScrcpyUnavailable

DEVICE_NAME_LEN = 64
META_LEN = 76
PACKET_HEADER_LEN = 12
MAX_PACKET_SIZE = 8 * 1024 * 1024

CODEC_IDS = {0x68323634: "h264", 0x68323635: "h265", 0x00617631: "av1"}

ACTION_DOWN, ACTION_UP, ACTION_MOVE = 0, 1, 2
MSG_INJECT_KEYCODE = 0
MSG_INJECT_TOUCH_EVENT = 2


def recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError(f"socket 提前关闭，仍缺 {remaining} 字节")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


@dataclass(frozen=True)
class VideoMeta:
    device_name: str
    codec: str
    width: int
    height: int


def parse_device_meta(blob: bytes) -> VideoMeta:
    """scrcpy >= 2.0 视频 socket 头：64 字节设备名 + 4 字节 codec + 4+4 宽高。"""
    if len(blob) != META_LEN:
        raise ScrcpyUnavailable(f"视频头长度应为 {META_LEN}，实际 {len(blob)}")
    name = blob[:DEVICE_NAME_LEN].split(b"\x00", 1)[0].decode("utf-8", "replace")
    codec_id, width, height = struct.unpack(">III", blob[DEVICE_NAME_LEN:])
    if codec_id not in CODEC_IDS:
        raise ScrcpyUnavailable(
            f"未知 codec id 0x{codec_id:08x}，需要 scrcpy >= 2.0 且 video_codec=h264"
        )
    if width <= 0 or height <= 0:
        raise ScrcpyUnavailable(f"视频尺寸非法: {width}x{height}")
    return VideoMeta(device_name=name, codec=CODEC_IDS[codec_id], width=width, height=height)


def parse_packet_header(header: bytes) -> tuple[int, bool, bool, int]:
    """12 字节包头：8 字节 pts+flags（bit63=配置帧，bit62=关键帧）+ 4 字节长度。"""
    if len(header) != PACKET_HEADER_LEN:
        raise ValueError(f"包头长度应为 {PACKET_HEADER_LEN}，实际 {len(header)}")
    pts_flags, size = struct.unpack(">QI", header)
    return pts_flags & 0x3FFF_FFFF_FFFF_FFFF, bool(pts_flags >> 63), bool((pts_flags >> 62) & 1), size


def build_touch(
    action: int,
    pointer_id: int,
    x: int,
    y: int,
    width: int,
    height: int,
    pressure: int = 0xFFFF,
    buttons: int = 0,
) -> bytes:
    pressure = 0 if action == ACTION_UP else pressure
    return struct.pack(
        ">BBQiiHHHII", MSG_INJECT_TOUCH_EVENT, action, pointer_id, x, y, width, height, pressure, 0, buttons
    )


def build_key(action: int, keycode: int, repeat: int = 0, meta_state: int = 0) -> bytes:
    return struct.pack(">BBIII", MSG_INJECT_KEYCODE, action, keycode, repeat, meta_state)
