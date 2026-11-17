"""六项新增日常专项的回归测试。

覆盖：补给箱倒计时跳过/免费领取、礼包商城、装备工坊一键合成、
特权卡领取全部、邮件与好友领取、哥布林矿工逐格挖掘与停止条件、
以及「单项失败不影响其余」的异常隔离与进度计数。
"""

import asyncio

from app.automation import engine as engine_module
from app.automation.engine import AutomationEngine
from app.vision.ocr import OcrItem

from test_automation import FakeAdapter, _item, _tap_scripted_ocr


def _engine(adapter, ocr, *, sleep=None):
    return AutomationEngine(lambda: adapter, ocr=ocr, sleep=sleep or _noop)


async def _noop(_seconds):
    return None


def _stub_nav(engine, monkeypatch):
    """把回冒险页/关闭弹窗变成免 OCR 的空操作，便于聚焦单项逻辑。"""

    async def ensure(_sid):
        return True

    async def back(_sid):
        return True

    monkeypatch.setattr(engine, "_ensure_adventure", ensure)
    monkeypatch.setattr(engine, "_back_to_adventure", back)


def _run(coro):
    return asyncio.run(coro)


def test_supply_skips_when_countdown_active(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    # 底部商城 -> 补给箱区（含「后免费」倒计时，无「免费/领取」）
    screens = [
        [_item("开始", 0.45, 0.82), _item("商城", 0.10, 0.941)],
        [_item("冒险者补给箱", 0.263, 0.548), _item("06:07:12后免费", 0.286, 0.748)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))
    _stub_nav(engine, monkeypatch)

    _run(engine._daily_supply(adapter.session_id))

    progress = engine.status()["progress"]
    assert progress["supplyClaims"] == 0
    messages = " | ".join(log["message"] for log in engine.status()["logs"])
    assert "免费倒计时" in messages
    # Timer-only: must NOT tap the guessed supply-box button coordinate
    assert not any(abs(x - 0.354) < 0.01 and abs(y - 0.79) < 0.01 for x, y in adapter.taps)


def test_supply_claims_when_free_button_present(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82), _item("商城", 0.10, 0.941)],
        [_item("冒险者补给箱", 0.263, 0.548), _item("免费", 0.354, 0.790)],
        [_item("点击关闭", 0.502, 0.887)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))
    _stub_nav(engine, monkeypatch)

    _run(engine._daily_supply(adapter.session_id))

    assert engine.status()["progress"]["supplyClaims"] == 1


