from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

from app.device.base import DeviceAdapter
from app.errors import AutomationBusy, AutomationUnavailable
from app.vision.ocr import OcrItem, engine_available, ocr_png

TASK_DAILY = "daily"
TASK_STAGE = "stage"
TASK_ALL = "all"

# 冒险页（主城）的推关入口
STAGE_ENTRY = "开始"
# 常见日常入口图标文案
DAILY_ENTRIES = ("游历", "家园", "日历", "特权卡", "活动", "超值好礼")
# 页面内的领取类动作
COLLECT_WORDS = (
    "一键领取",
    "全部领取",
    "领取",
    "收取",
    "免费领取",
    "签到",
    "立即领取",
    "点击领取",
    "升级",
)
BACK_WORDS = ("返回", "关闭", "退出")
# 推关过程中底部可推进流程的按钮
STAGE_ACTIONS = (
    "下一天",
    "领悟",
    "继续",
    "确定",
    "开始战斗",
    "战斗",
    "点击继续",
    "领取",
    "跳过",
    "打开",
    "开启",
    "拾取",
)
# 幸运转盘 / 幸运宝藏：标题整条匹配
WHEEL_TITLES = ("幸运转盘", "幸运宝藏")
# 挖宝小游戏：4x3 卡牌网格中心点，逐格翻开
DIG_HINT = "翻出三个相同卡牌"
DIG_CELLS = [
    (x, y)
    for y in (0.440, 0.575, 0.700)
    for x in (0.170, 0.391, 0.620, 0.852)
]
# 结算界面的按钮，出现即代表本轮结束
SETTLE_WORDS = ("再次挑战", "返回主城", "结算", "领取奖励", "再来一次")
# 选中卡片后需要额外确认的按钮（「获得」在前：单卡弹窗里「拾取」常是禁用态）
FINALIZE_WORDS = ("获得", "拾取", "确定")
SKILL_TITLE = "选择技能"
SKILL_HINT = "从下方选择一个技能"
# 技能弹窗里不是卡片的文案
SKILL_NON_CARDS = {
    "普通",
    "稀有",
    "史诗",
    "传说",
    "神话",
    "已学技能",
    "下一天",
    SKILL_TITLE,
    SKILL_HINT,
}
DAY_PATTERN = re.compile(r"第\s*\d+\s*天")
LEVEL_PATTERN = re.compile(r"^LV", re.IGNORECASE)

MAX_LOG = 200


@dataclass(frozen=True)
class Screen:
    items: list[OcrItem]

    def texts(self) -> list[str]:
        return [item.text for item in self.items]

    def has(self, *words: str) -> bool:
        return self.find(*words) is not None

    def find_exact(self, *words: str) -> OcrItem | None:
        for word in words:
            for item in self.items:
                if item.text.strip() == word:
                    return item
        return None

    def find(self, *words: str) -> OcrItem | None:
        """先按整条文本精确匹配，再退化为包含匹配"""
        for word in words:
            for item in self.items:
                if item.text.strip() == word:
                    return item
        for word in words:
            for item in self.items:
                if word and word in item.text:
                    return item
        return None


@dataclass
class _Progress:
    runs: int = 0
    daily_steps: int = 0

    def to_payload(self) -> dict[str, int]:
        return {"runs": self.runs, "dailySteps": self.daily_steps}


