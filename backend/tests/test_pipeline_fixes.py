"""流水线中断根因回归：转盘硬卡死、公会 toast、游历二次领取、副本自动结算。"""

import asyncio

from app.automation import engine as engine_module
from app.automation.engine import AutomationEngine
from app.vision.ocr import OcrItem


class FakeAdapter:
    name = "fake"

    def __init__(self, session_id="s1"):
        self.session_id = session_id
        self.taps: list[tuple[float, float]] = []
        self.stopped_packages: list[str] = []
        self.launched_packages: list[str] = []

    def get_session(self, session_id):
        assert session_id == self.session_id

    async def screenshot(self, session_id):
        return b"png"

    async def tap(self, session_id, x, y, press_ms, sigma, press_stdev=20.0):
        self.taps.append((x, y))

    async def key(self, session_id, key):
        return None

    async def swipe(self, session_id, x1, y1, x2, y2, duration_ms=300):
        return None

    async def stop_app(self, session_id, package):
        self.stopped_packages.append(package)

    async def launch_app(self, session_id, package, user=None):
        self.launched_packages.append(package)


def _item(text, cx, cy):
    return OcrItem(
        text=text, confidence=0.99,
        bounds=(cx - 0.1, cy - 0.02, cx + 0.1, cy + 0.02),
    )


async def _noop_sleep(_seconds):
    return None


def _engine(adapter, ocr):
    return AutomationEngine(
        lambda: adapter, ocr=ocr, sleep=_noop_sleep,
        clock=lambda: 0.0, max_run_seconds=100,
    )


def _run(coro):
    return asyncio.run(coro)


def test_wheel_spin_hard_stuck_forces_restart():
    """转盘停在「转盘中」时标记硬卡死，并跳过普通两局阈值直接重启。"""
    adapter = FakeAdapter()
    reads = {"n": 0}

    def read(_png):
        reads["n"] += 1
        return [_item("转盘中", 0.5, 0.83), _item("传说技能", 0.5, 0.31)]

    engine = _engine(adapter, read)
    restarted = []

    async def restart(_session_id, reason):
        restarted.append(reason)
        return True

    engine._restart_game = restart
    finished = _run(engine._play_run_with_retries(adapter.session_id))
    assert finished is False
    assert engine._hard_stuck is True
    assert engine._last_run_failed is True
    assert len(restarted) == 1
    assert reads["n"] <= engine_module.WHEEL_SPIN_MAX_ROUNDS + 2


def test_wheel_spin_detected_without_small_button_text():
    """真机 OCR 读不到「转盘中」小字：仅见「传说技能」且无开始/继续也要判卡死。"""
    engine = _engine(FakeAdapter(), lambda _png: [_item("传说技能", 0.5, 0.31)])
    screen = engine_module.Screen([_item("传说技能", 0.5, 0.31)])
    assert engine._wheel_stuck(screen) is True
    result = engine_module.Screen([
        _item("传说技能", 0.5, 0.31), _item("继续", 0.5, 0.90),
    ])
    assert engine._wheel_stuck(result) is False


def test_back_to_adventure_restarts_on_stuck_wheel():
    adapter = FakeAdapter()
    reads = {"n": 0}

    def read(_png):
        reads["n"] += 1
        if reads["n"] == 1:
            return [_item("转盘中", 0.5, 0.83)]
        return [_item("开始", 0.45, 0.82), _item("冒险", 0.5, 0.985)]

    engine = _engine(adapter, read)
    restarted = []

    async def restart(_session_id, reason):
        restarted.append(reason)
        return True

    engine._restart_game = restart
    assert _run(engine._back_to_adventure(adapter.session_id)) is True
    assert restarted and "转盘" in restarted[0]


def test_account_sweep_continues_after_one_account_fails():
    """单号失败只记状态并继续下一个账号；硬卡死才中断整队。"""
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    engine._accounts = ["风甲", "风乙"]
    engine._account_runs = {"风甲": "r1", "风乙": "r2"}
    attempts: list[str] = []
    persisted: list[tuple[str, str]] = []

    async def switch(_session_id, name):
        attempts.append(name)
        return True

    async def bootstrap(_session_id):
        if engine._account == "风甲":
            raise RuntimeError("模拟账号失败")

    def persist(status, error=""):
        persisted.append((engine._account, status))

    engine._switch_account = switch
    engine._bootstrap = bootstrap
    engine._persist_account_run = persist
    _run(engine._account_sweep(adapter.session_id))
    assert attempts == ["风甲", "风乙"]
    assert [(name, status) for name, status in persisted if status in ("failed", "completed")] == [
        ("风甲", "failed"), ("风乙", "completed")
    ]
    assert any("继续下一个账号" in log["message"] for log in engine.status()["logs"])


