import asyncio

from app.device.mock_device import MockDevice


def test_mock_session_lifecycle():
    async def scenario():
        device = MockDevice()
        devices = await device.list_devices()
        assert devices[0].serial == "MOCK-0001"
        session = await device.create_session("MOCK-0001", fps=5)
        assert session.width == 1080
        assert session.height == 2400
        assert session.mode == "mock"
        assert device.get_session(session.id).id == session.id
        await device.close_session(session.id)
        try:
            device.get_session(session.id)
        except Exception as exc:
            assert getattr(exc, "code", None) == "SESSION_NOT_FOUND"
        else:
            raise AssertionError("会话应已删除")

    asyncio.run(scenario())


def test_mock_tap_and_key():
    async def scenario():
        device = MockDevice()
        session = await device.create_session("MOCK-0001", fps=5)
        result = await device.tap(session.id, 0.5, 0.5, press_ms=80, sigma=0.0, press_stdev=0.0)
        assert (result.target_x, result.target_y) == (540, 1200)
        assert (result.real_x, result.real_y) == (540, 1200)
        assert result.press_ms == 80
        assert result.injected_via == "mock"
        swipe = await device.swipe(session.id, 0.5, 0.8, 0.5, 0.2, duration_ms=300)
        assert len(swipe.points) == 11
        await device.key(session.id, "back")

    asyncio.run(scenario())


def test_mock_session_id_never_reused():
    async def scenario():
        device = MockDevice()
        first = await device.create_session("MOCK-0001", fps=5)
        second = await device.create_session("MOCK-0001", fps=15)
        assert (first.id, second.id) == ("mock-1", "mock-2")
        await device.close_session(first.id)
        third = await device.create_session("MOCK-0001", fps=10)
        assert third.id == "mock-3"
        assert device.get_session(second.id).fps == 15

    asyncio.run(scenario())
