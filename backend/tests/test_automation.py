import asyncio
import json

import pytest

from app import accounts as accounts_module
from app.automation import engine as engine_module
from app.automation.engine import AutomationEngine
from app.vision.ocr import OcrItem


class FakeAdapter:
    name = "fake"

    def __init__(self, session_id="s1"):
        self.session_id = session_id
        self.taps: list[tuple[float, float]] = []
        self.keys: list[str] = []
        self.swipes: list[tuple[float, float, float, float]] = []

    def get_session(self, session_id):
        assert session_id == self.session_id

    async def screenshot(self, session_id):
        return b"png"

    async def tap(self, session_id, x, y, press_ms, sigma, press_stdev=20.0):
        self.taps.append((x, y))
        return None

    async def key(self, session_id, key):
        self.keys.append(key)

    async def swipe(self, session_id, x1, y1, x2, y2, duration_ms=300):
        self.swipes.append((x1, y1, x2, y2))

    async def stop_app(self, session_id, package):
        self.stopped_packages = getattr(self, "stopped_packages", []) + [package]

    async def launch_app(self, session_id, package, user=None):
        self.launched_packages = getattr(self, "launched_packages", []) + [package]
        return None


def _item(text, cx, cy):
    return OcrItem(text=text, confidence=0.99, bounds=(cx - 0.1, cy - 0.02, cx + 0.1, cy + 0.02))


def _tap_scripted_ocr(adapter, screens):
    """按点击次数推进的预设屏幕：同一屏在没有新点击时会稳定复现，贴近真实游戏"""

    def read(_png):
        index = min(len(adapter.taps), len(screens) - 1)
        return screens[index]

    return read


async def _noop_sleep(_seconds):
    return None


async def _return_none(_session_id):
    return None


async def _return_true(_session_id):
    return True


def _engine(adapter, ocr):
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return ticks["n"] * 0.001

    return AutomationEngine(
        lambda: adapter, ocr=ocr, sleep=_noop_sleep, clock=clock, max_run_seconds=50
    )


