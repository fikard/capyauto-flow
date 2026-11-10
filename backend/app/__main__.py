from __future__ import annotations

import socket

import uvicorn

from app.config import settings


def _invalid_port(port: object) -> SystemExit:
    return SystemExit(
        f"[capyauto] 端口 {port!r} 非法，必须是 1–65535 之间的整数，"
        f"用 CAPYAUTO_BACKEND_PORT 指定其他端口后重试"
    )


def port_busy(port: int) -> bool:
    if not 1 <= port <= 65535:
        raise _invalid_port(port)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OverflowError as exc:
            raise _invalid_port(port) from exc
        except OSError:
            return True
    return False


def main() -> None:
    port = settings.backend_port
    if not 1 <= port <= 65535:
        raise _invalid_port(port)
    if port_busy(port):
        raise SystemExit(
            f"[capyauto] 端口 {port} 已被占用，"
            f"用 CAPYAUTO_BACKEND_PORT 指定其他端口后重试"
        )
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