class AutomationEngine:
    """OCR 驱动的自动化引擎：日常任务与自动推关。

    流程不依赖固定坐标，全部基于截图 OCR 命中的文案锚点，再换算成归一化坐标点击。
    """

    def __init__(
        self,
        adapter_getter: Callable[[], DeviceAdapter],
        *,
        ocr: Callable[[bytes], list[OcrItem]] | None = None,
        sleep: Callable[[float], Any] | None = None,
        clock: Callable[[], float] = time.time,
        max_run_seconds: float = 600.0,
    ) -> None:
        self._adapter_getter = adapter_getter
        self._ocr = ocr or ocr_png
        self._sleep = sleep or asyncio.sleep
        self._clock = clock
        self._max_run_seconds = max_run_seconds
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._status = "idle"
        self._task_name: str | None = None
        self._session_id: str | None = None
        self._started_at: float | None = None
        self._ended_at: float | None = None
        self._error: str | None = None
        self._progress = _Progress()
        self._logs: deque[dict[str, Any]] = deque(maxlen=MAX_LOG)

    # ---------- 对外接口 ----------

    def status(self) -> dict[str, Any]:
        return {
            "status": self._status,
            "task": self._task_name,
            "sessionId": self._session_id,
            "startedAt": self._started_at,
            "endedAt": self._ended_at,
            "error": self._error,
            "progress": self._progress.to_payload(),
            "logs": list(self._logs),
        }

    async def start(
        self,
        session_id: str,
        *,
        task: str = TASK_ALL,
        max_runs: int = 1,
        skill_priority: list[str] | None = None,
    ) -> dict[str, Any]:
        if task not in (TASK_DAILY, TASK_STAGE, TASK_ALL):
            raise AutomationUnavailable(f"未知自动化任务: {task}")
        if self._task is not None and not self._task.done():
            raise AutomationBusy("自动化任务已在运行，请先停止")
        if not engine_available():
            raise AutomationUnavailable("未安装 OCR 引擎，无法执行自动化")

        adapter = self._adapter_getter()
        adapter.get_session(session_id)

        self._status = "running"
        self._task_name = task
        self._session_id = session_id
        self._started_at = self._clock()
        self._ended_at = None
        self._error = None
        self._stopping = False
        self._progress = _Progress()
        self._logs.clear()
        self._log("info", f"启动自动化：{task}（推关轮数 {max_runs}）")

        self._task = asyncio.create_task(
            self._run(session_id, task, max_runs, skill_priority or [])
        )
        return self.status()

    def stop(self) -> dict[str, Any]:
        if self._task is not None and not self._task.done():
            self._stopping = True
            self._log("warn", "收到停止指令，等待当前动作结束")
        return self.status()

    # ---------- 主流程 ----------

    async def _run(
        self, session_id: str, task: str, max_runs: int, skill_priority: list[str]
    ) -> None:
        try:
            if task in (TASK_DAILY, TASK_ALL):
                await self._daily(session_id)
            if task in (TASK_STAGE, TASK_ALL) and not self._stopping:
                await self._stage(session_id, max_runs, skill_priority)
            self._status = "stopped" if self._stopping else "completed"
            self._log("info", "自动化任务结束")
        except Exception as exc:  # noqa: BLE001 - 需要把异常落到状态里给前端
            self._status = "error"
            self._error = str(exc)
            self._log("error", f"自动化异常：{exc}")
        finally:
            self._ended_at = self._clock()

    async def _daily(self, session_id: str) -> None:
        await self._ensure_adventure(session_id)
        for entry in DAILY_ENTRIES:
            if self._stopping:
                return
            screen = await self._read(session_id)
            anchor = screen.find(entry)
            if anchor is None:
                self._log("warn", f"未找到日常入口「{entry}」，跳过")
                continue
            self._log("info", f"进入日常：{entry}")
            # 图标在文案上方，点击点上移一点
            await self._tap(session_id, anchor, dy=-0.025)
            for _ in range(5):
                if self._stopping:
                    return
                screen = await self._read(session_id)
                action = screen.find(*COLLECT_WORDS)
                if action is None:
                    break
                self._log("info", f"{entry}：点击「{action.text}」")
                await self._tap(session_id, action)
                self._progress.daily_steps += 1
            await self._back_to_adventure(session_id)

    async def _stage(
        self, session_id: str, max_runs: int, skill_priority: list[str]
    ) -> None:
        while self._progress.runs < max_runs and not self._stopping:
            screen = await self._read(session_id)
            # 已经在一局里（例如手动玩到一半）就先打完，避免直接报错
            if screen.find(STAGE_ENTRY) is None:
                if self._in_run(screen):
                    self._log("info", "检测到进行中的一局，先完成当前关卡")
                    await self._play_run(session_id, skill_priority)
                    continue
                await self._ensure_adventure(session_id)
                screen = await self._read(session_id)
            start = screen.find(STAGE_ENTRY)
            if start is None:
                raise AutomationUnavailable("未找到「开始」按钮，请手动回到冒险页后重试")
            self._log("info", f"第 {self._progress.runs + 1} 轮推关：点击「开始」")
            await self._tap(session_id, start)
            await self._play_run(session_id, skill_priority)

    async def _play_run(self, session_id: str, skill_priority: list[str]) -> None:
        deadline = self._clock() + self._max_run_seconds
        idle_rounds = 0
        stuck = 0
        dig_index = 0
        last_action: str | None = None
        last_signature: str | None = None
        while not self._stopping and self._clock() < deadline:
            screen = await self._read(session_id)
            signature = "|".join(screen.texts())
            stuck = stuck + 1 if signature == last_signature else 0
            last_signature = signature
            # 「获得/拾取/确定」是收尾按钮，任何弹窗下都优先点掉（必须整条匹配，避免误命中文案）
            finalize = self._finalize_button(screen)
            if finalize is not None:
                self._log("info", f"确认：「{finalize.text}」")
                await self._tap(session_id, finalize)
                idle_rounds = 0
                continue
            if self._is_skill_modal(screen):
                await self._pick_skills(session_id, screen, skill_priority)
                idle_rounds = 0
                continue
            # 挖宝小游戏：逐格翻牌，翻完自动结束
            if screen.has(DIG_HINT):
                cell = DIG_CELLS[dig_index % len(DIG_CELLS)]
                dig_index += 1
                self._log("info", f"挖宝翻牌：第 {dig_index} 张")
                await self._adapter_getter().tap(session_id, cell[0], cell[1], 80, 6)
                await self._sleep(0.9)
                idle_rounds = 0
                continue
            # 幸运转盘/宝藏：没有关闭按钮，转完次数后会出现「返回」
            if screen.find_exact(*WHEEL_TITLES) is not None:
                back = screen.find_exact("返回")
                if back is not None:
                    self._log("info", "退出幸运转盘")
                    await self._tap(session_id, back)
                else:
                    spin = screen.find_exact("转动")
                    if spin is not None:
                        self._log("info", "转动幸运转盘")
                        await self._tap(session_id, spin)
                    else:
                        await self._adapter_getter().tap(session_id, 0.098, 0.872, 80, 6)
                        await self._sleep(1.2)
                idle_rounds = 0
                continue
            settle = screen.find(*SETTLE_WORDS)
            if settle is not None:
                self._log("info", f"本轮结束：「{settle.text}」")
                await self._tap(session_id, settle)
                self._progress.runs += 1
                await self._back_to_adventure(session_id)
                return
            # 「请选择一项…」类弹窗：底部按钮往往被禁用，需要在列表里挑一项
            if screen.has("请选择"):
                option = self._prompt_option(screen)
                if option is not None:
                    self._log("info", f"选择馈赠：「{option.text}」")
                    await self._tap(session_id, option)
                    idle_rounds = 0
                    continue
            action = screen.find(*STAGE_ACTIONS)
            if action is not None and stuck < 3:
                text = action.text.strip()
                if text != last_action:
                    self._log("info", f"点击「{text}」")
                    last_action = text
                await self._tap(session_id, action)
                idle_rounds = 0
                continue
            # 没有标准动作按钮时，可能是二选一的奇遇选项（如「休息 / 搜索」）
            option = self._choice_option(screen)
            if option is not None:
                self._log("info", f"奇遇选项：「{option.text}」")
                await self._tap(session_id, option)
                idle_rounds = 0
                continue
            idle_rounds += 1
            if idle_rounds == 4:
                self._log("warn", "连续多轮未识别到可点击动作，尝试点击屏幕下方中部")
                await self._adapter_getter().tap(session_id, 0.5, 0.92, 80, 6)
            if idle_rounds >= 6:
                self._log("warn", "界面长时间无响应，放弃当前关卡")
                return
            await self._sleep(1.5)
        self._log("warn", "本轮推关超时，未检测到结算界面")

    def _finalize_button(self, screen: Screen) -> OcrItem | None:
        for word in FINALIZE_WORDS:
            for item in screen.items:
                if item.text.strip() == word:
                    return item
        return None

    def _prompt_option(self, screen: Screen) -> OcrItem | None:
        """「请选择一项…」弹窗里的候选项，取最上面一个"""
        options: list[OcrItem] = []
        for item in screen.items:
            left, top, right, bottom = item.bounds
            cy = (top + bottom) / 2
            cx = (left + right) / 2
            text = item.text.strip()
            if not (0.33 <= cy <= 0.78 and cx <= 0.80):
                continue
            if len(text) < 2 or len(text) > 6 or "。" in text or "请选择" in text:
                continue
            if LEVEL_PATTERN.match(text) or text in SKILL_NON_CARDS:
                continue
            if DAY_PATTERN.search(text):
                continue
            options.append(item)
        options.sort(key=lambda entry: entry.bounds[1])
        return options[0] if options else None

    def _in_run(self, screen: Screen) -> bool:
        """是否处于关卡内：技能弹窗、天数指示、推进按钮或结算按钮任一命中"""
        if self._is_skill_modal(screen):
            return True
        if any(DAY_PATTERN.search(item.text) for item in screen.items):
            return True
        return screen.find(*STAGE_ACTIONS) is not None or screen.find(*SETTLE_WORDS) is not None

    def _choice_option(self, screen: Screen) -> OcrItem | None:
        """底部一排二/三选一的奇遇按钮：取最左（最上）的那个"""
        options: list[OcrItem] = []
        for item in screen.items:
            left, top, right, bottom = item.bounds
            cy = (top + bottom) / 2
            text = item.text.strip()
            if cy < 0.84 or len(text) < 2 or len(text) > 6:
                continue
            if any(word in text for word in STAGE_ACTIONS + SETTLE_WORDS + ("开始", "冒险")):
                continue
            options.append(item)
        options.sort(key=lambda entry: (entry.bounds[1], entry.bounds[0]))
        return options[0] if options else None

    # ---------- 技能三选一 ----------

    def _is_skill_modal(self, screen: Screen) -> bool:
        if screen.has(SKILL_HINT):
            return True
        return any(item.text.strip() == SKILL_TITLE for item in screen.items)

    def _skill_cards(self, screen: Screen) -> list[OcrItem]:
        cards: list[OcrItem] = []
        for item in screen.items:
            left, top, right, bottom = item.bounds
            cy = (top + bottom) / 2
            cx = (left + right) / 2
            text = item.text.strip()
            if not (0.30 <= cy <= 0.72 and cx <= 0.62):
                continue
            if len(text) < 2 or "。" in text:
                continue
            if text in SKILL_NON_CARDS or "选择技能" in text or "选择一个技能" in text:
                continue
            if text.startswith("刷新"):
                continue
            cards.append(item)
        cards.sort(key=lambda entry: entry.bounds[1])
        return cards

    def _confirm_button(self, screen: Screen) -> OcrItem | None:
        for item in screen.items:
            left, top, right, bottom = item.bounds
            if SKILL_TITLE in item.text and (top + bottom) / 2 >= 0.72:
                return item
        return None

    def _choose_card(self, cards: list[OcrItem], priority: list[str]) -> OcrItem:
        for keyword in priority:
            for card in cards:
                if keyword and keyword in card.text:
                    return card
        return cards[0]

    async def _pick_skills(
        self, session_id: str, screen: Screen, skill_priority: list[str]
    ) -> None:
        last_signature: str | None = None
        unchanged = 0
        for _ in range(8):
            if self._stopping:
                return
            signature = "|".join(screen.texts())
            unchanged = unchanged + 1 if signature == last_signature else 0
            last_signature = signature
            if unchanged >= 2:
                self._log("warn", "技能弹窗无变化，跳过本次选择")
                return
            cards = self._skill_cards(screen)
            if cards:
                choice = self._choose_card(cards, skill_priority)
                self._log("info", f"选择技能：「{choice.text}」")
                await self._tap(session_id, choice)
                screen = await self._read(session_id)
                if not self._is_skill_modal(screen):
                    return
            confirm = self._confirm_button(screen)
            if confirm is None:
                if not cards:
                    return
                continue
            await self._tap(session_id, confirm)
            screen = await self._read(session_id)
            if not self._is_skill_modal(screen):
                return

    # ---------- 页面导航 ----------

    async def _ensure_adventure(self, session_id: str) -> None:
        screen = await self._read(session_id)
        if screen.has(STAGE_ENTRY):
            return
        nav = screen.find("冒险")
        if nav is not None:
            await self._tap(session_id, nav)
        else:
            await self._adapter_getter().key(session_id, "back")
            await self._sleep(1.2)
        screen = await self._read(session_id)
        if screen.has(STAGE_ENTRY):
            return
        self._log("warn", "未能确认冒险页，将按当前界面继续尝试")

    async def _back_to_adventure(self, session_id: str) -> bool:
        back_pressed = False
        for _ in range(4):
            screen = await self._read(session_id)
            if screen.has(STAGE_ENTRY):
                return True
            back = screen.find(*BACK_WORDS)
            if back is not None:
                await self._tap(session_id, back)
                continue
            if back_pressed:
                break
            await self._adapter_getter().key(session_id, "back")
            back_pressed = True
            await self._sleep(1.5)
        self._log("warn", "返回冒险页失败，请检查当前界面")
        return False

    # ---------- 基础能力 ----------

    async def _read(self, session_id: str) -> Screen:
        png = await self._adapter_getter().screenshot(session_id)
        items = await asyncio.to_thread(self._ocr, png)
        return Screen(list(items))

    async def _tap(self, session_id: str, item: OcrItem, *, dy: float = 0.0) -> None:
        left, top, right, bottom = item.bounds
        await self._adapter_getter().tap(
            session_id, (left + right) / 2, (top + bottom) / 2 + dy, 80, 6
        )
        await self._sleep(0.9)

    def _log(self, level: str, message: str) -> None:
        self._logs.append({"ts": self._clock(), "level": level, "message": message})


_engine: AutomationEngine | None = None


def get_engine() -> AutomationEngine:
    global _engine
    if _engine is None:
        from app.deps import get_adapter

        _engine = AutomationEngine(get_adapter)
    return _engine


def reset_engine() -> None:
    global _engine
    _engine = None
