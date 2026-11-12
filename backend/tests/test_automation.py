import asyncio

import pytest

from app.automation import engine as engine_module
from app.automation.engine import AutomationEngine
from app.vision.ocr import OcrItem


class FakeAdapter:
    name = "fake"

    def __init__(self, session_id="s1"):
        self.session_id = session_id
        self.taps: list[tuple[float, float]] = []
        self.keys: list[str] = []

    def get_session(self, session_id):
        assert session_id == self.session_id

    async def screenshot(self, session_id):
        return b"png"

    async def tap(self, session_id, x, y, press_ms, sigma, press_stdev=20.0):
        self.taps.append((x, y))
        return None

    async def key(self, session_id, key):
        self.keys.append(key)


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
        await engine.start(adapter.session_id, task="stage", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["status"] == "completed"
    assert status["progress"]["runs"] == 1
    # 开始 → 选卡 → 确认 → 领悟 → 结算
    assert len(adapter.taps) >= 5
    assert any("选择技能" in log["message"] for log in status["logs"])


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
            adapter.session_id, task="stage", max_runs=1, skill_priority=["恢复强化"]
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
        await engine.start(adapter.session_id, task="stage", max_runs=1)
        await engine._task

    _run(scenario())
    assert engine.status()["progress"]["runs"] == 1
    assert any("奇遇选项" in log["message"] for log in engine.status()["logs"])
    assert any(abs(x - 0.28) < 0.02 for x, _ in adapter.taps)


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
        await engine.start(adapter.session_id, task="stage", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["status"] == "completed"
    assert status["progress"]["runs"] == 1
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
        await engine.start(adapter.session_id, task="stage", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["status"] == "completed"
    assert status["progress"]["runs"] == 1


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
        await engine.start(adapter.session_id, task="stage", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["runs"] == 1
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
        await engine.start(adapter.session_id, task="stage", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["runs"] == 1
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
        await engine.start(adapter.session_id, task="stage", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["runs"] == 1
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
        await engine.start(adapter.session_id, task="stage", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["runs"] == 1
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
        await engine.start(adapter.session_id, task="stage", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["runs"] == 1
    assert not any("转盘" in log["message"] for log in status["logs"])


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
        await engine.start(adapter.session_id, task="stage", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["runs"] == 1
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
        await engine.start(adapter.session_id, task="stage", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["runs"] == 1
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
        await engine.start(adapter.session_id, task="stage", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["runs"] == 1
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
        await engine.start(adapter.session_id, task="stage", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["runs"] == 1
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
        await engine.start(adapter.session_id, task="stage", max_runs=1)
        await engine._task

    _run(scenario())
    status = engine.status()
    assert status["progress"]["runs"] == 1
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