def test_nav_shop_falls_back_to_icon_coordinate(monkeypatch):
    """回归：底部商城是纯图标，OCR 无「商城」文字时必须点已验证坐标。"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    screen = type("S", (), {"items": [_item("开始", 0.45, 0.82)]})()

    _run(engine._tap_nav_shop(adapter.session_id, screen))

    assert len(adapter.taps) == 1
    x, y = adapter.taps[0]
    assert abs(x - 0.100) < 0.01 and abs(y - 0.941) < 0.01


def test_gift_claims_free_gift(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82), _item("商城", 0.10, 0.941)],
        [_item("礼包商城", 0.621, 0.876)],
        [_item("免费礼包（0/1）", 0.198, 0.309), _item("免费", 0.790, 0.378)],
        [_item("点击关闭", 0.502, 0.887)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))
    _stub_nav(engine, monkeypatch)

    _run(engine._daily_gift(adapter.session_id))

    assert engine.status()["progress"]["giftClaims"] == 1


def test_gift_skips_when_already_claimed(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82), _item("商城", 0.10, 0.941)],
        [_item("礼包商城", 0.621, 0.876)],
        [_item("免费礼包（0/1）", 0.198, 0.309), _item("已领取", 0.790, 0.378)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))
    _stub_nav(engine, monkeypatch)

    _run(engine._daily_gift(adapter.session_id))

    assert engine.status()["progress"]["giftClaims"] == 0


def test_enhance_uses_workshop_one_click_synthesis(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82), _item("装备", 0.252, 0.95)],
        [_item("工坊", 0.88, 0.53)],
        [_item("键合成", 0.886, 0.364)],  # OCR 常丢「一」
        [_item("点击关闭", 0.502, 0.887)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))
    _stub_nav(engine, monkeypatch)

    _run(engine._daily_enhance(adapter.session_id))

    assert engine.status()["progress"]["enhanceSteps"] == 1
    messages = " | ".join(log["message"] for log in engine.status()["logs"])
    assert "工坊" in messages


def test_privilege_claims_all(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82), _item("特权卡", 0.062, 0.228)],
        [_item("领取全部", 0.501, 0.958)],
        [_item("点击关闭", 0.502, 0.887)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))
    _stub_nav(engine, monkeypatch)

    _run(engine._daily_privilege(adapter.session_id))

    assert engine.status()["progress"]["privilegeClaims"] == 1


def test_mail_and_friend_claim(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        # 邮件链
        [_item("开始", 0.45, 0.82), _item("三", 0.08, 0.159)],
        [_item("邮件", 0.205, 0.373), _item("好友", 0.205, 0.55)],
        [_item("键领取", 0.676, 0.735)],
        [_item("点击关闭", 0.502, 0.887)],
        # 好友链
        [_item("开始", 0.45, 0.82), _item("三", 0.08, 0.159)],
        [_item("邮件", 0.205, 0.373), _item("好友", 0.205, 0.55)],
        [_item("游戏好友", 0.170, 0.80)],
        [_item("键领取赠送", 0.501, 0.728)],
        [_item("点击关闭", 0.502, 0.887)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))
    _stub_nav(engine, monkeypatch)

    _run(engine._daily_mail_friend(adapter.session_id))

    progress = engine.status()["progress"]
    assert progress["mailClaims"] == 1
    assert progress["friendClaims"] == 1


def test_goblin_digs_until_no_more(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    # 活动 -> 挑战 -> 矿工 -> 第一格后即「无法挖掘」
    screens = [
        [_item("开始", 0.45, 0.82), _item("活动", 0.912, 0.849)],
        [_item("挑战", 0.652, 0.972)],
        [_item("哥布林矿工", 0.208, 0.398)],
        [_item("60/60", 0.540, 0.951)],
        [_item("无法挖掘", 0.5, 0.5), _item("0/60", 0.540, 0.951)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))
    _stub_nav(engine, monkeypatch)

    _run(engine._daily_goblin(adapter.session_id))

    progress = engine.status()["progress"]
    assert progress["goblinDigs"] == 1
    messages = " | ".join(log["message"] for log in engine.status()["logs"])
    assert "无法挖掘" in messages
    # 绝不点付费「自动挖矿」
    assert not any(abs(x - 0.881) < 0.01 and abs(y - 0.169) < 0.01 for x, y in adapter.taps)


def test_goblin_pickaxe_excludes_top_stamina():
    screen = type("S", (), {"items": [
        _item("678/36", 0.132, 0.065),  # 顶部体力，需排除
        _item("60/60", 0.540, 0.951),   # 底部镐头
    ]})()
    assert AutomationEngine._goblin_pickaxe(screen) == 60


def test_specials_isolate_failures(monkeypatch):
    """单项抛异常不应阻断其余专项。"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    calls = []

    async def boom(_sid):
        calls.append("boom")
        raise RuntimeError("模拟失败")

    async def ok(_sid):
        calls.append("ok")

    engine._daily_supply = boom
    engine._daily_gift = ok
    engine._daily_enhance = ok
    engine._daily_privilege = ok
    engine._daily_mail_friend = ok
    engine._daily_goblin = ok

    _run(engine._daily_specials(adapter.session_id))

    assert calls.count("ok") == 5
    messages = " | ".join(log["message"] for log in engine.status()["logs"])
    assert "补给箱" in messages and "模拟失败" in messages


def test_specials_pass_session_id_to_each_task(monkeypatch):
    """回归：调度表必须把 session_id 传给每个子任务，否则真机全部 missing argument。"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    seen = []

    async def make(name):
        async def task(sid):
            seen.append((name, sid))
        return task

    engine._daily_supply = asyncio.run(make("supply"))
    engine._daily_gift = asyncio.run(make("gift"))
    engine._daily_enhance = asyncio.run(make("enhance"))
    engine._daily_privilege = asyncio.run(make("privilege"))
    engine._daily_mail_friend = asyncio.run(make("mail"))
    engine._daily_goblin = asyncio.run(make("goblin"))

    _run(engine._daily_specials(adapter.session_id))

    assert len(seen) == 6
    assert all(sid == adapter.session_id for _name, sid in seen)


def test_daily_task_dispatches_specials(monkeypatch):
    """TASK_DAILY 应同时调用通用收集与六项专项。"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    called = []

    async def fake_collect(_sid, _work, _config):
        called.append("collect")

    async def fake_specials(_sid):
        called.append("specials")

    monkeypatch.setattr(engine, "_collect_and_record", fake_collect)
    monkeypatch.setattr(engine, "_daily_specials", fake_specials)

    async def scenario():
        await engine.start(adapter.session_id, task="daily")
        await engine._task

    _run(scenario())

    assert called == ["collect", "specials"]


def test_progress_payload_exposes_new_counters():
    engine = _engine(FakeAdapter(), lambda _png: [])
    payload = engine.status()["progress"]
    for key in (
        "supplyClaims", "giftClaims", "enhanceSteps", "privilegeClaims",
        "mailClaims", "friendClaims", "goblinDigs",
    ):
        assert key in payload