def test_enter_guild_hall_waits_for_toast_and_accepts_subpage_anchor():
    """升级 toast 只是提示；等它消失后用「公会信息」等多锚点确认已进入。"""
    adapter = FakeAdapter()
    reads = {"n": 0}

    def read(_png):
        reads["n"] += 1
        if reads["n"] <= 2:
            return [_item("公会升级", 0.5, 0.2), _item("开始", 0.45, 0.82)]
        return [_item("公会信息", 0.5, 0.25), _item("捐献", 0.3, 0.6)]

    engine = _engine(adapter, read)

    async def ensure(_session_id):
        return True

    engine._ensure_adventure = ensure
    screen = _run(engine._enter_guild_hall(adapter.session_id))
    assert screen is not None
    assert screen.find_exact("公会信息") is not None
    assert not any("未确认公会" in log["message"] for log in engine.status()["logs"])


def test_travel_idle_reward_claims_second_step(monkeypatch):
    """「挂机奖励」点开后还要点「领取」，不能因 OCR 签名相同提前退出。"""
    adapter = FakeAdapter()
    screens = [
        [_item("游历", 0.5, 0.75)],
        [_item("挂机奖励", 0.5, 0.62)],
        [_item("领取", 0.5, 0.84)],
        [],
    ]
    engine = _engine(adapter, lambda _png: screens[min(len(adapter.taps), len(screens) - 1)])

    async def ensure(_session_id):
        return True

    async def noop(_session_id):
        return None

    monkeypatch.setattr(engine, "_ensure_adventure", ensure)
    monkeypatch.setattr(engine, "_back_to_adventure", noop)
    _run(engine._collect_entries(adapter.session_id, engine_module.DAILY_CONFIG))
    assert engine.status()["progress"]["dailySteps"] == 2
    assert any("二次确认" in log["message"] for log in engine.status()["logs"])


def test_dungeon_auto_battle_waits_for_victory_confirm():
    """副本挑战是自动战斗，结算页「胜利 + 确定」才是完成信号。"""
    adapter = FakeAdapter()
    reads = {"n": 0}

    def read(_png):
        reads["n"] += 1
        if reads["n"] <= 2:
            return [_item("突袭巨龙巢穴", 0.5, 0.25)]
        return [
            _item("胜利", 0.5, 0.44),
            _item("确定", 0.5, 0.80),
            _item("突袭巨龙巢穴", 0.5, 0.17),
        ]

    engine = _engine(adapter, read)
    assert _run(engine._play_dungeon_run(adapter.session_id, "巨龙巢穴")) is True
    assert any(abs(x - 0.5) < 0.11 and abs(y - 0.80) < 0.03 for x, y in adapter.taps)


def test_dungeon_reward_popup_counts_as_success():
    """真机胜利后可能直接弹「奖励/点击关闭」，也要算一次副本完成。"""
    adapter = FakeAdapter()

    def read(_png):
        return [_item("奖励", 0.5, 0.42), _item("点击关闭", 0.5, 0.88)]

    engine = _engine(adapter, read)
    assert _run(engine._play_dungeon_run(adapter.session_id, "巨龙巢穴")) is True
    assert (0.5, 0.88) in adapter.taps


def test_dungeon_sweep_reuses_open_detail_and_confirms():
    """扫荡优先复用已打开的副本详情弹窗，且只在确认结算后计数。"""
    adapter = FakeAdapter()
    reads = {"n": 0}

    def read(_png):
        reads["n"] += 1
        if reads["n"] == 1:
            return [
                _item("突袭巨龙巢穴", 0.5, 0.25),
                _item("扫荡上一难度", 0.29, 0.75),
                _item("挑战", 0.71, 0.75),
            ]
        return [_item("胜利", 0.5, 0.44), _item("确定", 0.5, 0.80)]

    engine = _engine(adapter, read)
    _run(engine._sweep_dungeon(adapter.session_id, "巨龙巢穴"))
    progress = engine.status()["progress"]
    assert progress["dungeonsDone"] == 1
    assert progress["dungeonSweeps"] == 1
