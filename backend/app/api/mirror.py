from __future__ import annotations

import asyncio
import contextlib
import json
import time

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.deps import get_adapter
from app.errors import ApiError, MirrorLost

router = APIRouter(tags=["mirror"])

META_EVERY = 5


@router.websocket("/ws/mirror")
async def mirror(ws: WebSocket, sessionId: str = Query(...)) -> None:
    adapter = get_adapter()
    try:
        session = adapter.get_session(sessionId)
    except ApiError as exc:
        await ws.accept()
        await ws.send_text(
            json.dumps({"type": "error", "code": exc.code, "message": exc.message}, ensure_ascii=False)
        )
        await ws.close(code=4404)
        return

    await ws.accept()

    async def send_meta(seq: int) -> None:
        await ws.send_text(
            json.dumps(
                {
                    "type": "meta",
                    "seq": seq,
                    "ts": time.time(),
                    "width": session.width,
                    "height": session.height,
                    "fps": session.fps,
                    "degraded": session.degraded,
                    "mode": session.mode,
                },
                ensure_ascii=False,
            )
        )

    async def pump_client() -> None:
        while True:
            try:
                message = await ws.receive_text()
            except (WebSocketDisconnect, RuntimeError):
                return
            try:
                payload = json.loads(message)
            except ValueError:
                continue
            if isinstance(payload, dict) and payload.get("type") == "ping":
                try:
                    await ws.send_text(json.dumps({"type": "pong", "ts": time.time()}))
                except (WebSocketDisconnect, RuntimeError):
                    return

    await send_meta(0)
    pump = asyncio.create_task(pump_client())
    stream = adapter.frames(sessionId)
    sent = 0
    try:
        async for frame in stream:
            await ws.send_bytes(frame.jpeg)
            sent += 1
            if sent % META_EVERY == 0:
                await send_meta(frame.seq)
    except MirrorLost as exc:
        await ws.send_text(
            json.dumps({"type": "error", "code": "MIRROR_LOST", "message": exc.message}, ensure_ascii=False)
        )
    except WebSocketDisconnect:
        pass
    finally:
        pump.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await pump
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            with contextlib.suppress(Exception):
                await aclose()
        try:
            await ws.close()
        except (RuntimeError, WebSocketDisconnect):
            pass
