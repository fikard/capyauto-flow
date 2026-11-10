from __future__ import annotations

import socket

import uvicorn

from app.config import settings


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def main() -> None:
    if port_busy(settings.backend_port):
        raise SystemExit(
            f"[capyauto] 端口 {settings.backend_port} 已被占用，"
            f"用 CAPYAUTO_BACKEND_PORT 指定其他端口后重试"
        )
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.backend_port, log_level="info")


if __name__ == "__main__":
    main()