def test_stage_run_picks_skill_and_finishes(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [
            _item("选择技能", 0.50, 0.24),
            _item("从下方选择一个技能", 0.50, 0.376),
            _item("普攻剑气", 0.35, 0.404),
            _item("恢复强化", 0.35, 0.516),
            _item("0/1选择技能", 0.50, 0.822),
        ],
        [
            _item("选择技能", 0.50, 0.24),
            _item("普攻剑气", 0.35, 0.404),
            _item("1/1选择技能", 0.50, 0.822),
        ],
        [_item("已学技能", 0.90, 0.856), _item("领悟", 0.50, 0.911)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["status"] == "completed"
    assert status["progress"]["stageRuns"] == 1
    # 开始 → 选卡 → 确认 → 领悟 → 结算
    assert len(adapter.taps) >= 5
    assert any("选择技能" in log["message"] for log in status["logs"])


@pytest.mark.parametrize(
    "settlement",
    [
        [_item("胜利", 0.50, 0.30), _item("返回", 0.50, 0.90)],
        [_item("返回主城", 0.50, 0.90)],
    ],
)
def test_stage_settlement_requires_confirmed_return_to_adventure(settlement):
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: settlement)

    async def back_failed(_session_id):
        return False

    engine._back_to_adventure = back_failed

    async def scenario():
        assert not await engine._play_run(adapter.session_id)

    _run(scenario())
    assert engine.status()["progress"]["stageRuns"] == 0


def test_stage_respects_skill_priority(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [
            _item("选择技能", 0.50, 0.24),
            _item("从下方选择一个技能", 0.50, 0.376),
            _item("普攻剑气", 0.35, 0.404),
            _item("恢复强化", 0.35, 0.516),
            _item("普攻护盾", 0.35, 0.629),
            _item("0/1选择技能", 0.50, 0.822),
        ],
        [
            _item("选择技能", 0.50, 0.24),
            _item("恢复强化", 0.35, 0.516),
            _item("1/1选择技能", 0.50, 0.822),
        ],
        [_item("已学技能", 0.90, 0.856), _item("下一天", 0.50, 0.91)],
        [_item("再次挑战", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(
            adapter.session_id, task="growth", max_runs=1, skill_priority=["恢复强化"]
        )
        await engine._task

    _run(scenario())
    # 第二张卡的点击点（y=0.516）应被触发
    assert any(abs(y - 0.516) < 0.02 for _, y in adapter.taps)
    assert any("恢复强化" in log["message"] for log in engine.status()["logs"])


def test_daily_collects_rewards(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82), _item("游历", 0.499, 0.748)],
        [_item("开始游历", 0.50, 0.80), _item("挂机奖励", 0.30, 0.85)],
        [_item("领取", 0.50, 0.80)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="daily")
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["status"] == "completed"
    assert status["progress"]["dailySteps"] >= 2
    assert not any("游历：点击「开始游历」" in log["message"] for log in status["logs"])


def test_in_run_accepts_tutorial_choice_screen(monkeypatch):
    engine = _engine(FakeAdapter(), lambda _png: [])
    screen = engine_module.Screen(
        [
            _item("天", 0.28, 0.075),
            _item("你来到了黄昏古堡，这里传说是魔王的老巢。", 0.50, 0.62),
            _item("选择技能", 0.50, 0.916),
        ]
    )
    assert engine._in_run(screen) is True


def test_in_run_accepts_lucky_merchant_screen():
    engine = _engine(FakeAdapter(), lambda _png: [])
    screen = engine_module.Screen(
        [
            _item("幸运商人", 0.50, 0.30),
            _item("试试", 0.50, 0.905),
        ]
    )
    assert engine._in_run(screen) is True


def test_stage_handles_lucky_merchant():
    adapter = FakeAdapter()

    def read(_png):
        if not adapter.taps:
            return [
                _item("幸运商人", 0.50, 0.30),
                _item("试试", 0.50, 0.905),
            ]
        if len(adapter.taps) <= 2:
            return [_item("下一天", 0.50, 0.906)]
        if len(adapter.taps) == 3:
            return [_item("返回主城", 0.50, 0.90)]
        return [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, read)

    async def scenario():
        return await engine._play_run(adapter.session_id)

    assert _run(scenario()) is True
    assert adapter.taps[0] == (0.155, 0.545)
    assert adapter.taps[1] == (0.5, 0.905)


def test_lucky_merchant_exits_after_chances_used():
    adapter = FakeAdapter()
    merchant_reads = 8

    def read(_png):
        if len(adapter.taps) < merchant_reads * 2:
            return [
                _item("幸运商人", 0.50, 0.30),
                _item("试试", 0.50, 0.905),
            ]
        if len(adapter.taps) < merchant_reads * 2 + 1:
            return [_item("下一天", 0.50, 0.906)]
        return [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, read)

    async def scenario():
        return await engine._play_run(adapter.session_id)

    _run(scenario())
    assert (0.055, 0.905) in adapter.taps
    assert any("次数已用完" in log["message"] for log in engine.status()["logs"])


def test_back_to_adventure_tries_both_back_arrows():
    adapter = FakeAdapter()
    reads = {"n": 0}

    def read(_png):
        reads["n"] += 1
        if reads["n"] == 1:
            return [
                _item("还未开始游历", 0.50, 0.58),
                _item("开始", 0.45, 0.82),
                _item("20倍奖励", 0.50, 0.83),
                _item("开始游历", 0.50, 0.90),
            ]  # 游历面板也会识别到背景主城的「开始」
        return [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, read)

    async def scenario():
        return await engine._back_to_adventure(adapter.session_id)

    assert _run(scenario()) is True
    assert (0.070, 0.937) in adapter.taps
    assert (0.098, 0.955) in adapter.taps


def test_back_to_adventure_closes_home_page_with_top_right_x():
    """家园页左下角是「编辑」按钮：必须先点右上角 X，不能盲点返回箭头。"""
    adapter = FakeAdapter()
    reads = {"n": 0}

    def read(_png):
        reads["n"] += 1
        if reads["n"] == 1:
            return [
                _item("家园", 0.062, 0.065),
                _item("编辑", 0.109, 0.984),
            ]
        return [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, read)
    assert _run(engine._back_to_adventure(adapter.session_id)) is True
    assert (0.932, 0.132) in adapter.taps
    assert (0.070, 0.937) not in adapter.taps
    assert (0.098, 0.955) not in adapter.taps


def test_back_to_adventure_finishes_dig_minigame(monkeypatch):
    adapter = FakeAdapter()
    reads = {"n": 0}

    def read(_png):
        reads["n"] += 1
        if reads["n"] == 1:
            return [
                _item("挖宝", 0.50, 0.12),
                _item("翻出三个相同卡牌获得奖励", 0.50, 0.17),
            ]
        return [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, read)

    async def scenario():
        return await engine._back_to_adventure(adapter.session_id)

    assert _run(scenario()) is True
    assert len(adapter.taps) >= len(engine_module.DIG_CELLS)
    assert any("挖宝小游戏" in log["message"] for log in engine.status()["logs"])


def test_collect_entries_recovers_when_stuck_on_previous_page(monkeypatch):
    adapter = FakeAdapter()
    reads = {"n": 0}

    def read(_png):
        reads["n"] += 1
        if reads["n"] == 1:
            return [_item("背包", 0.50, 0.30)]  # 上一入口没退回冒险页
        return [_item("家园", 0.070, 0.745), _item("一键收获", 0.50, 0.86)]

    engine = _engine(adapter, read)
    ensure_calls = {"n": 0}

    async def ensure(_session_id):
        ensure_calls["n"] += 1
        return True

    async def back(_session_id):
        return True

    monkeypatch.setattr(engine, "_ensure_adventure", ensure)
    monkeypatch.setattr(engine, "_back_to_adventure", back)

    _run(engine._collect_entries(adapter.session_id, engine_module.DAILY_CONFIG))
    assert ensure_calls["n"] == 2  # 入口检查一次 + 卡页兜底一次
    assert engine._progress.daily_steps == 1
    assert any("进入日常：家园" in log["message"] for log in engine.status()["logs"])


def test_daily_returns_after_journey_page(monkeypatch):
    """「开始游历」不能被当成冒险页的「开始」按钮"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82), _item("游历", 0.499, 0.748)],
        [_item("开始游历", 0.50, 0.80), _item("挂机奖励", 0.30, 0.85)],
        [_item("游历结束", 0.50, 0.30), _item("返回", 0.50, 0.85)],
        [_item("开始", 0.45, 0.82), _item("家园", 0.070, 0.745)],
        [_item("一键收获", 0.50, 0.86)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="daily")
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["dailySteps"] == 2
    assert any("家园：点击「一键收获」" in log["message"] for log in status["logs"])
    assert not any("家园：点击「开始游历」" in log["message"] for log in status["logs"])


def test_start_rejects_concurrent_run(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [_item("开始", 0.45, 0.82)])

    async def scenario():
        await engine.start(adapter.session_id, task="daily")
        with pytest.raises(engine_module.AutomationBusy):
            await engine.start(adapter.session_id, task="daily")
        engine.stop()
        await engine._task

    _run(scenario())


def test_start_requires_ocr_engine(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: False)
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])

    async def scenario():
        with pytest.raises(engine_module.AutomationUnavailable):
            await engine.start(adapter.session_id, task="daily")

    _run(scenario())


def _run(coro):
    return asyncio.run(coro)


def test_choice_option_ignores_numeric_counters():
    engine = _engine(FakeAdapter(), lambda _png: [])
    screen = engine_module.Screen(
        [
            _item("1712", 0.91, 0.88),
            _item("休息", 0.28, 0.905),
            _item("搜索", 0.70, 0.905),
        ]
    )
    assert engine._choice_option(screen).text == "搜索"


def test_choice_option_allows_compound_stage_action():
    engine = _engine(FakeAdapter(), lambda _png: [])
    screen = engine_module.Screen(
        [_item("领悟传承", 0.735, 0.905), _item("离开", 0.265, 0.921)]
    )
    assert engine._choice_option(screen).text == "领悟传承"


def test_choice_option_ignores_single_result_label():
    engine = _engine(FakeAdapter(), lambda _png: [])
    screen = engine_module.Screen([_item("小吉", 0.91, 0.94)])
    assert engine._choice_option(screen) is None


def test_choice_option_ignores_luck_result_labels():
    engine = _engine(FakeAdapter(), lambda _png: [])
    screen = engine_module.Screen(
        [_item("大吉", 0.09, 0.94), _item("小吉", 0.91, 0.94)]
    )
    assert engine._choice_option(screen) is None


def test_stage_closes_slot_result_without_remaining_counter():
    adapter = FakeAdapter()

    def read(_png):
        if not adapter.taps:
            return [
                _item("神话技能", 0.50, 0.28),
                _item("大吉", 0.09, 0.94),
                _item("小吉", 0.91, 0.94),
            ]
        if len(adapter.taps) == 1:
            return [_item("下一天", 0.50, 0.906)]
        if len(adapter.taps) == 2:
            return [_item("返回主城", 0.50, 0.90)]
        return [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, read)

    async def scenario():
        assert await engine._play_run(adapter.session_id)

    _run(scenario())
    assert adapter.taps[0] == (0.5, 0.90)
    assert not any(abs(x - 0.91) < 0.02 for x, _ in adapter.taps)


def test_in_run_recognizes_slot_result():
    engine = _engine(FakeAdapter(), lambda _png: [])
    screen = engine_module.Screen(
        [
            _item("神话技能", 0.50, 0.28),
            _item("剩余旋转次数：5", 0.50, 0.70),
            _item("小吉", 0.91, 0.94),
        ]
    )
    assert engine._in_run(screen)


def test_stage_waits_for_battle_animation():
    adapter = FakeAdapter()
    battle = [_item("第15天", 0.10, 0.58), _item("战斗中", 0.50, 0.90)]
    screens = [
        battle.copy() for _ in range(6)
    ] + [
        [_item("继续", 0.50, 0.906)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]

    def read(_png):
        return screens.pop(0) if screens else [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, read)

    async def scenario():
        assert await engine._play_run(adapter.session_id)

    _run(scenario())
    assert adapter.taps[0] == (0.5, 0.906)


def test_stage_waits_for_day_transition():
    adapter = FakeAdapter()
    transition = [_item("第49天", 0.10, 0.60), _item("魔王之塔", 0.50, 0.64)]
    screens = [transition.copy() for _ in range(6)] + [
        [_item("继续", 0.50, 0.906)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]

    def read(_png):
        return screens.pop(0) if screens else [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, read)

    async def scenario():
        assert await engine._play_run(adapter.session_id)

    _run(scenario())
    assert adapter.taps[0] == (0.5, 0.906)


def test_stage_fails_fast_when_action_screen_is_frozen():
    adapter = FakeAdapter()
    reads = {"n": 0}
    frozen = [
        _item("方尖碑上刻着神秘的符文", 0.50, 0.61),
        _item("经验+34", 0.17, 0.78),
        _item("下一天", 0.50, 0.906),
        _item("大吉", 0.09, 0.94),
        _item("小吉", 0.91, 0.94),
    ]

    def read(_png):
        reads["n"] += 1
        return frozen

    engine = _engine(adapter, read)
    engine._max_run_seconds = 0.05

    assert _run(engine._play_run_ocr(adapter.session_id)) is False
    messages = [log["message"] for log in engine.status()["logs"]]
    assert "界面长时间无响应，放弃当前关卡" in messages
    assert "本轮推关超时，未检测到结算界面" not in messages
    assert reads["n"] <= 12


def test_stage_does_not_retry_start_on_choice_result():
    adapter = FakeAdapter()
    screens = [
        [
            _item("开始", 0.50, 0.85),
            _item("运气不佳", 0.50, 0.43),
            _item("失去15%生命", 0.50, 0.52),
        ],
        [_item("继续", 0.50, 0.906)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]

    def read(_png):
        return screens.pop(0) if screens else [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, read)

    async def scenario():
        assert await engine._play_run(adapter.session_id)

    _run(scenario())
    assert adapter.taps[0] == (0.5, 0.906)


def test_stage_starts_unlabelled_event_wheel():
    adapter = FakeAdapter()

    def read(_png):
        if not adapter.taps:
            return [
                _item("最大生命+30%", 0.50, 0.304),
                _item("最大生命+10%", 0.77, 0.376),
                _item("经验+30", 0.23, 0.376),
                _item("战斗胜利", 0.12, 0.628),
                _item("第31天", 0.10, 0.730),
                _item("发现了一座远古废墟。", 0.28, 0.773),
                _item("开始", 0.50, 0.832),
            ]
        if len(adapter.taps) == 1:
            return [_item("继续", 0.50, 0.906)]
        if len(adapter.taps) == 2:
            return [_item("返回主城", 0.50, 0.90)]
        return [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, read)
    engine._max_run_seconds = 0.05

    async def scenario():
        assert await engine._play_run(adapter.session_id)

    _run(scenario())
    assert adapter.taps[0] == (0.5, 0.832)


def test_stage_starts_legendary_skill_wheel():
    adapter = FakeAdapter()

    def read(_png):
        if not adapter.taps:
            return [
                _item("传说技能", 0.50, 0.306),
                _item("开始", 0.50, 0.832),
                _item("第36天", 0.10, 0.688),
                _item("下一天", 0.50, 0.906),
            ]
        if len(adapter.taps) == 1:
            return [_item("继续", 0.50, 0.906)]
        if len(adapter.taps) == 2:
            return [_item("返回主城", 0.50, 0.90)]
        return [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, read)

    async def scenario():
        assert await engine._play_run(adapter.session_id)

    _run(scenario())
    assert adapter.taps[0] == (0.5, 0.832)


def test_stage_starts_obelisk_wheel():
    adapter = FakeAdapter()

    def read(_png):
        if not adapter.taps:
            return [
                _item("方尖碑上刻着神秘的符文", 0.50, 0.75),
                _item("开始", 0.50, 0.832),
                _item("第54天", 0.10, 0.604),
            ]
        if len(adapter.taps) == 1:
            return [_item("继续", 0.50, 0.906)]
        if len(adapter.taps) == 2:
            return [_item("返回主城", 0.50, 0.90)]
        return [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, read)
    engine._max_run_seconds = 0.010

    async def scenario():
        assert await engine._play_run(adapter.session_id)

    _run(scenario())
    assert adapter.taps[0] == (0.5, 0.832)


def test_stage_confirms_mythic_skill_result_before_spinning_again():
    adapter = FakeAdapter()

    def read(_png):
        if not adapter.taps:
            return [
                _item("神话技能", 0.50, 0.277),
                _item("获得新技能", 0.50, 0.391),
                _item("剩余旋转次数：1", 0.50, 0.697),
                _item("继续", 0.50, 0.739),
                _item("转动", 0.50, 0.832),
            ]
        if len(adapter.taps) == 1:
            return [_item("下一天", 0.50, 0.906)]
        if len(adapter.taps) == 2:
            return [_item("返回主城", 0.50, 0.90)]
        return [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, read)

    async def scenario():
        assert await engine._play_run(adapter.session_id)

    _run(scenario())
    assert adapter.taps[0] == (0.5, 0.739)


def test_stage_spins_mythic_wheel_before_closing_result():
    adapter = FakeAdapter()

    def read(_png):
        if not adapter.taps:
            return [
                _item("神话技能", 0.50, 0.28),
                _item("剩余旋转次数：5", 0.50, 0.70),
                _item("转动", 0.50, 0.832),
                _item("下一天", 0.50, 0.906),
            ]
        if len(adapter.taps) == 1:
            return [
                _item("神话技能", 0.50, 0.28),
                _item("剩余旋转次数：4", 0.50, 0.70),
                _item("无事发生", 0.50, 0.52),
            ]
        if len(adapter.taps) == 2:
            return [_item("下一天", 0.50, 0.906)]
        if len(adapter.taps) == 3:
            return [_item("返回主城", 0.50, 0.90)]
        return [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, read)

    async def scenario():
        assert await engine._play_run(adapter.session_id)

    _run(scenario())
    assert adapter.taps[:2] == [(0.5, 0.832), (0.5, 0.90)]


def test_stage_closes_slot_result_instead_of_click_luck_label():
    adapter = FakeAdapter()

    def read(_png):
        if not adapter.taps:
            return [
                _item("神话技能", 0.50, 0.28),
                _item("剩余旋转次数：5", 0.50, 0.70),
                _item("小吉", 0.91, 0.94),
            ]
        if len(adapter.taps) == 1:
            return [_item("下一天", 0.50, 0.906)]
        if len(adapter.taps) == 2:
            return [_item("返回主城", 0.50, 0.90)]
        return [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, read)

    async def scenario():
        assert await engine._play_run(adapter.session_id)

    _run(scenario())
    assert adapter.taps[0] == (0.5, 0.90)
    assert not any(abs(x - 0.91) < 0.02 for x, _ in adapter.taps)


def test_stage_closes_skill_detail_before_advancing():
    adapter = FakeAdapter()
    detail = [
        _item("传说技能", 0.50, 0.30),
        _item("X", 0.50, 0.825),
        _item("1712", 0.91, 0.88),
        _item("下一天", 0.50, 0.906),
    ]

    def read(_png):
        if not adapter.taps:
            return detail
        if len(adapter.taps) == 1:
            return [_item("下一天", 0.50, 0.906)]
        if len(adapter.taps) == 2:
            return [_item("返回主城", 0.50, 0.90)]
        return [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, read)

    async def scenario():
        assert await engine._play_run(adapter.session_id)

    _run(scenario())
    assert abs(adapter.taps[0][0] - 0.50) < 0.001
    assert abs(adapter.taps[0][1] - 0.825) < 0.001
    assert not any(abs(x - 0.91) < 0.02 for x, _ in adapter.taps)


def test_stage_handles_choice_event(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [
            _item("第4天", 0.09, 0.626),
            _item("你发现了一处无人小屋。", 0.23, 0.67),
            _item("休息", 0.28, 0.905),
            _item("搜索", 0.70, 0.905),
        ],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1)
        await engine._task

    _run(scenario())
    assert engine.status()["progress"]["stageRuns"] == 1
    assert any("奇遇选项" in log["message"] for log in engine.status()["logs"])
    assert any(abs(x - 0.70) < 0.02 for x, _ in adapter.taps)


def test_stage_skill_modal_without_confirm(monkeypatch):
    """部分技能弹窗没有确认按钮，选卡后直接关闭"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [
            _item("选择技能", 0.50, 0.24),
            _item("从下方选择一个技能", 0.50, 0.376),
            _item("怒攻冰刺", 0.35, 0.43),
            _item("闪电飞刀", 0.35, 0.53),
            _item("怒攻恢复", 0.35, 0.63),
            _item("刷新(3)", 0.42, 0.80),
        ],
        [_item("第5天", 0.09, 0.626), _item("下一天", 0.50, 0.91)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["status"] == "completed"
    assert status["progress"]["stageRuns"] == 1
    assert not any("从下方选择一个技能" in log["message"] for log in status["logs"])


def test_stage_resumes_run_in_progress(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [
            _item("第4天", 0.09, 0.626),
            _item("你发现了一处无人小屋。", 0.23, 0.67),
            _item("休息", 0.28, 0.905),
            _item("搜索", 0.70, 0.905),
        ],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["status"] == "completed"
    assert status["progress"]["stageRuns"] == 1


def test_stage_handles_prompt_selection(monkeypatch):
    """「请选择一项…」弹窗时底部「下一天」是禁用的，必须先选馈赠"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [
            _item("第10天", 0.09, 0.74),
            _item("你遇见了天使！", 0.50, 0.42),
            _item("请选择一项天使的馈赠！", 0.50, 0.46),
            _item("大防御", 0.29, 0.49),
            _item("防御↑↑↑", 0.30, 0.55),
            _item("LV.1", 0.15, 0.61),
            _item("恢复生命", 0.28, 0.65),
            _item("下一天", 0.50, 0.91),
        ],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["stageRuns"] == 1
    assert any("选择馈赠" in log["message"] for log in status["logs"])
    assert any(abs(x - 0.29) < 0.02 and abs(y - 0.49) < 0.02 for x, y in adapter.taps)


def test_stage_single_card_modal_uses_finalize_button(monkeypatch):
    """单卡弹窗（如获得黄金鸟蛋）只有「拾取」按钮，不能反复点卡片"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [
            _item("选择技能", 0.50, 0.361),
            _item("从下方选择一个技能", 0.50, 0.398),
            _item("神话", 0.149, 0.467),
            _item("黄金鸟蛋", 0.346, 0.477),
            _item("获得", 0.50, 0.743),
            _item("拾取", 0.50, 0.911),
        ],
        [_item("第11天", 0.09, 0.74), _item("下一天", 0.50, 0.91)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["stageRuns"] == 1
    assert any("确认：「获得」" in log["message"] for log in status["logs"])


def test_stage_does_not_tap_reward_sentence(monkeypatch):
    """文案里出现「获得」时不能被当成确认按钮"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [
            _item("选择技能", 0.50, 0.236),
            _item("从下方选择一个技能", 0.50, 0.376),
            _item("普攻剑气", 0.35, 0.404),
            _item("恢复强化", 0.35, 0.516),
            _item("你感受到古代魔法的力量，可以获得获得2个技能。", 0.426, 0.773),
            _item("0/1选择技能", 0.50, 0.822),
        ],
        [
            _item("选择技能", 0.50, 0.236),
            _item("普攻剑气", 0.35, 0.404),
            _item("1/1选择技能", 0.50, 0.822),
        ],
        [_item("已学技能", 0.90, 0.856), _item("下一天", 0.50, 0.91)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["stageRuns"] == 1
    assert not any(abs(x - 0.426) < 0.02 and abs(y - 0.773) < 0.02 for x, y in adapter.taps)


def test_stage_handles_lucky_wheel(monkeypatch):
    """转盘：先转动 → 领取奖励 → 次数用尽后点「返回」退出"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [_item("第18天", 0.09, 0.74), _item("幸运转盘", 0.50, 0.227), _item("转动", 0.50, 0.90)],
        [
            _item("幸运转盘", 0.50, 0.227),
            _item("恭喜获得", 0.50, 0.317),
            _item("获得", 0.50, 0.69),
        ],
        [
            _item("第18天", 0.09, 0.74),
            _item("幸运转盘", 0.50, 0.227),
            _item("幸运转盘无法继续转动了", 0.50, 0.85),
            _item("返回", 0.50, 0.90),
        ],
        [_item("第19天", 0.09, 0.74), _item("下一天", 0.50, 0.91)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["stageRuns"] == 1
    assert any("转动幸运转盘" in log["message"] for log in status["logs"])
    assert any("退出幸运转盘" in log["message"] for log in status["logs"])


def test_stage_story_text_does_not_trigger_wheel(monkeypatch):
    """日志文案里出现「幸运转盘」不能被当成转盘弹窗"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [
            _item("第18天", 0.09, 0.686),
            _item("你发现了一个幸运转盘。", 0.17, 0.77),
            _item("你离开了", 0.10, 0.84),
            _item("下一天", 0.50, 0.957),
        ],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["stageRuns"] == 1
    assert not any("转盘" in log["message"] for log in status["logs"])


def test_stage_enters_dig_minigame(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [_item("第46天", 0.10, 0.625), _item("挖宝", 0.50, 0.906)],
        [_item("翻出三个相同卡牌获得奖励", 0.50, 0.170)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))
    engine._max_run_seconds = 0.006

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1, tower_floors=0)
        await engine._task

    _run(scenario())
    assert engine.status()["progress"]["stageRuns"] == 1
    assert adapter.taps[1] == (0.5, 0.906)


def test_stage_plays_dig_minigame(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    panel = [
        _item("挖宝", 0.50, 0.125),
        _item("翻出三个相同卡牌获得奖励", 0.50, 0.170),
    ]
    screens = [
        [_item("开始", 0.45, 0.82)],
        list(panel),
        list(panel),
        [_item("第20天", 0.09, 0.74), _item("下一天", 0.50, 0.91)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["stageRuns"] == 1
    assert any("挖宝翻牌" in log["message"] for log in status["logs"])
    assert any(abs(x - 0.170) < 0.01 and abs(y - 0.440) < 0.01 for x, y in adapter.taps)


def test_stage_handles_victory_screen(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [
            _item("胜利", 0.50, 0.27),
            _item("生存天数", 0.50, 0.36),
            _item("25天", 0.50, 0.40),
            _item("最高旅程：25天", 0.35, 0.44),
            _item("已学技能", 0.08, 0.94),
            _item("返回", 0.50, 0.85),
            _item("战斗中", 0.50, 0.93),
        ],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["stageRuns"] == 1
    assert any("关卡结算" in log["message"] for log in status["logs"])


def test_stage_skill_cards_ignore_modal_title(monkeypatch):
    """弹窗标题（如「能力进化」）不能被当成技能卡"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [
            _item("能力进化", 0.50, 0.310),
            _item("从下方选择一个技能", 0.50, 0.355),
            _item("攻击", 0.25, 0.392),
            _item("攻击↑。", 0.30, 0.427),
            _item("鳄霸", 0.25, 0.548),
            _item("胜利誓约之剑", 0.25, 0.669),
            _item("已学技能", 0.897, 0.892),
        ],
        [_item("第16天", 0.09, 0.74), _item("下一天", 0.50, 0.91)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["stageRuns"] == 1
    assert not any("能力进化" in log["message"] for log in status["logs"])


def test_stage_handles_pact_prompt(monkeypatch):
    """「是否与…签订契约」类弹窗，优先选择签订"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [
            _item("你遇见了咕噜怪！", 0.487, 0.407),
            _item("是否与咕噜怪签订契约，获得技能？", 0.493, 0.448),
            _item("传说", 0.150, 0.550),
            _item("缩小魔法", 0.347, 0.560),
            _item("攻击有概率使敌人缩小。", 0.396, 0.586),
            _item("第10天", 0.100, 0.730),
            _item("拒绝", 0.283, 0.764),
            _item("签订", 0.716, 0.765),
            _item("下一天", 0.502, 0.905),
        ],
        [_item("第10天", 0.09, 0.74), _item("下一天", 0.50, 0.91)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["stageRuns"] == 1
    assert any("契约选择：「签订」" in log["message"] for log in status["logs"])


def test_stage_retries_start_if_not_entered(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [_item("开始", 0.45, 0.82), _item("活动", 0.91, 0.848)],
        [_item("第1天", 0.09, 0.74), _item("下一天", 0.50, 0.91)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["stageRuns"] == 1
    assert any("重新点击「开始」" in log["message"] for log in status["logs"])


def test_automation_api_start_status_stop(client, monkeypatch):
    from app.api import automation as automation_api

    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [_item("开始", 0.45, 0.82)])
    monkeypatch.setattr(automation_api, "get_engine", lambda: engine)

    started = client.post(
        "/api/automation/start", json={"sessionId": "s1", "task": "daily"}
    )
    assert started.status_code == 200
    assert started.json()["task"] == "daily"

    status = client.get("/api/automation/status")
    assert status.status_code == 200
    assert status.json()["task"] == "daily"

    stopped = client.post("/api/automation/stop")
    assert stopped.status_code == 200


def test_automation_api_rejects_unknown_task(client, monkeypatch):
    from app.api import automation as automation_api

    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    engine = _engine(FakeAdapter(), lambda _png: [])
    monkeypatch.setattr(automation_api, "get_engine", lambda: engine)

    response = client.post(
        "/api/automation/start", json={"sessionId": "s1", "task": "nope"}
    )
    assert response.status_code == 422


def test_fast_mode_skill_picks_first_card(monkeypatch):
    """speed<1.0 时忽略 skill_priority，固定选第一张卡"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [
            _item("选择技能", 0.50, 0.24),
            _item("从下方选择一个技能", 0.50, 0.376),
            _item("普攻剑气", 0.35, 0.404),
            _item("恢复强化", 0.35, 0.516),
            _item("普攻护盾", 0.35, 0.629),
            _item("0/1选择技能", 0.50, 0.822),
        ],
        [
            _item("选择技能", 0.50, 0.24),
            _item("普攻剑气", 0.35, 0.404),
            _item("1/1选择技能", 0.50, 0.822),
        ],
        [_item("已学技能", 0.90, 0.856), _item("下一天", 0.50, 0.91)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        # 优先级写的是「恢复强化」（第二张），但 fast 模式应选第一张「普攻剑气」
        await engine.start(
            adapter.session_id,
            task="growth",
            max_runs=1,
            skill_priority=["恢复强化"],
            speed=0.5,
        )
        await engine._task

    _run(scenario())
    # 第一张卡 y=0.404 应被点击，第二张 y=0.516 不应被点击
    assert any(abs(y - 0.404) < 0.02 for _, y in adapter.taps)
    assert not any(abs(y - 0.516) < 0.02 for _, y in adapter.taps)
    assert any("普攻剑气" in log["message"] for log in engine.status()["logs"])


def test_tower_runs_two_floors(monkeypatch):
    """成长任务中爬塔默认连打两层"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    # 推关1轮 → 爬塔2层
    screens = [
        [_item("开始", 0.45, 0.82)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82), _item("星级挑战", 0.66, 0.747)],
        [_item("开始挑战", 0.50, 0.82)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82), _item("星级挑战", 0.66, 0.747)],
        [_item("开始挑战", 0.50, 0.82)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82), _item("星级挑战", 0.66, 0.747)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1, tower_floors=2)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["status"] == "completed"
    assert status["progress"]["towerFloors"] == 2
    assert status["progress"]["stageRuns"] == 1
    assert any("爬塔第 1 层" in log["message"] for log in status["logs"])
    assert any("爬塔第 2 层" in log["message"] for log in status["logs"])


def test_invalid_speed_rejected(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [_item("开始", 0.45, 0.82)])

    async def scenario():
        with pytest.raises(engine_module.AutomationUnavailable):
            await engine.start(adapter.session_id, task="daily", speed=5.0)

    _run(scenario())


def test_tower_skipped_when_zero_floors(monkeypatch):
    """towerFloors=0 时成长任务只推关不爬塔"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    # 推关1轮后无「星级挑战」入口 → 跳过爬塔
    screens = [
        [_item("开始", 0.45, 0.82)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1, tower_floors=0)
        await engine._task

    _run(scenario())
    progress = engine.status()["progress"]
    assert progress["towerFloors"] == 0
    assert progress["stageRuns"] == 1
    assert not any("爬塔第" in log["message"] for log in engine.status()["logs"])


def test_guild_collects_rewards(monkeypatch):
    """公会任务：进入公会页并点击领取"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82), _item("公会", 0.50, 0.748)],
        [_item("捐献", 0.50, 0.80)],
        [_item("开始", 0.45, 0.82), _item("公会", 0.50, 0.748)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="guild")
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["status"] == "completed"
    assert status["progress"]["guildSteps"] == 1
    assert any("进入公会" in log["message"] for log in status["logs"])


def test_ship_collects_rewards(monkeypatch):
    """船任务：进入船页并点击领取"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82), _item("船", 0.50, 0.748)],
        [_item("领取", 0.50, 0.80)],
        [_item("开始", 0.45, 0.82), _item("船", 0.50, 0.748)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="ship")
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["status"] == "completed"
    assert status["progress"]["shipSteps"] == 1
    assert any("进入船" in log["message"] for log in status["logs"])


def test_guild_entry_not_found_skips(monkeypatch):
    """公会入口不存在时跳过，不报错"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="guild")
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["status"] == "completed"
    assert status["progress"]["guildSteps"] == 0
    assert any("未找到公会入口" in log["message"] for log in status["logs"])


def test_all_runs_daily_first_then_stage(monkeypatch):
    """全量任务按 日常 → 公会 → 船 → 推关 的顺序执行"""
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    # 屏幕按点击次数推进：每类入口点击后下一屏出现领取按钮
    screens = [
        # 日常：游历
        [_item("开始", 0.45, 0.82), _item("游历", 0.50, 0.748)],
        [_item("开始游历", 0.50, 0.80), _item("挂机奖励", 0.30, 0.85)],
        # 公会
        [_item("开始", 0.45, 0.82), _item("公会", 0.50, 0.748)],
        [_item("捐献", 0.50, 0.80)],
        # 船
        [_item("开始", 0.45, 0.82), _item("船", 0.50, 0.748)],
        [_item("领取", 0.50, 0.80)],
        # 推关 1 轮
        [_item("开始", 0.45, 0.82)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    # 新增的公会捐献/讨伐、副本阶段单独有覆盖；这里只验证原有收集 → 推关顺序，
    # 把补充阶段置空，避免 scripted OCR 屏幕序列被额外读取打乱。
    async def noop(*_args, **_kwargs):
        return None

    for name in ("_daily_specials", "_guild", "_guild_raid", "_dungeons"):
        monkeypatch.setattr(engine, name, noop)

    async def scenario():
        await engine.start(
            adapter.session_id, task="all", max_runs=1, tower_floors=0
        )
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["status"] == "completed"
    assert status["progress"]["stageRuns"] == 1
    assert status["progress"]["dailySteps"] == 1
    assert status["progress"]["guildSteps"] == 1
    assert status["progress"]["shipSteps"] == 1


def test_parse_stamina_and_power():
    engine = _engine(FakeAdapter(), lambda _png: [])
    screen = engine_module.Screen(
        [
            _item("60/60", 0.30, 0.055),
            _item("战力 12.3万", 0.55, 0.30),
        ]
    )
    assert engine._parse_stamina(screen) == 60
    assert engine._parse_power(screen) == 123000


def test_travel_skips_when_stamina_below_threshold():
    adapter = FakeAdapter()
    engine = _engine(
        adapter,
        lambda _png: [_item("60/60", 0.30, 0.055), _item("游历", 0.50, 0.748)],
    )

    async def scenario():
        engine._travel_stamina = 100
        await engine._travel(adapter.session_id)

    _run(scenario())
    status = engine.status()
    assert status["progress"]["travelSpent"] == 0
    assert any("跳过游历" in log["message"] for log in status["logs"])


def test_bootstrap_stops_after_two_stage_failures():
    adapter = FakeAdapter()
    calls = {"n": 0}

    def read(_png):
        calls["n"] += 1
        # 每次尝试：主城 → 失败结算 → 主城
        if calls["n"] % 3 == 2:
            return [_item("失败", 0.50, 0.20), _item("返回主城", 0.50, 0.90)]
        return [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, read)

    async def scenario():
        engine._max_stage_fails = 2
        await engine._bootstrap_stage(adapter.session_id)
        assert engine.status()["progress"]["stageFailStreak"] == 1
        await engine._bootstrap_stage(adapter.session_id)
        assert engine.status()["progress"]["stageFailStreak"] == 2
        taps_before = len(adapter.taps)
        # 第三次进入应直接被失败上限拦住，不再点击
        await engine._bootstrap_stage(adapter.session_id)
        assert len(adapter.taps) == taps_before

    _run(scenario())
    status = engine.status()
    assert status["progress"]["stageFails"] == 2
    assert status["progress"]["stageFailStreak"] == 2


def test_bootstrap_stage_respects_max_runs(monkeypatch):
    adapter = FakeAdapter()
    engine = _engine(
        adapter,
        lambda _png: [_item("开始", 0.45, 0.82), _item("60/60", 0.50, 0.065)],
    )

    async def play_run(_session_id, **_kwargs):
        engine._last_run_failed = False
        return True

    monkeypatch.setattr(engine, "_play_run", play_run)

    async def scenario():
        engine._max_runs = 1
        await engine._bootstrap_stage(adapter.session_id)

    _run(scenario())
    assert engine.status()["progress"]["stageRuns"] == 1
    assert len(adapter.taps) == 1


def test_growth_loops_travel_upgrade_stage_until_stamina_low(monkeypatch):
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    calls: list[str] = []
    stamina = {"v": 300}

    async def travel(_session_id):
        calls.append("travel")
        stamina["v"] = max(stamina["v"] - 100, 3)
        engine._progress.stamina = stamina["v"]
        return True

    async def upgrade(_session_id):
        calls.append("upgrade")

    async def stage(_session_id, *, rounds=None):
        calls.append("stage")
        engine._progress.stage_runs += 1
        engine._progress.stamina = stamina["v"]

    monkeypatch.setattr(engine, "_travel_until_low", travel)
    monkeypatch.setattr(engine, "_upgrade", upgrade)
    monkeypatch.setattr(engine, "_stage", stage)
    engine._tower_floors = 0
    engine._max_runs = 0

    async def scenario():
        await engine._growth(adapter.session_id)

    _run(scenario())
    assert calls == [
        "travel", "upgrade", "stage",
        "travel", "upgrade", "stage",
        "travel",
    ]


def test_growth_stops_after_two_stage_failures(monkeypatch):
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    calls: list[str] = []

    async def travel(_session_id):
        calls.append("travel")
        engine._progress.stamina = 500
        return True

    async def upgrade(_session_id):
        calls.append("upgrade")

    async def stage(_session_id, *, rounds=None):
        calls.append("stage")
        engine._progress.stage_fails += 1
        engine._progress.stage_fail_streak += 1

    monkeypatch.setattr(engine, "_travel_until_low", travel)
    monkeypatch.setattr(engine, "_upgrade", upgrade)
    monkeypatch.setattr(engine, "_stage", stage)
    engine._tower_floors = 0
    engine._max_runs = 0

    async def scenario():
        await engine._growth(adapter.session_id)

    _run(scenario())
    assert calls.count("stage") == 2
    assert calls.count("travel") == 2


def test_stage_stops_when_stamina_below_five():
    adapter = FakeAdapter()
    engine = _engine(
        adapter,
        lambda _png: [_item("开始", 0.45, 0.82), _item("3/500", 0.10, 0.05)],
    )

    async def scenario():
        await engine._stage(adapter.session_id, rounds=1)

    _run(scenario())
    assert engine.status()["progress"]["stageRuns"] == 0
    assert adapter.taps == []


def test_travel_repeats_until_stamina_below_floor(monkeypatch):
    adapter = FakeAdapter()
    stamina = {"v": 300}
    engine = _engine(
        adapter,
        lambda _png: [_item(f"{stamina['v']}/500", 0.10, 0.05)],
    )
    calls: list[int] = []

    async def travel(_session_id):
        calls.append(1)
        stamina["v"] -= 100
        engine._progress.stamina = stamina["v"]
        return True

    monkeypatch.setattr(engine, "_travel", travel)

    async def scenario():
        await engine._travel_until_low(adapter.session_id)

    _run(scenario())
    assert len(calls) == 3


def test_read_retries_truncated_screenshot():
    adapter = FakeAdapter()
    calls = {"n": 0}

    def ocr(_png):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("image file is truncated")
        return [_item("开始", 0.45, 0.82)]

    engine = _engine(adapter, ocr)

    async def scenario():
        return await engine._read(adapter.session_id)

    screen = _run(scenario())
    assert screen.find_exact("开始") is not None
    assert calls["n"] == 2


def test_stage_retries_until_run_settles(monkeypatch):
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [_item("开始", 0.45, 0.82)])
    calls: list[int] = []

    async def play_run(_session_id, **_kwargs):
        calls.append(1)
        engine._last_run_failed = False
        return len(calls) >= 3

    monkeypatch.setattr(engine, "_play_run", play_run)

    async def scenario():
        engine._max_runs = 1
        await engine._stage(adapter.session_id)

    _run(scenario())
    assert len(calls) == 3
    assert engine.status()["progress"]["stageRuns"] == 1


def test_stage_stops_after_two_retries(monkeypatch):
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [_item("开始", 0.45, 0.82)])
    calls: list[int] = []

    async def play_run(_session_id, **_kwargs):
        calls.append(1)
        engine._last_run_failed = False
        return False

    monkeypatch.setattr(engine, "_play_run", play_run)

    async def scenario():
        engine._max_runs = 1
        await engine._stage(adapter.session_id)

    _run(scenario())
    assert len(calls) == 3
    assert engine.status()["progress"]["stageRuns"] == 0
    assert any("仍未结算" in log["message"] for log in engine.status()["logs"])


def test_stage_does_not_retry_real_failure(monkeypatch):
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [_item("开始", 0.45, 0.82)])
    calls: list[int] = []

    async def play_run(_session_id, **_kwargs):
        calls.append(1)
        engine._last_run_failed = True
        return False

    monkeypatch.setattr(engine, "_play_run", play_run)

    async def scenario():
        engine._max_runs = 1
        await engine._stage(adapter.session_id)

    _run(scenario())
    # 真实失败不重试同一局，但会再开一局；连续失败 2 次后停止
    assert len(calls) == 2
    assert engine.status()["progress"]["stageFails"] == 2


def test_play_run_timeout_is_not_game_failure():
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [_item("下一天", 0.50, 0.906)])
    engine._max_run_seconds = 0.002

    async def scenario():
        return await engine._play_run(adapter.session_id)

    assert _run(scenario()) is False
    assert engine._last_run_failed is False


def test_bootstrap_stage_retries_unsettled_run(monkeypatch):
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [_item("开始", 0.45, 0.82)])
    calls: list[int] = []

    async def play_run(_session_id, **_kwargs):
        calls.append(1)
        engine._last_run_failed = False
        return len(calls) >= 2

    monkeypatch.setattr(engine, "_play_run", play_run)

    async def scenario():
        engine._max_runs = 1
        await engine._bootstrap_stage(adapter.session_id)

    _run(scenario())
    status = engine.status()["progress"]
    assert len(calls) == 2
    assert status["stageRuns"] == 1
    assert status["stageFails"] == 0


def test_bootstrap_stage_stops_after_retries_without_failure(monkeypatch):
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [_item("开始", 0.45, 0.82)])
    calls: list[int] = []

    async def play_run(_session_id, **_kwargs):
        calls.append(1)
        engine._last_run_failed = False
        return False

    monkeypatch.setattr(engine, "_play_run", play_run)

    async def scenario():
        engine._max_runs = 1
        await engine._bootstrap_stage(adapter.session_id)

    _run(scenario())
    status = engine.status()["progress"]
    assert len(calls) == 3
    assert status["stageRuns"] == 0
    assert status["stageFails"] == 0
    assert any("仍未结算" in log["message"] for log in engine.status()["logs"])


def test_retry_skips_abandoned_stage():
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [_item("开始", 0.45, 0.82)])

    async def scenario():
        engine._max_stage_fails = 2
        engine._progress.stage_fail_streak = 2
        await engine._retry_stage(adapter.session_id)

    _run(scenario())
    assert adapter.taps == []
    assert any("不再尝试" in log["message"] for log in engine.status()["logs"])


def test_server_sweep_dry_run_lists_range():
    adapter = FakeAdapter()
    screen = [
        _item("服务器", 0.50, 0.30),
        _item("闲云野鹤1区", 0.30, 0.45),
        _item("闲云野鹤2区", 0.30, 0.55),
        _item("最新区", 0.30, 0.65),
    ]
    engine = _engine(adapter, lambda _png: screen)

    async def scenario():
        engine._server_from = "闲云野鹤1区"
        engine._server_dry_run = True
        await engine._server_sweep(adapter.session_id)

    _run(scenario())
    status = engine.status()
    assert status["progress"]["serversDone"] == 0
    assert any("不执行切换" in log["message"] for log in status["logs"])
    assert any("闲云野鹤2区" in log["message"] for log in status["logs"])


def test_bootstrap_runs_daily_first_then_mainline(monkeypatch):
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    calls = []

    def recorder(name):
        async def run(_session_id):
            calls.append(name)
            return name in {"_ensure_adventure", "_back_to_adventure"}

        return run

    async def collect(_session_id, config):
        calls.append(f"collect:{config.name}")

    names = (
        "_ensure_adventure",
        "_baseline",
        "_dungeons",
        "_tower_bootstrap",
        "_travel",
        "_bootstrap_stage",
        "_upgrade",
        "_retry_stage",
        "_back_to_adventure",
    )
    for name in names:
        monkeypatch.setattr(engine, name, recorder(name))
    monkeypatch.setattr(engine, "_collect_entries", collect)
    monkeypatch.setattr(engine, "_guild", recorder("_guild"))
    monkeypatch.setattr(engine, "_daily_specials", recorder("_daily_specials"))

    async def scenario():
        await engine._bootstrap(adapter.session_id)

    _run(scenario())
    assert calls == [
        "_ensure_adventure",
        "_baseline",
        "collect:日常",
        "_daily_specials",
        "_guild",
        "collect:船",
        "_dungeons",
        "_tower_bootstrap",
        "_travel",
        "_bootstrap_stage",
        "_upgrade",
        "_retry_stage",
        "_back_to_adventure",
    ]


def test_back_to_adventure_from_tower_uses_arrow_twice():
    adapter = FakeAdapter()
    screens = [
        [_item("第2层", 0.50, 0.30), _item("889.7K", 0.51, 0.646), _item("挑战", 0.50, 0.945)],
        [_item("挑战之塔", 0.25, 0.12), _item("挑战", 0.65, 0.97)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        assert await engine._back_to_adventure(adapter.session_id)

    _run(scenario())
    assert adapter.taps == [(0.098, 0.955), (0.098, 0.955)]


def test_back_to_adventure_never_presses_android_back():
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])

    async def scenario():
        assert not await engine._back_to_adventure(adapter.session_id)

    _run(scenario())
    assert adapter.keys == []


def test_parse_compact_power_ignores_other_top_resources():
    engine = _engine(FakeAdapter(), lambda _png: [])
    screen = engine_module.Screen(
        [
            _item("698/32", 0.30, 0.055),
            _item("267.1K", 0.20, 0.088),
            _item("461.5K", 0.75, 0.055),
        ]
    )
    assert engine._parse_power(screen) == 267100


def test_growth_failed_settlement_is_not_counted_as_success(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [_item("失败", 0.50, 0.20), _item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine.start(adapter.session_id, task="growth", max_runs=1, tower_floors=0)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["stageRuns"] == 0
    # 失败不记成功；连续两局失败后停止
    assert status["progress"]["stageFails"] == 2
    assert len(adapter.taps) >= 2


def test_travel_skips_when_stamina_is_unknown(monkeypatch):
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [_item("游历", 0.50, 0.748)])

    async def back_to_adventure(_session_id):
        return True

    monkeypatch.setattr(engine, "_back_to_adventure", back_to_adventure)

    async def scenario():
        engine._travel_stamina = 100
        await engine._travel(adapter.session_id)

    _run(scenario())
    assert adapter.taps == []
    assert engine.status()["progress"]["travelSpent"] == 0


def test_dungeons_skip_zero_remaining_and_locked_entries(monkeypatch):
    adapter = FakeAdapter()
    listing = engine_module.Screen(
        [
            _item("突袭巨龙巢穴", 0.24, 0.12),
            _item("剩余次数", 0.28, 0.18),
            _item("突袭星界树", 0.24, 0.26),
            _item("剩余次数", 0.28, 0.32),
            _item("突袭幻剑空岛", 0.24, 0.40),
            _item("剩余次数", 0.28, 0.46),
            _item("突袭潮汐神殿", 0.24, 0.54),
            _item("在第21章生存1天后解锁", 0.54, 0.57),
            _item("剩余次数", 0.28, 0.60),
        ]
    )
    engine = _engine(adapter, lambda _png: [])
    play_calls = []
    open_calls = []
    back_calls = []

    async def open_activity_tab(_session_id, _tab):
        open_calls.append(1)
        return listing

    async def read(_session_id, region=None):
        if region is not None:
            count = "2" if region[1] > 0.55 else "0"
            return engine_module.Screen([_item(count, 0.30, (region[1] + region[3]) / 2)])
        return engine_module.Screen([_item("挑战", 0.50, 0.90)])

    async def play_run(_session_id):
        play_calls.append(1)
        return True

    async def back_to_adventure(_session_id):
        back_calls.append(1)
        return True

    monkeypatch.setattr(engine, "_open_activity_tab", open_activity_tab)
    monkeypatch.setattr(engine, "_read", read)
    monkeypatch.setattr(engine, "_play_run", play_run)
    monkeypatch.setattr(engine, "_back_to_adventure", back_to_adventure)

    async def scenario():
        await engine._dungeons(adapter.session_id)

    _run(scenario())
    assert play_calls == []
    assert engine.status()["progress"]["dungeonsDone"] == 0
    assert len(open_calls) == 1
    assert len(back_calls) == 1


def test_bootstrap_tower_skips_above_current_power(monkeypatch):
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    play_calls = []

    async def open_activity_tab(_session_id, _tab):
        return engine_module.Screen([_item("挑战之塔", 0.25, 0.12)])

    async def read(_session_id):
        return engine_module.Screen(
            [_item("889.7K", 0.51, 0.646), _item("挑战", 0.50, 0.945)]
        )

    async def play_run(_session_id):
        play_calls.append(1)
        return True

    monkeypatch.setattr(engine, "_open_activity_tab", open_activity_tab)
    monkeypatch.setattr(engine, "_read", read)
    monkeypatch.setattr(engine, "_play_run", play_run)

    async def scenario():
        engine._tower_floors = 1
        engine._progress.power = 267100
        await engine._tower_bootstrap(adapter.session_id)

    _run(scenario())
    assert play_calls == []
    assert engine.status()["progress"]["towerFloors"] == 0


def test_bootstrap_tower_stops_on_unconfirmed_page(monkeypatch):
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    play_calls = []

    async def open_activity_tab(_session_id, _tab):
        return engine_module.Screen([_item("挑战之塔", 0.25, 0.12)])

    async def read(_session_id):
        return engine_module.Screen(
            [
                _item("竞技", 0.43, 0.97),
                _item("挑战", 0.65, 0.97),
                _item("副本", 0.88, 0.97),
            ]
        )

    async def play_run(_session_id):
        play_calls.append(1)
        return True

    monkeypatch.setattr(engine, "_open_activity_tab", open_activity_tab)
    monkeypatch.setattr(engine, "_read", read)
    monkeypatch.setattr(engine, "_play_run", play_run)

    async def scenario():
        engine._tower_floors = 1
        engine._progress.power = 267100
        await engine._tower_bootstrap(adapter.session_id)

    _run(scenario())
    assert play_calls == []
    assert len(adapter.taps) == 1
    assert abs(adapter.taps[0][1] - 0.12) < 0.001
    assert any("未确认挑战之塔页" in log["message"] for log in engine.status()["logs"])


def test_travel_confirms_20x_tier_and_settlement(monkeypatch):
    adapter = FakeAdapter()
    screens = [
        [_item("768/32", 0.30, 0.055), _item("游历", 0.50, 0.748)],
        [_item("1倍奖励", 0.50, 0.83), _item("开始游历", 0.50, 0.90)],
        [_item("3倍奖励", 0.50, 0.83), _item("开始游历", 0.50, 0.90)],
        [_item("5倍奖励", 0.50, 0.83), _item("开始游历", 0.50, 0.90)],
        [_item("10倍奖励", 0.50, 0.83), _item("开始游历", 0.50, 0.90)],
        [_item("20倍奖励", 0.50, 0.83), _item("开始游历", 0.50, 0.90)],
        [_item("游历结束", 0.50, 0.30), _item("返回", 0.50, 0.85)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def ensure_adventure(_session_id):
        return None

    async def back_to_adventure(_session_id):
        return True

    monkeypatch.setattr(engine, "_ensure_adventure", ensure_adventure)
    monkeypatch.setattr(engine, "_back_to_adventure", back_to_adventure)

    async def scenario():
        engine._travel_stamina = 100
        await engine._travel(adapter.session_id)

    _run(scenario())
    plus_taps = [point for point in adapter.taps if point == (0.725, 0.835)]
    assert len(plus_taps) == 4
    assert engine.status()["progress"]["travelSpent"] == 100


def test_upgrade_uses_talents_and_one_key_strengthen(monkeypatch):
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [_item("天赋", 0.67, 0.98), _item("等级5", 0.50, 0.72), _item("等级0", 0.81, 0.72)],
        [_item("天赋", 0.67, 0.98), _item("等级6", 0.50, 0.72), _item("等级0", 0.81, 0.72)],
        [_item("天赋", 0.67, 0.98), _item("等级6", 0.50, 0.72), _item("等级1", 0.81, 0.72)],
        [_item("装备", 0.25, 0.98), _item("守护指环", 0.13, 0.23)],
        [
            _item("装备", 0.25, 0.98),
            _item("守护指环", 0.50, 0.27),
            _item("10/20", 0.44, 0.39),
            _item("卸下", 0.50, 0.73),
            _item("一键强化", 0.79, 0.73),
        ],
        [
            _item("装备", 0.25, 0.98),
            _item("守护指环", 0.50, 0.27),
            _item("11/20", 0.44, 0.39),
            _item("卸下", 0.50, 0.73),
            _item("一键强化", 0.79, 0.73),
        ],
        [_item("装备", 0.25, 0.98)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def ensure_adventure(_session_id):
        return None

    monkeypatch.setattr(engine, "_ensure_adventure", ensure_adventure)

    async def scenario():
        await engine._upgrade(adapter.session_id)

    _run(scenario())
    assert engine.status()["progress"]["upgradeSteps"] == 3
    assert (0.79, 0.73) in adapter.taps
    assert (0.50, 0.73) not in adapter.taps


def test_parse_compact_power_ignores_top_left_gems():
    engine = _engine(FakeAdapter(), lambda _png: [])
    screen = engine_module.Screen(
        [
            _item("693/34", 0.13, 0.065),
            _item("15K", 0.334, 0.065),
            _item("405.9K", 0.54, 0.065),
        ]
    )
    assert engine._parse_power(screen) is None


def test_bootstrap_stops_when_adventure_is_not_confirmed(monkeypatch):
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    baseline_calls = []

    async def ensure_adventure(_session_id):
        return False

    async def baseline(_session_id):
        baseline_calls.append(1)

    monkeypatch.setattr(engine, "_ensure_adventure", ensure_adventure)
    monkeypatch.setattr(engine, "_baseline", baseline)

    async def scenario():
        with pytest.raises(engine_module.AutomationUnavailable):
            await engine._bootstrap(adapter.session_id)

    _run(scenario())
    assert baseline_calls == []


def test_bootstrap_stop_prevents_remaining_phases(monkeypatch):
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    calls = []

    async def ensure_adventure(_session_id):
        calls.append("_ensure_adventure")
        return True

    async def baseline(_session_id):
        calls.append("_baseline")

    async def dungeons(_session_id):
        calls.append("_dungeons")
        engine._stopping = True

    async def tower(_session_id):
        calls.append("_tower_bootstrap")

    async def collect(_session_id, config):
        calls.append(f"collect:{config.name}")

    async def guild(_session_id):
        calls.append("_guild")

    monkeypatch.setattr(engine, "_ensure_adventure", ensure_adventure)
    monkeypatch.setattr(engine, "_baseline", baseline)
    monkeypatch.setattr(engine, "_dungeons", dungeons)
    monkeypatch.setattr(engine, "_tower_bootstrap", tower)
    async def daily_specials(_session_id):
        calls.append("_daily_specials")

    monkeypatch.setattr(engine, "_collect_entries", collect)
    monkeypatch.setattr(engine, "_guild", guild)
    monkeypatch.setattr(engine, "_daily_specials", daily_specials)

    async def scenario():
        await engine._bootstrap(adapter.session_id)

    _run(scenario())
    assert calls == [
        "_ensure_adventure",
        "_baseline",
        "collect:日常",
        "_daily_specials",
        "_guild",
        "collect:船",
        "_dungeons",
    ]


def test_travel_does_not_start_after_stop():
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])

    async def scenario():
        engine._stopping = True
        engine._travel_stamina = 100
        await engine._travel(adapter.session_id)

    _run(scenario())
    assert adapter.taps == []


def test_back_to_adventure_uses_bottom_nav_on_shop():
    adapter = FakeAdapter()
    screens = [
        [_item("商城", 0.15, 0.986), _item("充值", 0.86, 0.875)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        assert await engine._back_to_adventure(adapter.session_id)

    _run(scenario())
    assert adapter.taps[0] == (0.5, 0.954)


# ---------- 推关快速模式：录制坐标 + 定时回放 ----------


def _fast_engine(adapter, ocr, *, check_every=8, script_path=None, max_run_seconds=0.02):
    """带可观测 sleep 的引擎，用于验证回放的定时点击与校验频率"""

    ticks = {"n": 0}
    sleeps: list[float] = []

    def clock():
        ticks["n"] += 1
        return ticks["n"] * 0.001

    async def sleep(seconds):
        sleeps.append(seconds)

    engine = AutomationEngine(
        lambda: adapter,
        ocr=ocr,
        sleep=sleep,
        clock=clock,
        max_run_seconds=max_run_seconds,
        stage_script_path=script_path,
    )
    engine._fast_stage = True
    engine._fast_stage_check_every = check_every
    return engine, sleeps


def _stage_taps(count, x=0.5, y=0.906, gap=0.4):
    return [engine_module.StageTap(x, y, gap) for _ in range(count)]


def test_fast_stage_replays_recorded_positions_on_timer(tmp_path):
    adapter = FakeAdapter()
    engine, sleeps = _fast_engine(
        adapter, lambda _png: [], check_every=99, script_path=tmp_path / "stage.json"
    )
    engine._stage_script = [
        engine_module.StageTap(0.5, 0.906, 0.4),
        engine_module.StageTap(0.35, 0.404, 0.9),
    ]

    async def scenario():
        return await engine._replay_stage(adapter.session_id)

    assert _run(scenario()) is None
    assert len(adapter.taps) == 2
    for (x, y), (ex, ey) in zip(adapter.taps, [(0.5, 0.906), (0.35, 0.404)]):
        assert x == pytest.approx(ex, abs=0.006)
        assert y == pytest.approx(ey, abs=0.006)
    assert sleeps[0] == pytest.approx(0.4, rel=0.2)
    assert sleeps[1] == pytest.approx(0.9, rel=0.2)


def test_choice_option_prefers_rightmost():
    engine = _engine(FakeAdapter(), lambda _png: [])
    screen = engine_module.Screen(
        [_item("休息", 0.28, 0.905), _item("搜索", 0.70, 0.905)]
    )
    option = engine._choice_option(screen)
    assert option is not None
    assert option.text == "搜索"


def test_replay_interleaves_option_anchor(tmp_path):
    adapter = FakeAdapter()
    engine, sleeps = _fast_engine(
        adapter, lambda _png: [], check_every=99, script_path=tmp_path / "stage.json"
    )
    engine._stage_script = [
        engine_module.StageTap(0.5, 0.906, 0.4, "next"),
        engine_module.StageTap(0.7, 0.905, 0.4, "option"),
        engine_module.StageTap(0.5, 0.906, 0.4, "next"),
    ]

    async def scenario():
        return await engine._replay_stage(adapter.session_id)

    assert _run(scenario()) is None
    # 两个 next 锚点各补一次右侧选项锚点
    assert len(adapter.taps) == 4
    expected = [(0.5, 0.906), (0.7, 0.905), (0.5, 0.906), (0.7, 0.905)]
    for (x, y), (ex, ey) in zip(adapter.taps, expected):
        assert x == pytest.approx(ex, abs=0.006)
        assert y == pytest.approx(ey, abs=0.006)
    assert any(0.12 <= value <= 0.28 for value in sleeps)


def test_choice_option_avoids_dangerous_option():
    engine = _engine(FakeAdapter(), lambda _png: [])
    screen = engine_module.Screen(
        [
            _item("保持安静", 0.266, 0.922),
            _item("战斗（危险！）", 0.724, 0.921),
        ]
    )
    option = engine._choice_option(screen)
    assert option is not None
    assert option.text == "保持安静"


def test_stage_script_roundtrip_keeps_option_kind(tmp_path):
    adapter = FakeAdapter()
    engine, _ = _fast_engine(
        adapter, lambda _png: [], check_every=99, script_path=tmp_path / "stage.json"
    )
    engine._stage_script = [
        engine_module.StageTap(0.5, 0.906, 1.0, "next"),
        engine_module.StageTap(0.7, 0.905, 1.0, "option"),
    ]
    engine._save_stage_script()
    loaded = engine._load_stage_script()
    assert [tap.kind for tap in loaded] == ["next", "option"]


def test_fast_stage_validates_every_n_taps(tmp_path):
    adapter = FakeAdapter()
    reads = {"n": 0}

    def read(_png):
        reads["n"] += 1
        return [_item("战斗中", 0.50, 0.90)]

    engine, _ = _fast_engine(
        adapter, read, check_every=3, script_path=tmp_path / "stage.json"
    )
    engine._stage_script = _stage_taps(7)

    async def scenario():
        return await engine._replay_stage(adapter.session_id)

    assert _run(scenario()) is None
    assert len(adapter.taps) == 7
    assert reads["n"] == 2  # 第 3、6 次点击后各校验一次


def test_fast_stage_stops_after_settlement(tmp_path):
    adapter = FakeAdapter()

    def read(_png):
        return [_item("胜利", 0.50, 0.30), _item("返回主城", 0.50, 0.90)]

    engine, _ = _fast_engine(
        adapter, read, check_every=1, script_path=tmp_path / "stage.json"
    )
    engine._stage_script = _stage_taps(5)
    back_calls: list[str] = []

    async def back(session_id):
        back_calls.append(session_id)
        return True

    engine._back_to_adventure = back

    async def scenario():
        return await engine._replay_stage(adapter.session_id)

    assert _run(scenario()) is True
    assert back_calls == [adapter.session_id]
    assert len(adapter.taps) == 2  # 一次回放 + 一次结算返回，未继续点完序列
    assert any("关卡结算" in log["message"] for log in engine.status()["logs"])


def test_fast_stage_marks_real_failure(tmp_path):
    adapter = FakeAdapter()

    def read(_png):
        return [_item("失败", 0.50, 0.30), _item("返回主城", 0.50, 0.90)]

    engine, _ = _fast_engine(
        adapter, read, check_every=1, script_path=tmp_path / "stage.json"
    )
    engine._stage_script = _stage_taps(5)

    async def back(_session_id):
        return True

    engine._back_to_adventure = back

    async def scenario():
        return await engine._replay_stage(adapter.session_id)

    assert _run(scenario()) is True
    assert engine._last_run_failed is True


def test_fast_stage_falls_back_when_off_track(tmp_path):
    adapter = FakeAdapter()
    engine, _ = _fast_engine(
        adapter,
        lambda _png: [_item("商城", 0.50, 0.90)],
        check_every=1,
        script_path=tmp_path / "stage.json",
    )
    engine._stage_script = _stage_taps(5)

    async def scenario():
        return await engine._replay_stage(adapter.session_id)

    assert _run(scenario()) is None
    assert any("切回逐帧识别" in log["message"] for log in engine.status()["logs"])


def test_play_run_skips_ocr_when_replay_settles(tmp_path, monkeypatch):
    adapter = FakeAdapter()
    engine, _ = _fast_engine(
        adapter, lambda _png: [], check_every=99, script_path=tmp_path / "stage.json"
    )
    engine._stage_script = _stage_taps(1)
    called = {"ocr": False}

    async def replay(_session_id):
        return True

    async def ocr_loop(_session_id):
        called["ocr"] = True
        return False

    monkeypatch.setattr(engine, "_replay_stage", replay)
    monkeypatch.setattr(engine, "_play_run_ocr", ocr_loop)

    async def scenario():
        return await engine._play_run(adapter.session_id, replay=True, record=True)

    assert _run(scenario()) is True
    assert called["ocr"] is False


def test_play_run_without_replay_flag_keeps_ocr_loop(tmp_path, monkeypatch):
    adapter = FakeAdapter()
    engine, _ = _fast_engine(
        adapter, lambda _png: [], check_every=99, script_path=tmp_path / "stage.json"
    )
    engine._stage_script = _stage_taps(3)

    async def replay(_session_id):
        raise AssertionError("未标记 replay 时不应回放录制坐标")

    async def ocr_loop(_session_id):
        return True

    monkeypatch.setattr(engine, "_replay_stage", replay)
    monkeypatch.setattr(engine, "_play_run_ocr", ocr_loop)

    async def scenario():
        return await engine._play_run(adapter.session_id, record=True)

    assert _run(scenario()) is True


def test_fast_stage_records_taps_of_stage_run(tmp_path):
    adapter = FakeAdapter()
    path = tmp_path / "stage.json"

    def read(_png):
        if not adapter.taps:
            return [
                _item("选择技能", 0.50, 0.24),
                _item("普攻剑气", 0.35, 0.404),
                _item("从下方选择一个技能", 0.50, 0.376),
                _item("0/1选择技能", 0.50, 0.822),
            ]
        if len(adapter.taps) == 1:
            return [
                _item("选择技能", 0.50, 0.24),
                _item("普攻剑气", 0.35, 0.404),
                _item("1/1选择技能", 0.50, 0.822),
            ]
        if len(adapter.taps) == 2:
            return [
                _item("神话技能", 0.50, 0.28),
                _item("大吉", 0.09, 0.94),
                _item("小吉", 0.91, 0.94),
            ]
        if len(adapter.taps) == 3:
            return [_item("下一天", 0.50, 0.906)]
        if len(adapter.taps) == 4:
            return [_item("返回主城", 0.50, 0.90)]
        return [_item("开始", 0.45, 0.82)]

    engine, _ = _fast_engine(adapter, read, check_every=99, script_path=path)

    async def scenario():
        return await engine._play_run(adapter.session_id, record=True)

    assert _run(scenario()) is True
    saved = json.loads(path.read_text("utf-8"))
    assert len(saved["taps"]) >= 5
    assert saved["taps"][0]["x"] == pytest.approx(0.35)
    assert all(0.05 <= tap["gap"] <= 2.0 for tap in saved["taps"])


def test_wait_categories_scale_only_animation():
    adapter = FakeAdapter()
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    engine = AutomationEngine(lambda: adapter, ocr=lambda _png: [], sleep=sleep)
    engine._speed = 0.5

    async def scenario():
        await engine._wait(1.0)
        await engine._wait(0.1)
        await engine._wait(0.8, "ocr_poll")
        await engine._wait(0.3, "debounce")

    _run(scenario())
    assert sleeps == [0.5, 0.2, 0.8, 0.3]


def test_travel_uses_20x_and_100_cost_when_threshold_is_20(monkeypatch):
    adapter = FakeAdapter()
    screens = [
        [_item("768/1000", 0.30, 0.055), _item("游历", 0.50, 0.748)],
        [_item("1倍奖励", 0.50, 0.83), _item("开始游历", 0.50, 0.90)],
        [_item("3倍奖励", 0.50, 0.83), _item("开始游历", 0.50, 0.90)],
        [_item("5倍奖励", 0.50, 0.83), _item("开始游历", 0.50, 0.90)],
        [_item("10倍奖励", 0.50, 0.83), _item("开始游历", 0.50, 0.90)],
        [_item("20倍奖励", 0.50, 0.83), _item("开始游历", 0.50, 0.90)],
        [_item("游历结束", 0.50, 0.30), _item("返回", 0.50, 0.85)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))
    monkeypatch.setattr(engine, "_ensure_adventure", _return_none)
    monkeypatch.setattr(engine, "_back_to_adventure", _return_true)

    async def scenario():
        engine._travel_stamina = 20
        assert await engine._travel(adapter.session_id)

    _run(scenario())
    assert engine.status()["progress"]["travelSpent"] == 100
    assert adapter.taps.count((0.725, 0.835)) == 4


def test_travel_without_20x_never_clicks_start(monkeypatch):
    adapter = FakeAdapter()
    screens = [
        [_item("768/1000", 0.30, 0.055), _item("游历", 0.50, 0.748)],
        [_item("4倍奖励", 0.50, 0.83), _item("开始游历", 0.50, 0.90)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))
    monkeypatch.setattr(engine, "_ensure_adventure", _return_none)
    monkeypatch.setattr(engine, "_back_to_adventure", _return_true)

    async def scenario():
        engine._travel_stamina = 20
        assert not await engine._travel(adapter.session_id)

    _run(scenario())
    assert (0.5, 0.90) not in adapter.taps
    assert engine.status()["progress"]["travelSpent"] == 0


def test_travel_never_blindly_changes_tier_before_panel_is_confirmed(monkeypatch):
    adapter = FakeAdapter()
    screens = [
        [_item("768/1000", 0.30, 0.055), _item("游历", 0.50, 0.748)],
        [_item("开始", 0.45, 0.82), _item("游历", 0.50, 0.748)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))
    monkeypatch.setattr(engine, "_ensure_adventure", _return_none)
    monkeypatch.setattr(engine, "_back_to_adventure", _return_true)

    async def scenario():
        engine._travel_stamina = 100
        assert not await engine._travel(adapter.session_id)

    _run(scenario())
    assert adapter.taps == [(0.5, 0.723)]
    assert engine.status()["progress"]["travelSpent"] == 0


def test_travel_does_not_repeat_plus_on_unchanged_tier(monkeypatch):
    adapter = FakeAdapter()
    screens = [
        [_item("768/1000", 0.30, 0.055), _item("游历", 0.50, 0.748)],
        [_item("1倍奖励", 0.50, 0.83), _item("开始游历", 0.50, 0.90)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))
    monkeypatch.setattr(engine, "_ensure_adventure", _return_none)
    monkeypatch.setattr(engine, "_back_to_adventure", _return_true)

    async def scenario():
        engine._travel_stamina = 100
        assert not await engine._travel(adapter.session_id)

    _run(scenario())
    assert adapter.taps == [(0.5, 0.723), (0.725, 0.835)]
    assert engine.status()["progress"]["travelSpent"] == 0


def test_back_to_adventure_from_privilege_card_uses_back_arrow():
    adapter = FakeAdapter()
    screens = [
        [
            _item("每日福利", 0.20, 0.13),
            _item("购买后立即获得", 0.18, 0.50),
            _item("购买68元", 0.80, 0.55),
        ],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        assert await engine._back_to_adventure(adapter.session_id)

    _run(scenario())
    assert adapter.taps == [(0.098, 0.955)]


def test_back_to_adventure_from_privilege_card_without_daily_welfare():
    adapter = FakeAdapter()
    screens = [
        [
            _item("免广告卡", 0.18, 0.25),
            _item("月卡", 0.13, 0.53),
            _item("终身卡", 0.16, 0.86),
            _item("购买后立即获得", 0.18, 0.38),
            _item("购买68元", 0.79, 0.43),
            _item("购买30元", 0.79, 0.76),
            _item("领取全部", 0.50, 0.96),
        ],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        assert await engine._back_to_adventure(adapter.session_id)

    _run(scenario())
    assert adapter.taps == [(0.098, 0.955)]


def test_back_to_adventure_from_paid_shop_never_blind_taps_close_positions():
    adapter = FakeAdapter()
    screens = [
        [
            _item("每日特惠", 0.69, 0.13),
            _item("福利礼包", 0.26, 0.40),
            _item("超值礼包", 0.74, 0.40),
            _item("30元", 0.82, 0.26),
            _item("6元", 0.74, 0.57),
            _item("12元", 0.26, 0.81),
            _item("18元", 0.74, 0.81),
        ],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        assert await engine._back_to_adventure(adapter.session_id)

    _run(scenario())
    assert adapter.taps == [(0.098, 0.955)]


def test_bootstrap_fails_when_main_city_not_confirmed_at_end(monkeypatch):
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])

    async def _ok(*_args, **_kwargs):
        return True

    async def _not_found(*_args, **_kwargs):
        return False

    monkeypatch.setattr(engine, "_ensure_adventure", _return_true)
    monkeypatch.setattr(engine, "_baseline", _ok)
    monkeypatch.setattr(engine, "_collect_and_record", _ok)
    monkeypatch.setattr(engine, "_dungeons", _ok)
    monkeypatch.setattr(engine, "_tower_bootstrap", _ok)
    monkeypatch.setattr(engine, "_travel", _ok)
    monkeypatch.setattr(engine, "_bootstrap_stage", _ok)
    monkeypatch.setattr(engine, "_upgrade", _ok)
    monkeypatch.setattr(engine, "_retry_stage", _ok)
    monkeypatch.setattr(engine, "_back_to_adventure", _not_found)

    async def scenario():
        with pytest.raises(engine_module.AutomationUnavailable, match="冒险页"):
            await engine._bootstrap(adapter.session_id)

    _run(scenario())


def test_switch_account_clears_popup_on_current_account_first():
    """当前账号主城被钥匙特惠弹窗挡住时，先清弹窗再判定同一账号"""
    adapter = FakeAdapter()
    screens = [
        [
            _item("风零", 0.16, 0.057),
            _item("钥匙特惠", 0.50, 0.30),
            _item("68元", 0.49, 0.63),
            _item("冒险", 0.50, 0.986),
        ],
        [_item("风零", 0.16, 0.057), _item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        assert await engine._switch_account(adapter.session_id, "风零")

    _run(scenario())
    assert adapter.taps[0][0] > 0.4 and 0.8 < adapter.taps[0][1] < 0.9


def test_switch_account_closes_promo_popup_before_verify():
    """切号成功后出现「钥匙特惠」付费弹窗时，先关闭弹窗再核验主城"""
    adapter = FakeAdapter()
    screens = [
        [_item("风壹", 0.16, 0.057), _item("开始", 0.45, 0.82)],
        [_item("个人信息", 0.50, 0.20), _item("选择服务器", 0.50, 0.30)],
        [_item("最近登录", 0.50, 0.40), _item("风零", 0.50, 0.55)],
        [_item("开始游戏", 0.50, 0.78)],
        [
            _item("风零", 0.16, 0.057),
            _item("钥匙特惠", 0.50, 0.30),
            _item("68元", 0.49, 0.63),
            _item("免费", 0.54, 0.78),
            _item("冒险", 0.50, 0.986),
        ],
        [_item("风零", 0.16, 0.057), _item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        assert await engine._switch_account(adapter.session_id, "风零")

    _run(scenario())
    popup_closes = {(0.5, 0.83), (0.5, 0.852), (0.5, 0.887), (0.5, 0.868)}
    assert popup_closes & set(adapter.taps), f"未点击弹窗关闭位: {adapter.taps}"
    assert engine.status()["progress"]["accountsCreated"] == 0


def test_pick_skills_ignore_misread_rarity_label():
    """「普通」被 OCR 误读为「音通」时，不能当成技能卡点击"""
    adapter = FakeAdapter()
    screen = [
        _item("选择技能", 0.50, 0.34),
        _item("从下方选择一个技能", 0.50, 0.38),
        _item("音通", 0.15, 0.41),
        _item("普攻强化", 0.35, 0.42),
        _item("音通", 0.15, 0.56),
        _item("反击光枪", 0.35, 0.57),
        _item("选择技能", 0.50, 0.91),
    ]
    engine = _engine(adapter, lambda _png: screen)
    cards = engine._skill_cards(engine_module.Screen(list(screen)))
    texts = [card.text for card in cards]
    assert "音通" not in texts
    assert "普攻强化" in texts
    assert "反击光枪" in texts


def _call_scripted_ocr(screens):
    """按读屏调用次数推进的预设屏幕：同一点击次数下可以出现不同帧（弹窗动画）"""

    calls = {"n": 0}

    def read(_png):
        index = min(calls["n"], len(screens) - 1)
        calls["n"] += 1
        return screens[index]

    return read


def test_guild_retries_read_until_donate_dialog_confirmed():
    """点「捐献」后弹窗有动画，OCR 旧帧不能直接放弃，需重读确认"""
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [_item("公会大厅", 0.50, 0.32)],
        [_item("公会信息", 0.50, 0.18), _item("捐献", 0.50, 0.79)],
        [_item("公会信息", 0.50, 0.18), _item("捐献", 0.50, 0.79)],
        [_item("公会捐献", 0.50, 0.40), _item("免费", 0.50, 0.65)],
        [_item("奖励", 0.50, 0.41), _item("点击关闭", 0.50, 0.89)],
        [_item("公会信息", 0.50, 0.18), _item("捐献", 0.50, 0.79)],
        [_item("公会大厅", 0.50, 0.32)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _call_scripted_ocr(screens))

    async def scenario():
        await engine._guild(adapter.session_id)

    _run(scenario())
    assert engine.status()["progress"]["guildSteps"] == 1


def test_guild_closes_donate_dialog_when_free_unavailable():
    """免费次数用完后，先关掉捐献弹窗再返回主城，避免后续全部「未能确认冒险页」"""
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [_item("公会大厅", 0.50, 0.32)],
        [_item("公会信息", 0.50, 0.18), _item("捐献", 0.50, 0.79)],
        [_item("公会捐献", 0.50, 0.40), _item("今日剩余次数：0", 0.50, 0.69)],
        [_item("公会信息", 0.50, 0.18), _item("捐献", 0.50, 0.79)],
        [_item("公会大厅", 0.50, 0.32)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _call_scripted_ocr(screens))

    async def scenario():
        await engine._guild(adapter.session_id)

    _run(scenario())
    assert (0.5, 0.78) in adapter.taps
    assert engine.status()["progress"]["guildSteps"] == 0


def test_guild_free_donation_full_flow():
    """已加入公会：图标进公会地图 → 公会大厅 → 捐献 → 免费捐献"""
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [_item("公会大厅", 0.50, 0.32), _item("公会远征", 0.24, 0.41)],
        [_item("公会信息", 0.50, 0.18), _item("捐献", 0.50, 0.79), _item("公会管理", 0.78, 0.79)],
        [_item("公会捐献", 0.50, 0.40), _item("免费", 0.50, 0.65), _item("今日剩余次数：5", 0.50, 0.69)],
        [_item("奖励", 0.50, 0.41), _item("点击关闭", 0.50, 0.89)],
        [_item("公会信息", 0.50, 0.18), _item("捐献", 0.50, 0.79)],
        [_item("公会大厅", 0.50, 0.32)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine._guild(adapter.session_id)

    _run(scenario())
    assert engine.status()["progress"]["guildSteps"] == 1
    assert (0.08, 0.80) in adapter.taps
    assert (0.5, 0.65) in adapter.taps


def test_guild_skips_when_free_donation_exhausted():
    """免费次数用完后按钮变为宝石消耗，没有「免费」文字绝不点击"""
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [_item("公会大厅", 0.50, 0.32)],
        [_item("公会信息", 0.50, 0.18), _item("捐献", 0.50, 0.79)],
        [_item("公会捐献", 0.50, 0.40), _item("25", 0.50, 0.65), _item("今日剩余次数：0", 0.50, 0.69)],
        [_item("公会大厅", 0.50, 0.32)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine._guild(adapter.session_id)

    _run(scenario())
    assert engine.status()["progress"]["guildSteps"] == 0
    assert (0.5, 0.65) not in adapter.taps


def test_guild_skips_when_not_joined():
    """未加入公会：点击图标后仍未确认公会地图，跳过且不乱点"""
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        await engine._guild(adapter.session_id)

    _run(scenario())
    assert engine.status()["progress"]["guildSteps"] == 0
    assert adapter.taps == [(0.08, 0.80)]


def test_back_to_adventure_closes_gift_popup_before_finalize():
    adapter = FakeAdapter()
    screens = [
        [
            _item("开始", 0.45, 0.82),
            _item("武器特惠礼包", 0.50, 0.25),
            _item("购买后立即获得", 0.18, 0.50),
        ],
        [
            _item("开始", 0.45, 0.82),
            _item("限时体力礼包", 0.50, 0.40),
            _item("购买时间", 0.30, 0.50),
        ],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        assert await engine._back_to_adventure(adapter.session_id)

    _run(scenario())
    assert adapter.taps == [(0.5, 0.83), (0.5, 0.886)]


def test_back_to_adventure_rejects_unknown_paid_page_before_finalize():
    adapter = FakeAdapter()
    engine = _engine(
        adapter,
        lambda _png: [
            _item("购买后立即获得", 0.18, 0.50),
            _item("购买68元", 0.80, 0.55),
        ],
    )

    async def scenario():
        with pytest.raises(engine_module.AutomationUnavailable, match="付费或广告"):
            await engine._back_to_adventure(adapter.session_id)

    _run(scenario())
    assert adapter.taps == []


def test_announcement_close_covers_verified_bottom_positions():
    adapter = FakeAdapter()
    screens = [[_item("公告", 0.50, 0.20)] for _ in range(5)] + [
        [_item("开始", 0.45, 0.82)]
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        assert await engine._back_to_adventure(adapter.session_id)

    _run(scenario())
    assert adapter.taps == [(0.5, y) for y in (0.83, 0.886, 0.768, 0.815, 0.868)]


def test_untitled_obelisk_wheel_is_not_retried_as_adventure(monkeypatch):
    adapter = FakeAdapter()
    screens = [
        [_item("你发现了一座方", 0.50, 0.30), _item("开始", 0.50, 0.832)],
        [_item("小吉", 0.50, 0.30), _item("点击关闭", 0.50, 0.90)],
        [_item("返回主城", 0.50, 0.90)],
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))
    monkeypatch.setattr(engine, "_back_to_adventure", _return_true)

    async def scenario():
        assert await engine._play_run_ocr(adapter.session_id)

    _run(scenario())
    assert not any("仍在冒险页" in log["message"] for log in engine.status()["logs"])


def test_switch_account_uses_exact_role_and_verifies_identity():
    adapter = FakeAdapter()
    screens = [
        [_item("风叁", 0.10, 0.06), _item("开始", 0.45, 0.82)],
        [_item("个人信息", 0.50, 0.20), _item("选择服务器", 0.73, 0.475)],
        [
            _item("最近登录", 0.25, 0.328),
            _item("风贰小号", 0.50, 0.40),
            _item("风贰", 0.50, 0.50),
        ],
        [_item("开始游戏", 0.50, 0.82)],
        [_item("风贰", 0.10, 0.06), _item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        assert await engine._switch_account(adapter.session_id, "风贰")

    _run(scenario())
    assert (0.5, 0.4) not in adapter.taps
    assert (0.5, 0.5) in adapter.taps
    assert adapter.taps[-1] == (0.5, 0.82)


def test_switch_account_closes_login_announcement_before_identity_check():
    adapter = FakeAdapter()
    screens = [
        [_item("风叁", 0.10, 0.06), _item("开始", 0.45, 0.82)],
        [_item("个人信息", 0.50, 0.20), _item("选择服务器", 0.73, 0.475)],
        [_item("最近登录", 0.25, 0.328), _item("风贰", 0.50, 0.50)],
        [_item("开始游戏", 0.50, 0.82)],
        [_item("风贰", 0.10, 0.06), _item("游戏公告", 0.50, 0.25)],
        [_item("风贰", 0.10, 0.06), _item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        assert await engine._switch_account(adapter.session_id, "风贰")

    _run(scenario())
    assert (0.5, 0.83) in adapter.taps


def test_switch_account_rejects_wrong_identity():
    adapter = FakeAdapter()
    screens = [
        [_item("风叁", 0.10, 0.06), _item("开始", 0.45, 0.82)],
        [_item("个人信息", 0.50, 0.20), _item("选择服务器", 0.73, 0.475)],
        [_item("最近登录", 0.25, 0.328), _item("风贰", 0.50, 0.50)],
        [_item("开始游戏", 0.50, 0.82)],
        [_item("风叁", 0.10, 0.06), _item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def scenario():
        assert not await engine._switch_account(adapter.session_id, "风贰")

    _run(scenario())


def test_account_sweep_resets_progress_and_assigns_independent_runs(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    calls = []

    async def switch(_session_id, account):
        calls.append(f"switch:{account}")
        return True

    async def bootstrap(_session_id):
        calls.append(f"bootstrap:{engine._account}")
        engine._progress.stage_runs = 1
        engine._progress.phase = "done"

    monkeypatch.setattr(engine, "_switch_account", switch, raising=False)
    monkeypatch.setattr(engine, "_bootstrap", bootstrap)

    async def scenario():
        await engine.start(
            adapter.session_id,
            task="account_sweep",
            accounts=["风贰", "风零"],
            max_runs=1,
        )
        await engine._task

    _run(scenario())
    assert calls == ["switch:风贰", "bootstrap:风贰", "switch:风零", "bootstrap:风零"]
    saved = {item["name"]: item["lastRun"] for item in accounts_module.load_accounts()}
    assert saved["风贰"]["status"] == saved["风零"]["status"] == "completed"
    assert saved["风贰"]["progress"]["stageRuns"] == 1
    assert saved["风零"]["progress"]["stageRuns"] == 1
    assert saved["风贰"]["runId"] != saved["风零"]["runId"]


def test_account_sweep_rejects_main_account(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    engine = _engine(FakeAdapter(), lambda _png: [])

    async def scenario():
        with pytest.raises(engine_module.AutomationUnavailable, match="你瞅啥呢"):
            await engine.start(
                "s1", task="account_sweep", accounts=["风贰", "你瞅啥呢"]
            )

    _run(scenario())
    assert engine._task is None


def test_account_sweep_failure_continues_to_remaining_accounts(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    calls = []

    async def switch(_session_id, account):
        return True

    async def bootstrap(_session_id):
        calls.append(engine._account)
        if engine._account == "风贰":
            raise engine_module.AutomationUnavailable("身份不符")

    monkeypatch.setattr(engine, "_switch_account", switch, raising=False)
    monkeypatch.setattr(engine, "_bootstrap", bootstrap)

    async def scenario():
        await engine.start(
            adapter.session_id, task="account_sweep", accounts=["风贰", "风零"]
        )
        await engine._task

    _run(scenario())
    # 单号失败只记 failed 状态，不阻断后续账号
    assert calls == ["风贰", "风零"]
    saved = {item["name"]: item["lastRun"] for item in accounts_module.load_accounts()}
    assert saved["风贰"]["status"] == "failed"
    assert saved["风贰"]["error"] == "身份不符"
    assert saved["风零"]["status"] == "completed"


def test_baseline_rejects_main_account_even_when_target_is_supplied():
    adapter = FakeAdapter()
    engine = _engine(
        adapter,
        lambda _png: [
            _item("你瞅啥呢", 0.10, 0.06),
            _item("768/1000", 0.30, 0.055),
            _item("开始", 0.45, 0.82),
        ],
    )
    engine._account = "风贰"

    async def scenario():
        with pytest.raises(engine_module.AutomationUnavailable, match="主账号"):
            await engine._baseline(adapter.session_id)

    _run(scenario())
    assert adapter.taps == []


def test_account_sweep_state_write_failure_prevents_bootstrap(monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    calls = []
    writes = {"n": 0}

    def record(*args, **kwargs):
        writes["n"] += 1
        if writes["n"] > 1:
            raise OSError("disk full")
        return accounts_module.record_account_run(*args, **kwargs)

    async def bootstrap(_session_id):
        calls.append(engine._account)

    monkeypatch.setattr(engine_module, "record_account_run", record)
    monkeypatch.setattr(engine, "_bootstrap", bootstrap)

    async def scenario():
        await engine.start(adapter.session_id, task="account_sweep", accounts=["风贰"])
        await engine._task

    _run(scenario())
    assert calls == []
    assert engine.status()["status"] == "error"
    assert "disk full" in engine.status()["error"]


def test_fast_stage_keeps_longest_recording(tmp_path):
    path = tmp_path / "stage.json"
    engine, _ = _fast_engine(
        FakeAdapter(), lambda _png: [], script_path=path
    )
    engine._recorded = _stage_taps(6, 0.5, 0.91, 0.5)
    engine._remember_recorded()
    assert len(engine._stage_script) == 6
    assert len(json.loads(path.read_text("utf-8"))["taps"]) == 6

    engine._recorded = _stage_taps(3, 0.1, 0.1, 0.5)
    engine._remember_recorded()
    assert len(engine._stage_script) == 6
    assert len(json.loads(path.read_text("utf-8"))["taps"]) == 6


def test_fast_stage_ignores_too_short_recording(tmp_path):
    path = tmp_path / "stage.json"
    engine, _ = _fast_engine(FakeAdapter(), lambda _png: [], script_path=path)
    engine._recorded = _stage_taps(3)

    engine._remember_recorded()

    assert engine._stage_script == []
    assert not path.exists()


def test_fast_stage_loads_script_from_disk(tmp_path):
    path = tmp_path / "stage.json"
    path.write_text(
        json.dumps({"taps": [{"x": 0.5, "y": 0.9, "gap": 0.7}, {"x": "bad"}]}),
        "utf-8",
    )
    engine = AutomationEngine(
        lambda: FakeAdapter(), ocr=lambda _png: [], sleep=_noop_sleep, stage_script_path=path
    )
    assert engine._stage_script == [engine_module.StageTap(0.5, 0.9, 0.7)]


def test_start_registers_account_without_completed_work(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    engine, _ = _fast_engine(adapter, lambda _png: [], script_path=tmp_path / "stage.json")

    async def scenario():
        await engine.start(adapter.session_id, task="daily", account="风陆")
        engine.stop()
        await engine._task

    _run(scenario())
    assert [item["name"] for item in accounts_module.account_summary()] == ["风陆"]
    assert accounts_module.account_summary()[0]["works"]["daily"]["done"] is False


def test_start_rejects_unknown_stage_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    engine, _ = _fast_engine(adapter, lambda _png: [], script_path=tmp_path / "stage.json")

    async def scenario():
        with pytest.raises(engine_module.AutomationUnavailable):
            await engine.start(adapter.session_id, task="growth", stage_mode="turbo")

    _run(scenario())


def test_all_task_runs_collects_before_stage(monkeypatch):
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    calls = []

    async def collect(_session_id, config):
        calls.append(config.name)

    async def growth(_session_id):
        calls.append("推关")

    monkeypatch.setattr(engine, "_collect_entries", collect)
    monkeypatch.setattr(engine, "_growth", growth)

    _run(engine._run(adapter.session_id, "all"))
    assert calls == ["日常", "公会", "船", "推关"]


def test_run_records_work_into_account_collection(monkeypatch, tmp_path):
    monkeypatch.setenv("CAPYAUTO_ACCOUNTS", str(tmp_path / "accounts.json"))
    engine = _engine(FakeAdapter(), lambda _png: [])
    engine._account = "风叁"

    async def collect(_session_id, _config):
        engine._progress.daily_steps += 2

    monkeypatch.setattr(engine, "_collect_entries", collect)

    _run(engine._run("s1", "daily"))
    summary = accounts_module.account_summary()
    assert summary[0]["name"] == "风叁"
    assert summary[0]["works"]["daily"]["done"] is True
    assert summary[0]["works"]["guild"]["done"] is False


def test_run_skips_account_record_when_nothing_collected(monkeypatch, tmp_path):
    monkeypatch.setenv("CAPYAUTO_ACCOUNTS", str(tmp_path / "accounts.json"))
    engine = _engine(FakeAdapter(), lambda _png: [])
    engine._account = "风叁"

    async def collect(_session_id, _config):
        return None  # 入口全未命中，没有任何收集动作

    monkeypatch.setattr(engine, "_collect_entries", collect)

    _run(engine._run("s1", "all"))
    assert accounts_module.account_summary() == []
    assert any("不计入完成" in log["message"] for log in engine.status()["logs"])


def test_bootstrap_records_only_phases_with_progress(monkeypatch, tmp_path):
    monkeypatch.setenv("CAPYAUTO_ACCOUNTS", str(tmp_path / "accounts.json"))
    engine = _engine(FakeAdapter(), lambda _png: [])
    engine._account = "风叁"

    async def ensure(_session_id):
        return True

    async def noop(_session_id):
        return None

    async def collect(_session_id, config):
        if config.name == "日常":
            engine._progress.daily_steps += 1

    for name in ("_ensure_adventure", "_back_to_adventure"):
        monkeypatch.setattr(engine, name, ensure)
    for name in (
        "_baseline",
        "_dungeons",
        "_tower_bootstrap",
        "_travel",
        "_bootstrap_stage",
        "_upgrade",
        "_retry_stage",
    ):
        monkeypatch.setattr(engine, name, noop)
    monkeypatch.setattr(engine, "_collect_entries", collect)

    _run(engine._bootstrap("s1"))
    works = accounts_module.account_summary()[0]["works"]
    assert works["daily"]["done"] is True
    assert works["guild"]["done"] is False
    assert works["ship"]["done"] is False
    assert works["stage"]["done"] is False


def test_start_rejects_invalid_fast_check_interval(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    engine, _ = _fast_engine(adapter, lambda _png: [], script_path=tmp_path / "stage.json")

    async def scenario():
        with pytest.raises(engine_module.AutomationUnavailable):
            await engine.start(
                adapter.session_id, task="growth", stage_mode="lean", fast_stage_check_every=0
            )

    _run(scenario())


def test_automation_api_passes_fast_stage(client, monkeypatch, tmp_path):
    from app.api import automation as automation_api

    monkeypatch.setattr(engine_module, "engine_available", lambda: True)
    adapter = FakeAdapter()
    engine, _ = _fast_engine(
        adapter, lambda _png: [_item("开始", 0.45, 0.82)], script_path=tmp_path / "stage.json"
    )
    monkeypatch.setattr(automation_api, "get_engine", lambda: engine)

    response = client.post(
        "/api/automation/start",
        json={
            "sessionId": "s1",
            "task": "growth",
            "stageMode": "lean",
            "fastStageCheckEvery": 5,
            "account": "风叁",
        },
    )
    assert response.status_code == 200
    assert engine._fast_stage is True
    assert engine._fast_stage_check_every == 5
    assert engine._account == "风叁"


# ---------- 全自动流水线（all）阶段覆盖 ----------

def test_all_pipeline_covers_guild_dungeon_and_stage(monkeypatch):
    """all 必须覆盖公会捐献/讨伐、副本挑战/扫荡与推关；单阶段失败不中断后续。"""
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    calls = []

    async def collect(_session_id, _work, config):
        calls.append(f"collect:{config.name}")

    async def guild(_session_id):
        calls.append("guild_donate")

    async def raid(_session_id):
        calls.append("guild_raid")
        engine._progress.guild_raids += 1

    async def dungeons(_session_id):
        calls.append("dungeon")
        engine._progress.dungeon_sweeps += 1
        raise RuntimeError("模拟副本入口缺失")

    async def growth(_session_id):
        calls.append("growth")
        engine._progress.stage_runs += 1

    monkeypatch.setattr(engine, "_collect_and_record", collect)
    monkeypatch.setattr(engine, "_guild", guild)
    monkeypatch.setattr(engine, "_guild_raid", raid)
    monkeypatch.setattr(engine, "_dungeons", dungeons)
    monkeypatch.setattr(engine, "_growth", growth)
    monkeypatch.setattr(engine, "_record_work", lambda *_args, **_kwargs: None)

    _run(engine._run(adapter.session_id, "all"))
    status = engine.status()
    assert calls == [
        "collect:日常", "collect:公会", "guild_donate", "guild_raid",
        "collect:船", "dungeon", "growth",
    ]
    assert status["status"] == "completed"
    assert status["progress"]["phase"] == "done"
    assert status["progress"]["guildRaids"] == 1
    assert status["progress"]["dungeonSweeps"] == 1
    assert any("阶段「dungeon」未完成" in log["message"] for log in status["logs"])
    assert any("流水线汇总" in log["message"] for log in status["logs"])


def test_all_pipeline_warns_when_left_inside_a_run(monkeypatch):
    """上次急停停在局内时，必须明确告知用户，不能只留下一堆静默跳过。"""
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [_item("选择技能", 0.50, 0.24)])

    async def noop(*_args, **_kwargs):
        return None

    for name in ("_collect_and_record", "_guild", "_guild_raid", "_dungeons", "_growth"):
        monkeypatch.setattr(engine, name, noop)
    monkeypatch.setattr(engine, "_record_work", lambda *_args, **_kwargs: None)

    _run(engine._run(adapter.session_id, "all"))
    assert any(
        "停留在推关局内" in log["message"] for log in engine.status()["logs"]
    )


def test_guild_raid_clicks_only_confirmed_action(monkeypatch):
    """公会讨伐只点 OCR 明确确认的按钮，并单独计数。"""
    adapter = FakeAdapter()
    screens = [
        [_item("公会大厅", 0.50, 0.30), _item("讨伐", 0.70, 0.55)],
        [_item("公会大厅", 0.50, 0.30), _item("讨伐", 0.70, 0.55)],
        [_item("开始讨伐", 0.50, 0.80)],
        [_item("确定", 0.50, 0.80)],
        [],
    ]
    seq = iter(screens)
    engine = _engine(adapter, lambda _png: next(seq, []))

    async def yes(_session_id):
        return True

    async def noop(_session_id):
        return None

    monkeypatch.setattr(engine, "_ensure_adventure", yes)
    monkeypatch.setattr(engine, "_back_to_adventure", noop)

    _run(engine._guild_raid(adapter.session_id))
    progress = engine.status()["progress"]
    assert progress["guildRaids"] == 1
    assert progress["guildSteps"] == 1
    assert any(
        "公会讨伐：点击「开始讨伐」" in log["message"]
        for log in engine.status()["logs"]
    )


def test_guild_raid_skips_without_guild_hall(monkeypatch):
    """认不出公会地图就跳过，不盲点坐标、不虚报次数。"""
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])

    async def yes(_session_id):
        return True

    async def noop(_session_id):
        return None

    monkeypatch.setattr(engine, "_ensure_adventure", yes)
    monkeypatch.setattr(engine, "_back_to_adventure", noop)

    _run(engine._guild_raid(adapter.session_id))
    assert engine.status()["progress"]["guildRaids"] == 0
    assert any(
        "未确认公会页" in log["message"] for log in engine.status()["logs"]
    )


# ---------- 2026-11-16 真机修正回归 ----------

def test_has_material_dialog_and_close_only_taps_x():
    """材料/金币不足弹窗要被识别，且只点底部 X，绝不碰价格/前往。"""
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    mat = engine_module.Screen([
        _item("道具获取", 0.50, 0.25),
        _item("当前数量：16.5K", 0.50, 0.38),
        _item("黑市购买", 0.31, 0.56),
        _item("30元", 0.78, 0.49),
        _item("前往", 0.78, 0.56),
    ])
    assert engine._has_material_dialog(mat) is True
    normal = engine_module.Screen([_item("天赋", 0.67, 0.98), _item("等级1", 0.50, 0.72)])
    assert engine._has_material_dialog(normal) is False

    _run(engine._close_material_dialog(adapter.session_id))
    assert adapter.taps == [(0.5, 0.885)]
    assert not any(0.7 < x < 0.9 and abs(y - 0.49) < 0.05 for x, y in adapter.taps)


def test_upgrade_does_not_count_material_popup_as_success(monkeypatch):
    """点天赋弹出材料引导时不记成功，且安全关闭。"""
    adapter = FakeAdapter()
    screens = [
        [_item("开始", 0.45, 0.82)],
        # 进入天赋页（tap 次数=1）
        [_item("天赋", 0.67, 0.98), _item("等级0", 0.50, 0.72), _item("等级0", 0.81, 0.72)],
        # 点攻击卡片后弹出材料引导（tap 次数=2）
        [
            _item("天赋", 0.67, 0.98), _item("道具获取", 0.50, 0.25),
            _item("当前数量：16.5K", 0.50, 0.38), _item("30元", 0.78, 0.49),
        ],
        # 关闭弹窗后回到天赋页（tap 次数=3）
        [_item("天赋", 0.67, 0.98), _item("等级0", 0.50, 0.72), _item("等级0", 0.81, 0.72)],
        # 之后装备页相关（不会再强化，直接给空）
        [_item("开始", 0.45, 0.82)],
    ]
    engine = _engine(adapter, _tap_scripted_ocr(adapter, screens))

    async def ensure_adventure(_session_id):
        return True

    monkeypatch.setattr(engine, "_ensure_adventure", ensure_adventure)
    _run(engine._upgrade(adapter.session_id))
    assert engine.status()["progress"]["upgradeSteps"] == 0
    assert any("材料不足" in log["message"] for log in engine.status()["logs"])


def test_confirm_button_recognizes_real_device_words():
    """真机技能弹窗底部是「领悟」/「下一天」，必须被识别为确认按钮。"""
    engine = _engine(FakeAdapter(), lambda _png: [])
    screen = engine_module.Screen([
        _item("选择技能", 0.50, 0.34),       # 顶部标题
        _item("天雷", 0.30, 0.41),
        _item("领悟", 0.50, 0.911),          # 底部确认
    ])
    btn = engine._confirm_button(screen)
    assert btn is not None and btn.text == "领悟"
    screen2 = engine_module.Screen([
        _item("选择技能", 0.50, 0.34),
        _item("下一天", 0.50, 0.91),
    ])
    btn2 = engine._confirm_button(screen2)
    assert btn2 is not None and btn2.text == "下一天"


def test_recover_if_stuck_restarts_once_then_fatal():
    """连续卡住：第一次杀进程重启并恢复；重启后仍卡则置 fatal 停止。"""
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [_item("开始", 0.45, 0.82)])
    calls = {"ensure": 0}

    async def ensure(_session_id):
        calls["ensure"] += 1
        return calls["ensure"] <= 12  # 第一次自愈能回冒险页，第二次不行

    monkeypatch_ok = ensure
    engine._ensure_adventure = monkeypatch_ok
    # 第一次：STUCK_RESTART_LIMIT=2，第一次调用只累计
    assert _run(engine._recover_if_stuck(adapter.session_id, failed=True)) is False
    assert engine._stuck_streak == 1
    # 第二次：触发重启
    assert _run(engine._recover_if_stuck(adapter.session_id, failed=True)) is True
    assert engine._restart_count == 1
    assert getattr(adapter, "stopped_packages", []) == ["com.hb.cncapy.and"]
    assert engine._stuck_streak == 0
    # 再次连续卡两次：重启已达上限 → fatal
    _run(engine._recover_if_stuck(adapter.session_id, failed=True))
    _run(engine._recover_if_stuck(adapter.session_id, failed=True))
    assert engine._fatal_stuck is True


def test_lean_mode_uses_faster_gap_and_jitter():
    """精简模式 start 后启用压缩节拍与更大抖动。"""
    adapter = FakeAdapter()
    engine = _engine(adapter, lambda _png: [])
    _run(engine.start(adapter.session_id, task="growth", stage_mode="lean", max_runs=1))
    assert engine._fast_stage is True
    assert engine._lean_gap_scale == engine_module.LEAN_STAGE_GAP_SCALE
    assert engine._lean_jitter == engine_module.LEAN_STAGE_JITTER
    assert engine._lean_option_gap == engine_module.LEAN_STAGE_OPTION_GAP
