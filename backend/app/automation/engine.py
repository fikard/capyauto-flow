from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.accounts import WORK_LABELS, ensure_account, record_account_run, record_work
from app.device.base import DeviceAdapter
from app.errors import AutomationBusy, AutomationUnavailable
from app.vision.ocr import OcrItem, engine_available, ocr_png

TASK_GROWTH = "growth"
TASK_DAILY = "daily"
TASK_GUILD = "guild"
TASK_SHIP = "ship"
TASK_BOOTSTRAP = "bootstrap"
TASK_SERVER_SWEEP = "server_sweep"
TASK_ACCOUNT_SWEEP = "account_sweep"
TASK_ALL = "all"

TRAVEL_COST = 100
TRAVEL_TIERS = ("1倍奖励", "3倍奖励", "5倍奖励", "10倍奖励", "20倍奖励")
FORBIDDEN_ACCOUNT = "你瞅啥呢"

# 冒险页（主城）的推关入口
STAGE_ENTRY = "开始"
# 推关一局消耗的体力，低于该值不再开局
STAGE_STAMINA_COST = 5
# 爬塔（星级挑战）入口，单独处理：进入后连打 N 层
TOWER_ENTRY = "星级挑战"
TOWER_START = "开始挑战"
BACK_WORDS = ("返回", "关闭", "退出")
# 子页面左下角的返回箭头：游历面板的箭头偏左，主城通用箭头略靠右
BACK_ARROWS = ((0.070, 0.937), (0.098, 0.955))
# 付费商城（每日特惠等）的真实价格：命中时禁止盲点关闭位，只能走返回箭头
SHOP_PRICE_PATTERN = re.compile(r"\d+\s*元")
# 主城左下角的公会旗帜图标（纯图标无文字，OCR 不可见）；进入后用「公会大厅」确认
GUILD_ICON = (0.08, 0.80)
GUILD_HALL = "公会大厅"
# 真机公会页并不总有「公会大厅」标题：升级 toast 会遮住标题，
# 且可能直接停在「公会信息/捐献/公会管理」页。用多锚点确认，避免误判未入会。
GUILD_PAGE_ANCHORS = (
    "公会信息", "公会管理", "公会成员", "公会捐献", "公会讨伐", "捐献", "讨伐"
)
GUILD_TOAST_WORDS = ("公会升级", "升级成功", "公会等级")
# 全屏子页面标题：右上角 X 才是关闭位，左下角在这些页面是「编辑」等功能按钮。
# 盲点左下箭头会切进编辑态，之后所有返回兜底都失效（真机 2026-11-16 实测）。
SUBPAGE_CLOSE_WORDS = ("家园", "公会信息", "宜居度", "伙伴展示")


@dataclass(frozen=True)
class CategoryConfig:
    """收集类任务（日常/公会/船）的配置：入口文案 + 页面内可点击的领取类动作"""

    name: str
    entries: tuple[str, ...]
    collect_words: tuple[str, ...]
    entry_dy: float = -0.025  # 图标在文案上方，点击点上移


# 日常：游历、家园、日历、特权卡、活动、超值好礼
DAILY_CONFIG = CategoryConfig(
    name="日常",
    entries=("游历", "家园", "日历", "特权卡", "活动", "超值好礼"),
    collect_words=(
        "一键领取",
        "全部领取",
        "一键收获",
        "一键种植",
        "挂机奖励",
        "领取",
        "收取",
        "免费领取",
        "签到",
        "立即领取",
        "点击领取",
    ),
)

# 公会：入口与领取动作（待真机验证后可调整）
GUILD_CONFIG = CategoryConfig(
    name="公会",
    entries=("公会",),
    collect_words=(
        "捐献",
        "一键捐献",
        "领取",
        "一键领取",
        "挑战",
        "讨伐",
        "进入",
        "参加",
    ),
)

# 船：入口与领取动作（待真机验证后可调整）
SHIP_CONFIG = CategoryConfig(
    name="船",
    entries=("船", "造船", "码头", "航海", "船队"),
    collect_words=(
        "领取",
        "一键领取",
        "收获",
        "出海",
        "起航",
        "建造",
        "升级",
        "探索",
    ),
)
# 起号：副本入口，按解锁顺序
DUNGEON_ENTRIES = ("巨龙巢穴", "星界树", "幻剑空岛", "潮汐神殿")
# 起号：爬塔入口，优先「挑战之塔」（日常口径），「星级挑战」仅作兼容
BOOTSTRAP_TOWER_ENTRIES = ("挑战之塔", "星级挑战")
# 起号：区服列表与建角
SERVER_LIST_WORDS = ("服务器", "切换服务器", "区服")
SERVER_ENTER_WORDS = ("进入游戏", "开始游戏", "进入", "确定")
SERVER_STAMINA_PATTERN = re.compile(r"(\d{1,5})\s*/\s*(\d{1,5})")
SERVER_POWER_PATTERN = re.compile(r"战力[^0-9]{0,6}([0-9]+(?:\.[0-9]+)?)\s*([万千亿]?)")
COMPACT_POWER_PATTERN = re.compile(r"^([0-9]+(?:\.[0-9]+)?)([KMB])$", re.IGNORECASE)

# 推关过程中底部可推进流程的按钮
STAGE_ACTIONS = (
    "下一天",
    "领悟",
    "继续",
    "确定",
    "开始战斗",
    "战斗",
    "挖宝",
    "点击继续",
    "领取",
    "跳过",
    "打开",
    "开启",
    "拾取",
    "点击关闭",
)
# 幸运转盘 / 幸运宝藏：标题整条匹配
WHEEL_TITLES = ("幸运转盘", "幸运宝藏")
# 局内「传说技能」事件转盘：点「开始」后按钮变「转盘中…」。
# 真机 2026-11-16 实测：在冲鸭加速器下该动画可能永久停住，既不出结果也不出「返回」，
# 只能杀进程重启；旧实现一直空转到单局超时，收尾也回不了冒险页，直接中断全账号流水线。
WHEEL_SPIN_HINT = "转盘中"
WHEEL_SPIN_MAX_ROUNDS = 8
# 局内随机事件：只用来判断「还在一局里」，具体点击各走各的分支
RUN_EVENT_TITLES = ("幸运转盘", "幸运宝藏", "幸运商人")
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
# 双选项里带这些词的通常是高风险战斗，长局容易反复失败
DANGER_OPTION_WORDS = ("危险", "战斗", "挑战", "迎战", "接受")
# 技能弹窗里不是卡片的文案
SKILL_NON_CARDS = {
    "普通",
    "晋通",  # OCR 常把「普通」认成「晋通」
    "音通",  # OCR 常把「普通」认成「音通」
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
# 快速模式：录制单次点击的最小/最大间隔，避免把 OCR 耗时算进回放节拍
FAST_STAGE_MIN_GAP = 0.4
FAST_STAGE_MAX_GAP = 2.0
# 起步失败时只会录到几次无效点击，低于该长度不落盘
FAST_STAGE_MIN_TAPS = 5
# 单局预算用完（超时）时自动续跑，最多重试这么多次
MAX_STAGE_RETRIES = 2
# 回放时的点击低偏移幅度（归一化坐标）与间隔打散比例
FAST_STAGE_JITTER = 0.004
FAST_STAGE_GAP_JITTER = 0.15
# 下一个锚点与右侧选项锚点之间的点击间隔
FAST_STAGE_OPTION_GAP = (0.12, 0.28)
# 精简模式提速：回放节拍整体压缩、校验间隔放宽、点击抖动加大以提高容错。
# 录制时已剔除 OCR 耗时，回放点击本可更快；用一组独立系数，避免影响全量模式。
LEAN_STAGE_GAP_SCALE = 0.55      # 回放点击间隔额外压缩到 55%
LEAN_STAGE_OPTION_GAP = (0.06, 0.14)  # 右侧选项补点更快
LEAN_STAGE_JITTER = 0.008        # 命中偏移加大一倍，容忍锚点漂移
LEAN_STAGE_CHECK_EVERY = 12      # 每 12 次才 OCR 校验一次（默认 8）
LEAN_STAGE_MAX_RETRIES = 3       # 精简模式多给一次续跑机会

# 技能弹窗底部确认按钮：真机实测是「领悟」或「下一天」，不是顶部标题「选择技能」。
# 旧实现只找含「选择技能」且 cy>=0.72 的项，永远命中不到，导致选了卡却确认不了。
SKILL_CONFIRM_WORDS = ("领悟", "下一天", "继续", "确定")
# 挖宝翻牌上限：翻完 DIG_CELLS 一轮后仍识别到挖宝页就放弃，避免无限循环卡死
DIG_MAX_ROUNDS = 2
# 卡住自愈：单局界面长时间无变化 / 连续失败达到阈值时，杀进程重启一次
STUCK_ROUNDS_LIMIT = 6           # 逐帧识别连续 N 轮无变化视为卡住（与 idle 放弃对齐）
STUCK_RESTART_LIMIT = 2          # 连续多少个「卡住/失败」单局后触发一次重启
RESTART_MAX_TIMES = 1            # 整个任务最多重启几次，仍卡住则停止
RESTART_SETTLE_S = 3.0           # 杀进程后等待多久再拉起
DEFAULT_STAGE_SCRIPT = Path(__file__).resolve().parents[2] / ".data" / "stage_script.json"

# ---------- 六项日常专项（真机 2026-11-16 采集的锚点）----------
# 底部商城 tab 在 cy≈0.94，用 cy 阈值区分「底部导航」与页内同名文字。
NAV_BOTTOM_CY = 0.90
# 1) 商城 → 冒险者补给箱：倒计时「XX后免费」表示未就绪，禁止点击
SUPPLY_LABEL = "冒险者补给箱"
SUPPLY_WAIT_WORD = "后免费"
SUPPLY_CLAIM_WORDS = ("免费领取", "领取", "免费")
# 2) 商城 → 礼包商城 → 免费礼包
GIFT_MALL = "礼包商城"
FREE_GIFT_LABEL = "免费礼包"
FREE_GIFT_BTN = "免费"
# 3) 装备 → 工坊一键合成（真机无「一键强化」文案，最接近的真实动作）
WORKSHOP = "工坊"
ENHANCE_WORDS = ("一键强化", "一键合成", "强化")
ENHANCE_DETAIL_WORDS = ("合成提升等级", "升阶")
# 4) 冒险 → 左侧特权卡 → 领取全部
PRIVILEGE_LABEL = "特权卡"
CLAIM_ALL = "领取全部"
# 5) 冒险 → 左侧三横 → 邮件/好友
MENU_WORDS = ("三", "三横线", "菜单")
MAIL_LABEL = "邮件"
FRIEND_LABEL = "好友"
GAME_FRIEND_TAB = "游戏好友"
MAIL_CLAIM = "一键领取"
FRIEND_CLAIM = "一键领取赠送"
# 6) 冒险 → 活动 → 挑战 → 哥布林矿工
ACTIVITY_ENTRY = "活动"
CHALLENGE_TAB = "挑战"
GOBLIN_ENTRY = "哥布林矿工"
GOBLIN_NO_MORE = ("无法挖掘", "镐头不足", "镐头已用完", "明日再来", "下次再来")
GOBLIN_PICKAXE_PATTERN = re.compile(r"^(\d{1,3})\s*/\s*(\d{1,3})$")
# 5列×6行矿格中心（真机截图 0.19~0.79 × 0.36~0.70）
GOBLIN_CELLS = [(x, y) for y in (0.36, 0.43, 0.50, 0.57, 0.64, 0.71) for x in (0.19, 0.34, 0.49, 0.64, 0.79)]
GOBLIN_MAX_TAPS = 80  # 保护上限，避免 OCR 漏读镐头时无限点击


@dataclass(frozen=True)
class StageTap:
    """快速模式下的一次点击：归一化坐标 + 距上一次点击的间隔（秒）。

    kind 为 "next" 表示主推进锚点，"option" 表示双选项时右侧选项的锚点。
    """

    x: float
    y: float
    gap: float = 1.0
    kind: str = "next"


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

    def adventure_entry(self) -> OcrItem | None:
        """主城推关入口；游历面板中的背景「开始」不能算作主城。"""
        if self.find_exact("开始游历") is not None:
            return None
        if any(self.find_exact(tier) is not None for tier in TRAVEL_TIERS):
            return None
        return self.find_exact(STAGE_ENTRY)

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
    stage_runs: int = 0        # 推关轮数（成长）
    tower_floors: int = 0      # 爬塔层数（成长）
    daily_steps: int = 0       # 日常收集步数
    guild_steps: int = 0       # 公会收集步数
    ship_steps: int = 0        # 船收集步数
    # 六项日常专项的实际执行次数
    supply_claims: int = 0     # 冒险者补给箱免费领取
    gift_claims: int = 0       # 免费礼包领取
    enhance_steps: int = 0     # 装备强化/合成
    privilege_claims: int = 0  # 特权卡领取全部
    mail_claims: int = 0       # 邮件一键领取
    friend_claims: int = 0     # 好友一键领取赠送
    goblin_digs: int = 0       # 哥布林矿工挖掘格数
    guild_raids: int = 0       # 公会讨伐执行次数
    dungeon_sweeps: int = 0    # 副本扫荡执行次数
    # 起号
    phase: str = "idle"
    stage_fails: int = 0
    stage_fail_streak: int = 0
    dungeons_done: int = 0
    travel_spent: int = 0
    upgrade_steps: int = 0
    accounts_created: int = 0
    servers_done: int = 0
    power: int = 0
    stamina: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "stageRuns": self.stage_runs,
            "towerFloors": self.tower_floors,
            "dailySteps": self.daily_steps,
            "guildSteps": self.guild_steps,
            "shipSteps": self.ship_steps,
            "supplyClaims": self.supply_claims,
            "giftClaims": self.gift_claims,
            "enhanceSteps": self.enhance_steps,
            "privilegeClaims": self.privilege_claims,
            "mailClaims": self.mail_claims,
            "friendClaims": self.friend_claims,
            "goblinDigs": self.goblin_digs,
            "guildRaids": self.guild_raids,
            "dungeonSweeps": self.dungeon_sweeps,
            "phase": self.phase,
            "stageFails": self.stage_fails,
            "stageFailStreak": self.stage_fail_streak,
            "dungeonsDone": self.dungeons_done,
            "travelSpent": self.travel_spent,
            "upgradeSteps": self.upgrade_steps,
            "accountsCreated": self.accounts_created,
            "serversDone": self.servers_done,
            "power": self.power,
            "stamina": self.stamina,
        }


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
        max_run_seconds: float | None = None,
        stage_script_path: Path | str | None = None,
    ) -> None:
        self._adapter_getter = adapter_getter
        self._ocr = ocr or ocr_png
        self._sleep = sleep or asyncio.sleep
        self._clock = clock
        # 单局预算：长局在 OCR 速度下 600 秒不够，可用环境变量放大
        self._max_run_seconds = max_run_seconds or float(
            os.environ.get("CAPYAUTO_MAX_RUN_SECONDS", "600")
        )
        self._stage_script_path = Path(
            stage_script_path
            or os.environ.get("CAPYAUTO_STAGE_SCRIPT")
            or DEFAULT_STAGE_SCRIPT
        )
        self._stage_script: list[StageTap] = self._load_stage_script()
        self._recorded: list[StageTap] = []
        self._recording = False
        self._last_tap_ts: float | None = None
        self._stage_mode = "full"
        self._fast_stage = False
        self._fast_stage_check_every = 8
        # 精简模式提速参数：默认与全量一致，start(stage_mode="lean") 时才压缩。
        # 放实例上便于直接调用 _replay_stage 的单元测试保持原坐标预期。
        self._lean_gap_scale = 1.0
        self._lean_option_gap = FAST_STAGE_OPTION_GAP
        self._lean_jitter = FAST_STAGE_JITTER
        self._account = ""
        self._accounts: list[str] = []
        self._account_runs: dict[str, str] = {}
        self._run_id = ""
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._status = "idle"
        self._task_name: str | None = None
        self._session_id: str | None = None
        self._started_at: float | None = None
        self._ended_at: float | None = None
        self._error: str | None = None
        self._progress = _Progress()
        self._speed = 1.0
        self._tower_floors = 2
        self._max_runs = 1
        self._max_stage_fails = 2
        self._travel_stamina = 100
        self._allow_gem_breakthrough = False
        self._server_from = ""
        self._server_to = ""
        self._server_dry_run = True
        self._last_run_failed = False
        self._skill_priority: list[str] = []
        # 卡住自愈状态：连续卡住局数 / 已重启次数 / 重启后是否仍卡
        self._stuck_streak = 0
        self._restart_count = 0
        self._fatal_stuck = False
        self._hard_stuck = False
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
        speed: float = 1.0,
        tower_floors: int = 2,
        max_stage_fails: int = 2,
        travel_stamina: int = 100,
        allow_gem_talent_breakthrough: bool = False,
        stage_mode: str = "full",
        fast_stage_check_every: int = 8,
        account: str = "",
        accounts: list[str] | None = None,
        server_from: str = "",
        server_to: str = "",
        server_dry_run: bool = True,
    ) -> dict[str, Any]:
        valid_tasks = (
            TASK_GROWTH,
            TASK_DAILY,
            TASK_GUILD,
            TASK_SHIP,
            TASK_BOOTSTRAP,
            TASK_SERVER_SWEEP,
            TASK_ACCOUNT_SWEEP,
            TASK_ALL,
        )
        if task not in valid_tasks:
            raise AutomationUnavailable(f"未知自动化任务: {task}")
        if self._task is not None and not self._task.done():
            raise AutomationBusy("自动化任务已在运行，请先停止")
        if not engine_available():
            raise AutomationUnavailable("未安装 OCR 引擎，无法执行自动化")
        if not (0.1 <= speed <= 3.0):
            raise AutomationUnavailable(f"speed 需在 0.1~3.0 之间，收到 {speed}")
        if not (0 <= tower_floors <= 20):
            raise AutomationUnavailable(f"towerFloors 需在 0~20 之间，收到 {tower_floors}")
        if not (1 <= max_stage_fails <= 5):
            raise AutomationUnavailable(
                f"maxStageFails 需在 1~5 之间，收到 {max_stage_fails}"
            )
        if not (0 <= travel_stamina <= 1000):
            raise AutomationUnavailable(
                f"travelStamina 需在 0~1000 之间，收到 {travel_stamina}"
            )
        if not (1 <= fast_stage_check_every <= 50):
            raise AutomationUnavailable(
                f"fastStageCheckEvery 需在 1~50 之间，收到 {fast_stage_check_every}"
            )
        if stage_mode not in ("full", "lean"):
            raise AutomationUnavailable(f"stageMode 只能是 full 或 lean，收到 {stage_mode}")
        if task == TASK_SERVER_SWEEP and not server_from:
            raise AutomationUnavailable("区服遍历需要提供起始区服名 serverFrom")
        account_queue = list(dict.fromkeys(name.strip() for name in (accounts or []) if name.strip()))
        if task == TASK_ACCOUNT_SWEEP and not account_queue:
            raise AutomationUnavailable("账号队列不能为空")
        if FORBIDDEN_ACCOUNT in account_queue or (account.strip() == FORBIDDEN_ACCOUNT):
            raise AutomationUnavailable(f"主账号「{FORBIDDEN_ACCOUNT}」已排除，拒绝执行")

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
        self._speed = speed
        self._tower_floors = tower_floors
        self._max_runs = max_runs
        self._max_stage_fails = max_stage_fails
        self._travel_stamina = travel_stamina
        self._allow_gem_breakthrough = allow_gem_talent_breakthrough
        self._stage_mode = stage_mode
        self._fast_stage = stage_mode == "lean"
        self._fast_stage_check_every = fast_stage_check_every
        if self._fast_stage:
            # 精简模式：节拍压缩、选项补点更快、点击抖动加大以提高容错。
            # 校验间隔仍尊重 fastStageCheckEvery（校验密一点更稳，不额外放宽）。
            self._lean_gap_scale = LEAN_STAGE_GAP_SCALE
            self._lean_option_gap = LEAN_STAGE_OPTION_GAP
            self._lean_jitter = LEAN_STAGE_JITTER
        else:
            self._lean_gap_scale = 1.0
            self._lean_option_gap = FAST_STAGE_OPTION_GAP
            self._lean_jitter = FAST_STAGE_JITTER
        self._account = account.strip()
        self._accounts = account_queue if task == TASK_ACCOUNT_SWEEP else []
        self._account_runs = {name: uuid.uuid4().hex for name in self._accounts}
        self._run_id = uuid.uuid4().hex
        if task == TASK_ACCOUNT_SWEEP:
            try:
                for name in self._accounts:
                    record_account_run(
                        name,
                        self._account_runs[name],
                        "pending",
                        current_phase="pending",
                    )
            except OSError as exc:
                self._status = "error"
                self._error = f"账号状态写入失败：{exc}"
                raise AutomationUnavailable(self._error) from exc
        elif self._account:
            try:
                ensure_account(self._account)
            except OSError as exc:
                self._log("warn", f"账号登记失败：{exc}")
        self._recorded = []
        self._recording = False
        self._last_tap_ts = None
        self._log("info", f"推关模式：{'精简（定时回放）' if self._fast_stage else '全量（逐帧识别）'}")
        if self._fast_stage and not self._stage_script:
            self._log("warn", "精简模式已开启，但还没有录制脚本；本轮先按逐帧识别运行并录制")
        self._server_from = server_from.strip()
        self._server_to = server_to.strip()
        self._server_dry_run = server_dry_run
        self._last_run_failed = False
        self._skill_priority = skill_priority or []
        self._stuck_streak = 0
        self._restart_count = 0
        self._fatal_stuck = False
        self._hard_stuck = False
        self._logs.clear()
        self._log(
            "info",
            f"启动自动化：{task}（推关 {max_runs} 轮 · 爬塔 {tower_floors} 层 · 速度 x{1/speed:.1f}）",
        )
        if task == TASK_BOOTSTRAP:
            self._log(
                "info",
                f"起号参数：失败上限 {max_stage_fails} 次 · 游历阈值 {travel_stamina} 体力"
                f" · 天赋宝石突破 {'允许' if allow_gem_talent_breakthrough else '禁止'}",
            )
        if task == TASK_ALL:
            self._log(
                "info",
                "全自动流水线：日常 → 公会（捐献/讨伐）→ 船 → 成长（游历/推关/爬塔）"
                " → 副本挑战/扫荡",
            )
        if task == TASK_SERVER_SWEEP:
            self._log(
                "info",
                f"区服遍历：{self._server_from} → {self._server_to or '最新区'}"
                f"（{'只枚举不切换' if server_dry_run else '实际切换'}）",
            )

        self._task = asyncio.create_task(self._run(session_id, task))
        return self.status()

    def stop(self) -> dict[str, Any]:
        if self._task is not None and not self._task.done():
            self._stopping = True
            self._log("warn", "收到停止指令，等待当前动作结束")
        return self.status()

    # ---------- 主流程 ----------

    async def _run(self, session_id: str, task: str) -> None:
        try:
            if task == TASK_ACCOUNT_SWEEP:
                await self._account_sweep(session_id)
            elif task == TASK_ALL:
                await self._run_all(session_id)
            elif task == TASK_BOOTSTRAP:
                await self._bootstrap(session_id)
            elif task == TASK_SERVER_SWEEP:
                await self._server_sweep(session_id)
            else:
                # 单任务：日常 / 公会 / 船 / 成长
                if task == TASK_DAILY and not self._stopping:
                    await self._collect_and_record(session_id, "daily", DAILY_CONFIG)
                    await self._daily_specials(session_id)
                if task == TASK_GUILD and not self._stopping:
                    await self._collect_and_record(session_id, "guild", GUILD_CONFIG)
                    # 主城公会入口是纯图标无文字，文字锚点命中不到；必须补图标路径
                    await self._guild(session_id)
                    await self._guild_raid(session_id)
                if task == TASK_SHIP and not self._stopping:
                    await self._collect_and_record(session_id, "ship", SHIP_CONFIG)
                if task == TASK_GROWTH and not self._stopping:
                    before_runs = self._progress.stage_runs
                    await self._growth(session_id)
                    if self._progress.stage_runs > before_runs:
                        self._record_work("stage")
            if self._fatal_stuck and not self._stopping:
                self._status = "error"
                self._error = "游戏反复卡住，重启一次后仍无法恢复，已停止以保障设备安全"
                if task != TASK_ACCOUNT_SWEEP:
                    self._persist_account_run("failed", self._error)
                self._log("error", self._error)
            else:
                self._status = "stopped" if self._stopping else "completed"
                if task != TASK_ACCOUNT_SWEEP:
                    self._persist_account_run("stopped" if self._stopping else "completed")
                self._log("info", "自动化任务结束")
        except Exception as exc:  # noqa: BLE001 - 需要把异常落到状态里给前端
            self._status = "error"
            self._error = str(exc)
            if task != TASK_ACCOUNT_SWEEP:
                try:
                    self._persist_account_run("failed", str(exc))
                except OSError as write_exc:
                    self._log("error", f"账号失败状态写入失败：{write_exc}")
            self._log("error", f"自动化异常：{exc}")
        finally:
            self._ended_at = self._clock()

    async def _run_all(self, session_id: str) -> None:
        """全自动流水线：逐阶段隔离，单个入口找不到不会阻断后续动作。

        旧实现只有 日常/公会收集/船/成长，缺公会捐献与讨伐、副本挑战/扫荡；
        且公会收集入口写成文字「公会」，真机主城是纯图标，永远命中不到，
        结果整条流水线只在游历里空转，看起来像什么都没做。
        """
        # 动作范围扩大后必须保留主账号护栏：绝不在「你瞅啥呢」上跑全自动流水线
        screen = await self._read(session_id)
        detected = self._detect_account_name(screen)
        if detected == FORBIDDEN_ACCOUNT:
            raise AutomationUnavailable(
                f"检测到主账号「{FORBIDDEN_ACCOUNT}」，拒绝执行全自动流水线"
            )
        if self._account and detected and detected != self._account:
            raise AutomationUnavailable(
                f"账号身份不符：期望「{self._account}」，实际「{detected}」"
            )
        if self._in_run(screen):
            # 上一次急停/手动停在局内时，所有子页面都回不了主城，阶段会被整片跳过。
            # 必须把原因说清楚，否则 Web 上只看到「启动成功 + 一堆跳过」。
            self._log(
                "warn",
                "当前停留在推关局内，入口页无法回城；请先手动结算这一局再启动全自动流水线",
            )
        stage_before = self._progress.stage_runs
        guild_before = self._progress.guild_steps
        stages: tuple[tuple[str, Callable[[], Any]], ...] = (
            ("daily", lambda: self._collect_and_record(session_id, "daily", DAILY_CONFIG)),
            ("daily_specials", lambda: self._daily_specials(session_id)),
            ("guild", lambda: self._collect_and_record(session_id, "guild", GUILD_CONFIG)),
            ("guild_donate", lambda: self._guild(session_id)),
            ("guild_raid", lambda: self._guild_raid(session_id)),
            ("ship", lambda: self._collect_and_record(session_id, "ship", SHIP_CONFIG)),
            ("dungeon", lambda: self._dungeons(session_id)),
            ("growth", lambda: self._growth(session_id)),
        )
        for name, work in stages:
            if self._stopping:
                return
            self._progress.phase = name
            self._log("info", f"流水线阶段：{name}")
            try:
                await work()
            except Exception as exc:  # noqa: BLE001 - 单阶段失败不阻断整条流水线
                self._log("warn", f"阶段「{name}」未完成：{exc}")
        self._progress.phase = "done"
        if self._progress.stage_runs > stage_before:
            self._record_work("stage")
        if self._progress.guild_steps > guild_before:
            self._record_work("guild")
        self._log(
            "info",
            f"流水线汇总：推关 {self._progress.stage_runs} · 公会动作 {self._progress.guild_steps}"
            f" · 公会讨伐 {self._progress.guild_raids} · 副本 {self._progress.dungeons_done}"
            f" · 扫荡 {self._progress.dungeon_sweeps} · 爬塔 {self._progress.tower_floors}"
            f" · 游历 {self._progress.travel_spent} 体力"
            f" · 补给箱 {self._progress.supply_claims} · 免费礼包 {self._progress.gift_claims}"
            f" · 装备强化 {self._progress.enhance_steps} · 特权卡 {self._progress.privilege_claims}"
            f" · 邮件 {self._progress.mail_claims} · 好友礼 {self._progress.friend_claims}"
            f" · 挖矿 {self._progress.goblin_digs} 格",
        )

    def _persist_account_run(self, status: str, error: str = "") -> None:
        if not self._account or not self._run_id:
            return
        record_account_run(
            self._account,
            self._run_id,
            status,
            current_phase=self._progress.phase,
            error=error,
            progress=self._progress.to_payload(),
        )

    async def _account_sweep(self, session_id: str) -> None:
        failed: list[str] = []
        for name in self._accounts:
            if self._stopping:
                return
            self._account = name
            self._run_id = self._account_runs[name]
            self._progress = _Progress()
            self._last_run_failed = False
            self._hard_stuck = False
            # 重启额度按账号计：上一号用掉一次不能让后续账号失去自愈能力。
            # 若上一号是「重启后仍失败」，_fatal_stuck 会在下面中断整队。
            self._stuck_streak = 0
            self._restart_count = 0
            try:
                self._set_phase("switch")
                if not await self._switch_account(session_id, name):
                    raise AutomationUnavailable(f"账号「{name}」切换或身份核验失败，停止全队")
                await self._bootstrap(session_id)
                self._persist_account_run("stopped" if self._stopping else "completed")
            except OSError:
                # 账号状态写盘失败是设备/磁盘级问题，继续切号只会把状态写得更乱
                raise
            except Exception as exc:  # noqa: BLE001 - 单号失败不应阻断后续账号
                try:
                    self._persist_account_run("failed", str(exc))
                except OSError as write_exc:
                    self._log("error", f"账号失败状态写入失败：{write_exc}")
                failed.append(f"{name}：{exc}")
                self._log("warn", f"账号「{name}」未完成，继续下一个账号：{exc}")
                # 硬卡死重启后仍失败意味着设备需要人工介入，不能再切号继续操作
                if self._fatal_stuck or self._stopping:
                    break
        if failed:
            self._log("warn", f"全账号流水线结束，失败 {len(failed)} 个：{' | '.join(failed)}")
        else:
            self._log("info", f"全账号流水线结束，{len(self._accounts)} 个账号均已完成")

    async def _growth(self, session_id: str) -> None:
        """成长循环：游历压体力 → 提升天赋 → 推关，直到体力不足或连续失败。"""
        # 先把阶段写进 status.progress.phase：游历阶段可能持续数十秒，
        # 若一直显示 idle，Web 上会误判成「流水线卡住 / 什么都没做」。
        self._progress.phase = "travel"
        self._log("info", "成长阶段：游历压体力 → 提升 → 推关 → 爬塔")
        while not self._stopping and not self._fatal_stuck:
            if (
                self._max_stage_fails
                and self._progress.stage_fail_streak >= self._max_stage_fails
            ):
                self._log(
                    "warn",
                    f"推关连续失败 {self._max_stage_fails} 次，停止成长",
                )
                break
            if self._max_runs and self._progress.stage_runs >= self._max_runs:
                self._log("info", "达到推关轮数上限，停止成长")
                break
            prepared = await self._travel_until_low(session_id)
            if self._stopping:
                break
            if prepared:
                if self._stamina_short():
                    break
                await self._upgrade(session_id)
                if self._stopping:
                    break
            before_runs = self._progress.stage_runs
            before_fails = self._progress.stage_fails
            self._progress.phase = "stage"
            await self._stage(session_id, rounds=1)
            if not prepared:
                # 体力/游历无法确认：只打一局，避免在非主城环境反复空转
                break
            if (
                self._progress.stage_runs == before_runs
                and self._progress.stage_fails == before_fails
            ):
                # 既没推进也没失败：体力不足或入口异常，避免空转
                break
        if not self._stopping and self._tower_floors > 0:
            await self._tower(session_id)

    def _stamina_short(self) -> bool:
        """体力已确认且不足以再开一局；未知（0）时不提前终止。"""
        return 0 < self._progress.stamina < STAGE_STAMINA_COST

    async def _collect_entries(
        self, session_id: str, config: CategoryConfig
    ) -> None:
        """通用收集类任务：遍历入口，进入后循环点击领取类按钮。

        适用于 日常 / 公会 / 船 这三类"进页面 → 点领取 → 返回"的任务。
        每个入口单独读取屏幕（处理完一个入口后主城页可能切换 tab）。
        """
        await self._ensure_adventure(session_id)
        found_any = False
        recovered = False
        for entry in config.entries:
            if self._stopping:
                return
            screen = await self._read(session_id)
            anchor = screen.find(entry)
            if anchor is None and not recovered:
                # 上一入口可能没退回冒险页：兜底回城后重试一次，避免整类任务被跳过
                recovered = True
                if await self._ensure_adventure(session_id):
                    screen = await self._read(session_id)
                    anchor = screen.find(entry)
            if anchor is None:
                self._log("warn", f"未找到{config.name}入口「{entry}」，跳过")
                continue
            found_any = True
            self._log("info", f"进入{config.name}：{entry}")
            await self._tap(session_id, anchor, dy=config.entry_dy)
            last_signature: str | None = None
            for _ in range(5):
                if self._stopping:
                    return
                screen = await self._read(session_id)
                signature = "|".join(screen.texts())
                if signature == last_signature:
                    break
                last_signature = signature
                action = screen.find(*config.collect_words)
                if action is None:
                    break
                self._log("info", f"{entry}：点击「{action.text}」")
                await self._tap(session_id, action)
                # 按类别分别计数
                if config is DAILY_CONFIG:
                    self._progress.daily_steps += 1
                elif config is GUILD_CONFIG:
                    self._progress.guild_steps += 1
                elif config is SHIP_CONFIG:
                    self._progress.ship_steps += 1
                # 游历「挂机奖励」是两层弹窗：第一层点开奖励预览，第二层才是领取。
                # 动画期间 OCR 签名可能完全不变，旧逻辑直接 break 导致奖励漏领。
                if config is DAILY_CONFIG and "挂机" in action.text:
                    for _ in range(5):
                        await self._wait(0.4, "claim_poll")
                        follow = await self._read(session_id)
                        claim = follow.find_exact("一键领取", "立即领取", "领取全部", "领取")
                        if claim is not None:
                            self._log("info", f"游历奖励二次确认：「{claim.text}」")
                            await self._tap(session_id, claim)
                            self._progress.daily_steps += 1
                            break
                        if follow.find_exact("挂机奖励") is None:
                            break
                    last_signature = None
            await self._back_to_adventure(session_id)

    async def _tower(self, session_id: str) -> None:
        """爬塔（星级挑战）：进入后连打 N 层，每层复用推关战斗循环"""
        await self._ensure_adventure(session_id)
        screen = await self._read(session_id)
        anchor = screen.find(TOWER_ENTRY)
        if anchor is None:
            self._log("warn", f"未找到爬塔入口「{TOWER_ENTRY}」，跳过爬塔")
            return
        self._log("info", f"进入爬塔：{TOWER_ENTRY}（目标 {self._tower_floors} 层）")
        await self._tap(session_id, anchor, dy=-0.025)

        for floor in range(self._tower_floors):
            if self._stopping:
                return
            screen = await self._read(session_id)
            # 爬塔页的「开始」按钮：优先匹配「开始挑战」，退化为「挑战」/「开始」
            start = (
                screen.find_exact(TOWER_START)
                or screen.find("开始挑战", "挑战", "再次挑战")
                or screen.find_exact("开始")
            )
            if start is None:
                self._log("warn", "爬塔页未找到开始按钮，结束爬塔")
                break
            self._log("info", f"爬塔第 {floor + 1} 层：点击「{start.text}」")
            await self._tap(session_id, start)
            # 每层战斗复用推关循环；结算后会自动回到爬塔列表
            if await self._play_run(session_id):
                self._progress.tower_floors += 1
            await self._back_to_adventure(session_id)
        self._log("info", f"爬塔完成：共 {self._progress.tower_floors} 层")

    async def _stage(self, session_id: str, *, rounds: int | None = None) -> None:
        """推关。rounds 为本次调用最多打几局，缺省表示总轮数上限（0 = 不限）。"""
        limit = self._max_runs if rounds is None else rounds
        done = 0
        while (not limit or done < limit) and not self._stopping and not self._fatal_stuck:
            screen = await self._read(session_id)
            stamina = self._parse_stamina(screen)
            if stamina is not None:
                self._progress.stamina = stamina
                if stamina < STAGE_STAMINA_COST:
                    self._log(
                        "info",
                        f"体力 {stamina} < {STAGE_STAMINA_COST}，停止推关",
                    )
                    return
            # 已经在一局里（例如手动玩到一半）就先打完，避免直接报错
            if screen.adventure_entry() is None:
                if self._in_run(screen):
                    self._log("info", "检测到进行中的一局，先完成当前关卡")
                    finished = await self._play_run_with_retries(session_id)
                    if not finished or self._last_run_failed:
                        if not self._count_stage_failure():
                            return
                        continue
                    self._progress.stage_runs += 1
                    self._progress.stage_fail_streak = 0
                    done += 1
                    continue
                await self._ensure_adventure(session_id)
                screen = await self._read(session_id)
            start = screen.adventure_entry()
            if start is None:
                raise AutomationUnavailable("未找到「开始」按钮，请手动回到冒险页后重试")
            self._log("info", f"第 {self._progress.stage_runs + 1} 轮推关：点击「开始」")
            await self._tap(session_id, start)
            finished = await self._play_run_with_retries(
                session_id, replay=True, record=True
            )
            if not finished or self._last_run_failed:
                if not self._count_stage_failure():
                    return
                continue
            self._progress.stage_runs += 1
            self._progress.stage_fail_streak = 0
            done += 1

    def _count_stage_failure(self) -> bool:
        """记录一次真实推关失败；返回是否还能继续尝试。"""
        if not self._last_run_failed:
            return False
        self._progress.stage_fails += 1
        self._progress.stage_fail_streak += 1
        self._log(
            "warn",
            f"推关失败：累计 {self._progress.stage_fails} 次，"
            f"同一关连续 {self._progress.stage_fail_streak} 次",
        )
        return self._progress.stage_fail_streak < self._max_stage_fails

    # ---------- 起号（bootstrap） ----------

    def _set_phase(self, phase: str) -> None:
        self._progress.phase = phase
        self._log("info", f"起号阶段：{phase}")
        self._persist_account_run("running")

    async def _bootstrap(self, session_id: str) -> None:
        """单账号主线：基线 → 副本 → 爬塔 → 游历 → 推关 → 提升 → 回推。"""
        self._set_phase("baseline")
        if not await self._ensure_adventure(session_id):
            raise AutomationUnavailable("未能确认冒险页，已停止主线")
        await self._baseline(session_id)
        if self._stopping:
            return

        # 单账号一次性主线：先日常，再公会（免费捐献）、船，最后推关
        self._set_phase("daily")
        await self._collect_and_record(session_id, "daily", DAILY_CONFIG)
        # 六项日常专项（补给箱/礼包/装备强化/特权卡/邮件好友/哥布林矿工）。
        # account_sweep 每号走的就是 _bootstrap，必须在这里也接上，否则全账号流水线不执行专项。
        # 单独异常隔离：专项失败不影响后续公会/爬塔等阶段。
        if not self._stopping:
            try:
                await self._daily_specials(session_id)
            except Exception as exc:
                self._log("warn", f"六项日常专项异常，已跳过不影响主线：{exc}")
        if self._stopping:
            return

        self._set_phase("guild")
        guild_before = self._progress.guild_steps
        await self._guild(session_id)
        if self._progress.guild_steps > guild_before:
            self._record_work("guild")
        else:
            self._log("info", "公会：本次没有可领取的内容，不计入完成")
        if self._stopping:
            return

        self._set_phase("ship")
        await self._collect_and_record(session_id, "ship", SHIP_CONFIG)
        if self._stopping:
            return

        self._set_phase("dungeon")
        await self._dungeons(session_id)
        if self._stopping:
            return

        self._set_phase("tower")
        await self._tower_bootstrap(session_id)
        if self._stopping:
            return

        self._set_phase("travel")
        await self._travel(session_id)
        if self._stopping:
            return

        self._set_phase("stage")
        before_runs = self._progress.stage_runs
        await self._bootstrap_stage(session_id)
        if self._progress.stage_runs > before_runs:
            self._record_work("stage")
        if self._stopping:
            return

        self._set_phase("upgrade")
        await self._upgrade(session_id)
        if self._stopping:
            return

        self._set_phase("retry")
        await self._retry_stage(session_id)
        if self._stopping:
            return

        self._set_phase("done")
        if not await self._back_to_adventure(session_id):
            raise AutomationUnavailable("起号结束前未能回到冒险页，账号不记为完成")
        self._log(
            "info",
            f"起号结束：推关 {self._progress.stage_runs} 关 · 副本 {self._progress.dungeons_done} 次"
            f" · 塔 {self._progress.tower_floors} 层 · 游历 {self._progress.travel_spent} 体力"
            f" · 提升 {self._progress.upgrade_steps} 步 · 失败 {self._progress.stage_fails} 次",
        )

    async def _baseline(self, session_id: str) -> None:
        screen = await self._read(session_id)
        stamina = self._parse_stamina(screen)
        power = self._parse_power(screen)
        if stamina is not None:
            self._progress.stamina = stamina
        if power is not None:
            self._progress.power = power
        detected = self._detect_account_name(screen)
        if detected == FORBIDDEN_ACCOUNT:
            raise AutomationUnavailable(f"检测到主账号「{FORBIDDEN_ACCOUNT}」，拒绝执行")
        if self._account and detected and detected != self._account:
            raise AutomationUnavailable(
                f"账号身份不符：期望「{self._account}」，实际「{detected}」"
            )
        if not self._account:
            if detected:
                self._account = detected
                self._log("info", f"账号识别：「{detected}」")
                try:
                    ensure_account(detected, power=self._progress.power)
                except OSError as exc:
                    self._log("warn", f"账号登记失败：{exc}")
        self._log(
            "info",
            f"基线：战力 {self._progress.power or '未知'} · 体力 {self._progress.stamina or '未知'}",
        )

    @staticmethod
    def _detect_account_name(screen: Screen) -> str:
        """主城左上角的角色名：短文本、非数字、非固定标签。"""
        for item in screen.items:
            left, top, right, bottom = item.bounds
            cx, cy = (left + right) / 2, (top + bottom) / 2
            text = item.text.strip()
            if cx >= 0.30 or cy >= 0.12:
                continue
            if not 2 <= len(text) <= 8 or re.search(r"\d|/|%", text):
                continue
            if text in {"战力", "等级", "经验", "冒险", "活动", "商城"}:
                continue
            return text
        return ""

    async def _collect_and_record(
        self, session_id: str, work: str, config: CategoryConfig
    ) -> None:
        """执行一类收集任务；只有真的产生收集动作才记入账号完成情况。"""
        field = f"{work}_steps"
        before = getattr(self._progress, field)
        await self._collect_entries(session_id, config)
        if getattr(self._progress, field) > before:
            self._record_work(work)
        else:
            self._log("info", f"{config.name}：本次没有可领取的内容，不计入完成")

    # ---------- 六项日常专项 ----------
    # 底部导航多数是纯图标，OCR 读不到「商城/装备」文字，命中不到时用已验证坐标兜底。
    NAV_SHOP_POINT = (0.100, 0.941)
    NAV_EQUIP_POINT = (0.252, 0.950)

    @staticmethod
    def _bottom_nav(screen: Screen, word: str) -> OcrItem | None:
        """底部导航栏的具名入口（cy 靠下才算，避免命中页内同名标题）。"""
        for item in screen.items:
            if item.text.strip() == word and (item.bounds[1] + item.bounds[3]) / 2 > NAV_BOTTOM_CY:
                return item
        return None

    async def _tap_nav_shop(self, session_id: str, screen: Screen) -> None:
        """进入商城 tab：OCR 命中「商城」则点它，否则点已验证的图标坐标。"""
        shop = self._bottom_nav(screen, "商城")
        if shop is not None:
            await self._tap(session_id, shop)
        else:
            self._log("info", "商城入口无文字锚点，用图标坐标兜底")
            await self._tap_point(session_id, *self.NAV_SHOP_POINT, wait=0.6)

    async def _close_reward_dialog(self, session_id: str) -> None:
        """关闭领取成功弹窗；只认明确的「点击关闭」，绝不碰购买类按钮。"""
        for _ in range(3):
            screen = await self._read(session_id)
            close = screen.find_exact("点击关闭")
            if close is None:
                return
            await self._tap(session_id, close)
            await self._wait(0.4, "debounce")

    async def _daily_supply(self, session_id: str) -> None:
        """1) 商城 → 滑到底部冒险者补给箱 → 免费领取；有「后免费」倒计时则跳过。"""
        await self._ensure_adventure(session_id)
        screen = await self._read(session_id)
        await self._tap_nav_shop(session_id, screen)
        # 商城是长列表，向下滑动把补给箱区带进视野
        for _ in range(6):
            await self._adapter_getter().swipe(session_id, 0.5, 0.78, 0.5, 0.28, 450)
            await self._wait(0.3)
            screen = await self._read(session_id)
            if screen.has(SUPPLY_LABEL):
                break
        screen = await self._read(session_id)
        supply = screen.find(SUPPLY_LABEL)
        if supply is None:
            self._log("warn", "专项1 补给箱：滑到底部仍未找到冒险者补给箱，跳过")
            await self._back_to_adventure(session_id)
            return
        # 倒计时文本本身含「后免费」，必须先排除，否则会把倒计时当成领取按钮（真机坑）
        claim: OcrItem | None = None
        for item in screen.items:
            text = item.text.strip()
            if SUPPLY_WAIT_WORD in text:
                continue
            if any(word == text or word in text for word in SUPPLY_CLAIM_WORDS):
                claim = item
                break
        countdown = any(SUPPLY_WAIT_WORD in t for t in screen.texts())
        if claim is not None:
            self._log("info", f"补给箱：点击「{claim.text}」")
            await self._tap(session_id, claim)
            await self._close_reward_dialog(session_id)
            self._progress.supply_claims += 1
        elif countdown:
            self._log("info", "补给箱：仍在免费倒计时中，跳过")
        else:
            # 关键按钮无文字（钥匙 + 计数角标），点已验证的补给箱按钮位
            cx = (supply.bounds[0] + supply.bounds[2]) / 2
            await self._tap_point(session_id, min(max(cx, 0.2), 0.45), 0.79, wait=0.5)
            await self._close_reward_dialog(session_id)
            self._progress.supply_claims += 1
            self._log("info", "补给箱：点击补给箱按钮并关闭奖励")
        await self._back_to_adventure(session_id)

    async def _daily_gift(self, session_id: str) -> None:
        """2) 商城 → 礼包商城 → 免费礼包（显示「已领取」则跳过）。"""
        await self._ensure_adventure(session_id)
        screen = await self._read(session_id)
        await self._tap_nav_shop(session_id, screen)
        screen = await self._read(session_id)
        mall = screen.find(GIFT_MALL)
        if mall is None:
            self._log("warn", "专项2 免费礼包：未找到礼包商城入口，跳过")
            await self._back_to_adventure(session_id)
            return
        await self._tap(session_id, mall)
        screen = await self._read(session_id)
        if screen.has("已领取"):
            self._log("info", "免费礼包：今日已领取，跳过")
            await self._back_to_adventure(session_id)
            return
        gift = screen.find(FREE_GIFT_LABEL)
        if gift is None:
            self._log("warn", "专项2 免费礼包：未找到免费礼包栏，跳过")
            await self._back_to_adventure(session_id)
            return
        # 「免费」按钮与免费礼包同一栏，OCR 常把「免费」识别出来
        free = screen.find_exact(FREE_GIFT_BTN) or screen.find(FREE_GIFT_BTN)
        if free is None:
            self._log("warn", "专项2 免费礼包：未找到免费按钮，跳过")
            await self._back_to_adventure(session_id)
            return
        self._log("info", f"免费礼包：点击「{free.text}」")
        await self._tap(session_id, free)
        await self._close_reward_dialog(session_id)
        self._progress.gift_claims += 1
        await self._back_to_adventure(session_id)

    async def _daily_enhance(self, session_id: str) -> None:
        """3) 装备 → 一键强化。真机无此文案，映射到工坊「一键合成」。"""
        await self._ensure_adventure(session_id)
        screen = await self._read(session_id)
        equip = self._bottom_nav(screen, "装备")
        if equip is None:
            # 装备入口是纯图标，OCR 常读不到「装备」文字；用已验证坐标兜底
            await self._tap_point(session_id, 0.252, 0.950, wait=0.6)
        else:
            await self._tap(session_id, equip)
        screen = await self._read(session_id)
        direct = screen.find(*ENHANCE_WORDS)
        if direct is not None:
            self._log("info", f"装备强化：点击「{direct.text}」")
            await self._tap(session_id, direct)
            await self._close_reward_dialog(session_id)
            self._progress.enhance_steps += 1
            await self._back_to_adventure(session_id)
            return
        workshop = screen.find(WORKSHOP)
        if workshop is None:
            self._log("warn", "专项3 装备强化：未找到工坊或一键强化，跳过")
            await self._back_to_adventure(session_id)
            return
        await self._tap(session_id, workshop)
        screen = await self._read(session_id)
        # OCR 常把「一键合成」读成「键合成」，用后者做包含匹配
        synth = screen.find("键合成", "一键合成")
        if synth is None:
            self._log("warn", "专项3 装备强化：工坊内未找到一键合成，跳过")
            await self._back_to_adventure(session_id)
            return
        self._log("info", f"装备强化：工坊点击「{synth.text}」（真机等价一键强化）")
        await self._tap(session_id, synth)
        await self._close_reward_dialog(session_id)
        self._progress.enhance_steps += 1
        await self._back_to_adventure(session_id)

    async def _daily_privilege(self, session_id: str) -> None:
        """4) 冒险 → 左侧特权卡 → 领取全部。"""
        await self._ensure_adventure(session_id)
        screen = await self._read(session_id)
        card = screen.find(PRIVILEGE_LABEL)
        if card is None:
            # 特权卡在左侧纯图标栏，OCR 命中不到时用已验证坐标兜底
            await self._tap_point(session_id, 0.062, 0.228, wait=0.6)
        else:
            await self._tap(session_id, card)
        screen = await self._read(session_id)
        if screen.has("已领取"):
            self._log("info", "特权卡：今日已领取，跳过")
            await self._back_to_adventure(session_id)
            return
        claim = screen.find_exact(CLAIM_ALL) or screen.find(CLAIM_ALL)
        if claim is None:
            self._log("warn", "专项4 特权卡：未找到领取全部，跳过")
            await self._back_to_adventure(session_id)
            return
        self._log("info", f"特权卡：点击「{claim.text}」")
        await self._tap(session_id, claim)
        await self._close_reward_dialog(session_id)
        self._progress.privilege_claims += 1
        await self._back_to_adventure(session_id)

    async def _open_side_menu(self, session_id: str) -> bool:
        """展开冒险页左侧三横菜单。"""
        screen = await self._read(session_id)
        menu = screen.find(*MENU_WORDS)
        if menu is not None:
            await self._tap(session_id, menu)
        else:
            await self._tap_point(session_id, 0.081, 0.159, wait=0.6)
        screen = await self._read(session_id)
        return screen.has(MAIL_LABEL) or screen.has(FRIEND_LABEL)

    async def _daily_mail_friend(self, session_id: str) -> None:
        """5) 三横 → 邮件一键领取；三横 → 好友 → 游戏好友 → 一键领取赠送。"""
        # 邮件
        await self._ensure_adventure(session_id)
        if await self._open_side_menu(session_id):
            screen = await self._read(session_id)
            mail = screen.find(MAIL_LABEL)
            if mail is not None:
                await self._tap(session_id, mail)
                screen = await self._read(session_id)
                claim = screen.find(MAIL_CLAIM, "键领取")
                if claim is not None:
                    self._log("info", f"邮件：点击「{claim.text}」")
                    await self._tap(session_id, claim)
                    await self._close_reward_dialog(session_id)
                    self._progress.mail_claims += 1
                else:
                    self._log("info", "邮件：无可领取内容")
            else:
                self._log("warn", "专项5 邮件：未找到邮件入口")
        else:
            self._log("warn", "专项5 邮件：三横菜单未展开")
        await self._back_to_adventure(session_id)

        # 好友
        await self._ensure_adventure(session_id)
        if await self._open_side_menu(session_id):
            screen = await self._read(session_id)
            friend = screen.find(FRIEND_LABEL)
            if friend is not None:
                await self._tap(session_id, friend)
                screen = await self._read(session_id)
                tab = screen.find(GAME_FRIEND_TAB)
                if tab is not None:
                    await self._tap(session_id, tab)
                    screen = await self._read(session_id)
                claim = screen.find(FRIEND_CLAIM, "键领取赠送")
                if claim is not None:
                    self._log("info", f"好友：点击「{claim.text}」")
                    await self._tap(session_id, claim)
                    await self._close_reward_dialog(session_id)
                    self._progress.friend_claims += 1
                else:
                    self._log("info", "好友：无可领取赠送")
            else:
                self._log("warn", "专项5 好友：未找到好友入口")
        else:
            self._log("warn", "专项5 好友：三横菜单未展开")
        await self._back_to_adventure(session_id)

    @staticmethod
    def _goblin_pickaxe(screen: Screen) -> int | None:
        """读取底部镐头剩余数（如 60/60）；顶部体力计数 cy 很小，需排除。"""
        for item in screen.items:
            if (item.bounds[1] + item.bounds[3]) / 2 < 0.85:
                continue
            match = GOBLIN_PICKAXE_PATTERN.match(item.text.strip())
            if match:
                return int(match.group(1))
        return None

    async def _daily_goblin(self, session_id: str) -> None:
        """6) 活动 → 挑战 → 哥布林矿工 → 逐格挖掘直到镐头耗尽/无法挖掘。"""
        await self._ensure_adventure(session_id)
        screen = await self._read(session_id)
        activity = screen.find(ACTIVITY_ENTRY)
        if activity is None:
            self._log("warn", "专项6 哥布林：未找到活动入口，跳过")
            return
        await self._tap(session_id, activity)
        screen = await self._read(session_id)
        tab = screen.find(CHALLENGE_TAB)
        if tab is None:
            self._log("warn", "专项6 哥布林：未找到挑战 tab，跳过")
            await self._back_to_adventure(session_id)
            return
        await self._tap(session_id, tab)
        screen = await self._read(session_id)
        goblin = screen.find(GOBLIN_ENTRY)
        if goblin is None:
            self._log("warn", "专项6 哥布林：未找到哥布林矿工入口，跳过")
            await self._back_to_adventure(session_id)
            return
        await self._tap(session_id, goblin)
        await self._wait(0.6)

        # 「自动挖矿」是付费入口（68元），绝不点击；只逐格点矿块
        picks = 0
        for cell_x, cell_y in GOBLIN_CELLS:
            if self._stopping or picks >= GOBLIN_MAX_TAPS:
                break
            screen = await self._read(session_id)
            if any(word in text for text in screen.texts() for word in GOBLIN_NO_MORE):
                self._log("info", "哥布林：已无法挖掘，停止")
                break
            remaining = self._goblin_pickaxe(screen)
            if remaining is not None and remaining <= 0:
                self._log("info", "哥布林：镐头已耗尽，停止")
                break
            if screen.find_exact("点击关闭") is not None:
                await self._close_reward_dialog(session_id)
            await self._tap_point(session_id, cell_x, cell_y, wait=0.3)
            picks += 1
            self._progress.goblin_digs += 1
        self._log("info", f"哥布林矿工：本轮挖掘 {picks} 格")
        await self._back_to_adventure(session_id)

    async def _daily_specials(self, session_id: str) -> None:
        """六项新增日常专项，逐项独立异常隔离；单项失败不影响其余。"""
        tasks: tuple[tuple[str, Callable[[], Any]], ...] = (
            ("补给箱", lambda: self._daily_supply(session_id)),
            ("免费礼包", lambda: self._daily_gift(session_id)),
            ("装备强化", lambda: self._daily_enhance(session_id)),
            ("特权卡", lambda: self._daily_privilege(session_id)),
            ("邮件好友", lambda: self._daily_mail_friend(session_id)),
            ("哥布林矿工", lambda: self._daily_goblin(session_id)),
        )
        for name, work in tasks:
            if self._stopping:
                return
            try:
                await work()
            except Exception as exc:  # noqa: BLE001 - 单项失败不阻断其余专项
                self._log("warn", f"日常专项「{name}」未完成：{exc}")

    async def _enter_guild_hall(self, session_id: str) -> Screen | None:
        """从冒险页进入公会页；兼容升级 toast 遮挡标题和直接落在子页的情况。"""
        await self._ensure_adventure(session_id)
        tapped_icon = False
        for _ in range(8):
            if self._stopping:
                return None
            screen = await self._read(session_id)
            texts = "|".join(screen.texts())
            hall = screen.find_exact(GUILD_HALL)
            if hall is not None:
                await self._tap(session_id, hall)
                await self._wait(0.6)
                return await self._read(session_id)
            anchor = next(
                (item for word in GUILD_PAGE_ANCHORS if (item := screen.find_exact(word))),
                None,
            )
            if anchor is not None:
                return screen
            if any(word in texts for word in GUILD_TOAST_WORDS):
                # toast 只是一闪而过的提示，不能拿它当「未入会」的证据
                await self._wait(0.7, "guild_toast")
                continue
            if not tapped_icon:
                tapped_icon = True
                await self._tap_point(session_id, *GUILD_ICON, wait=1.0)
                continue
            await self._wait(0.5, "guild_nav")
        return None

    async def _guild(self, session_id: str) -> None:
        """公会日常：进入公会大厅完成免费捐献；未加入公会或免费不可用时跳过。

        免费次数用完后捐献按钮会变成宝石消耗，因此只有 OCR 确认「免费」文字才点击。
        """
        screen = await self._enter_guild_hall(session_id)
        if screen is None:
            self._log("warn", "未确认公会页，跳过公会（可能未加入公会）")
            return
        donate = None
        for _ in range(4):
            donate = screen.find_exact("捐献")
            if donate is not None:
                break
            await self._wait(0.4, "ocr_poll")
            screen = await self._read(session_id)
        if donate is None:
            self._log("warn", "公会信息页未找到「捐献」，跳过")
            await self._back_to_adventure(session_id)
            return
        await self._tap(session_id, donate)
        dialog = None
        for attempt in range(6):
            screen = await self._read(session_id)
            # 真机 OCR 常漏读标题；用「今日剩余次数 / 免费」任一独有文案确认弹窗
            dialog = screen.find("公会捐献", "今日剩余次数", "免费")
            if dialog is not None:
                break
            if attempt == 2:
                # 可能第一下点空（公会页刚打开动画未结束），再点一次捐献
                await self._tap(session_id, donate)
            await self._wait(0.4, "ocr_poll")
        if dialog is None:
            self._log("warn", "未确认公会捐献弹窗，跳过")
            # 真机弹窗 X 在 cy≈0.78；旧坐标 0.909 会点到下层「公会管理」
            await self._tap_point(session_id, 0.5, 0.78, wait=0.8)
            await self._back_to_adventure(session_id)
            return
        free = screen.find("免费")
        if free is None:
            self._log("info", "公会免费捐献不可用（已用完或未解锁），跳过")
            await self._tap_point(session_id, 0.5, 0.78, wait=0.8)
            await self._back_to_adventure(session_id)
            return
        await self._tap(session_id, free)
        self._progress.guild_steps += 1
        self._log("info", "公会免费捐献完成")
        screen = await self._read(session_id)
        close = screen.find_exact("点击关闭")
        if close is not None:
            await self._tap(session_id, close)
        await self._back_to_adventure(session_id)

    async def _guild_raid(self, session_id: str) -> None:
        """公会讨伐：图标进公会 → OCR 确认讨伐入口 → 执行挑战/扫荡。

        真机 UI 文案尚未逐页校准，因此这里只认明确的入口与执行按钮；
        认不出就记日志跳过，绝不盲点坐标，避免误触付费或高难内容。
        """
        screen = await self._enter_guild_hall(session_id)
        if screen is None:
            self._log("warn", "未确认公会页，跳过公会讨伐")
            return
        raid = screen.find("公会讨伐", "讨伐")
        if raid is None:
            self._log("info", "公会页未找到讨伐入口，跳过")
            await self._back_to_adventure(session_id)
            return
        self._log("info", f"进入公会讨伐：{raid.text}")
        await self._tap(session_id, raid)
        for _ in range(6):
            if self._stopping:
                return
            screen = await self._read(session_id)
            # 精确文案匹配，避免把「挑战之塔」等其它入口当成讨伐动作
            action = screen.find_exact(
                "一键讨伐", "一键扫荡", "扫荡", "开始讨伐", "开始挑战", "挑战"
            )
            if action is None:
                break
            self._log("info", f"公会讨伐：点击「{action.text}」")
            await self._tap(session_id, action)
            confirm = (await self._read(session_id)).find_exact("确定", "确认")
            if confirm is not None:
                await self._tap(session_id, confirm)
            self._progress.guild_raids += 1
            self._progress.guild_steps += 1
            await self._wait(0.8)
        if self._progress.guild_raids:
            self._log("info", f"公会讨伐完成 {self._progress.guild_raids} 次")
        else:
            self._log("info", "公会讨伐：未确认可执行的挑战/扫荡按钮，跳过")
        await self._back_to_adventure(session_id)

    def _record_work(self, work: str) -> None:
        """把当前账号这项工作写入账号集合；写盘失败不影响主流程。"""
        if not self._account:
            return
        try:
            entry = record_work(
                self._account,
                work,
                power=self._progress.power,
                stamina=self._progress.stamina,
            )
        except OSError as exc:
            self._log("warn", f"账号记录写入失败：{exc}")
            return
        if entry is not None:
            self._log("info", f"账号「{self._account}」完成{WORK_LABELS[work]}并已记录")

    def _parse_stamina(self, screen: Screen) -> int | None:
        for item in screen.items:
            match = SERVER_STAMINA_PATTERN.search(item.text)
            if match and int(match.group(2)) >= 20:
                return int(match.group(1))
        return None

    def _parse_power(self, screen: Screen) -> int | None:
        for item in screen.items:
            match = SERVER_POWER_PATTERN.search(item.text)
            if match:
                value = float(match.group(1))
                scale = {"万": 10_000, "亿": 100_000_000}.get(match.group(2), 1)
                return int(value * scale)
        for item in screen.items:
            left, top, right, bottom = item.bounds
            cx, cy = (left + right) / 2, (top + bottom) / 2
            if cx >= 0.35 or not 0.075 <= cy <= 0.12:
                continue
            match = COMPACT_POWER_PATTERN.fullmatch(item.text.strip())
            if match:
                scale = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[
                    match.group(2).upper()
                ]
                return int(float(match.group(1)) * scale)
        return None

    async def _open_activity_tab(self, session_id: str, tab: str) -> Screen | None:
        await self._ensure_adventure(session_id)
        screen = await self._read(session_id)
        activity = screen.find_exact("活动")
        if activity is None:
            self._log("warn", "未找到活动入口，跳过")
            return None
        await self._tap(session_id, activity)
        screen = await self._read(session_id)
        tab_anchor = screen.find_exact(tab)
        if tab_anchor is None:
            self._log("warn", f"活动页未找到「{tab}」标签，跳过")
            return None
        await self._tap(session_id, tab_anchor)
        return await self._read(session_id)

    async def _dungeons(self, session_id: str) -> None:
        """副本：先打最高层，失败则扫荡剩余次数。"""
        screen: Screen | None = None
        for entry in DUNGEON_ENTRIES:
            if self._stopping:
                return
            for _ in range(2):
                if self._stopping:
                    return
                if screen is None:
                    screen = await self._open_activity_tab(session_id, "副本")
                    if screen is None:
                        await self._back_to_adventure(session_id)
                        return
                anchor = screen.find(entry)
                if anchor is None:
                    self._log("warn", f"未找到副本「{entry}」，跳过")
                    break
                anchor_cy = (anchor.bounds[1] + anchor.bounds[3]) / 2
                locked = any(
                    "解锁" in item.text
                    and anchor_cy
                    < (item.bounds[1] + item.bounds[3]) / 2
                    < anchor_cy + 0.11
                    for item in screen.items
                )
                if locked:
                    self._log("info", f"{entry}：尚未解锁，跳过")
                    break
                remaining = await self._dungeon_remaining(session_id, screen, anchor)
                if remaining is None:
                    self._log("warn", f"{entry}：未确认剩余次数，跳过")
                    break
                if remaining <= 0:
                    self._log("info", f"{entry}：剩余 0 次，跳过")
                    break
                self._log("info", f"进入副本：{entry}（剩余 {remaining} 次）")
                await self._tap(session_id, anchor, dy=-0.025)
                detail = await self._read(session_id)
                start = detail.find("开始挑战", "挑战", "进入挑战") or detail.find_exact("挑战")
                screen = None
                if start is None:
                    self._log("warn", f"{entry}：未找到挑战按钮，跳过剩余次数")
                    break
                await self._tap(session_id, start)
                # 真机实测：副本「挑战」是 4 秒左右的自动战斗，直接出「胜利/确定」结算，
                # 不会进入推关那种「下一天/选技能」循环。复用 _play_run 必然空转超时。
                finished = await self._play_dungeon_run(session_id, entry)
                if finished:
                    self._progress.dungeons_done += 1
                    self._log("info", f"{entry}：挑战通过")
                    continue
                self._log("warn", f"{entry}：挑战失败，改为扫荡剩余次数")
                await self._sweep_dungeon(session_id, entry)
                break
        await self._back_to_adventure(session_id)

    async def _play_dungeon_run(self, session_id: str, entry: str) -> bool:
        """副本战斗：自动开打，等「胜利/失败」结算页并点掉「确定」。"""
        for _ in range(40):
            if self._stopping:
                return False
            screen = await self._read(session_id)
            # 真机：胜利后有时跳过「确定」直接弹「奖励 / 点击关闭」，
            # 后台已扣掉一次挑战次数；这同样是成功，必须计数并关掉弹窗。
            if screen.has("奖励") and screen.find_exact("点击关闭") is not None:
                self._log("info", f"{entry}：副本奖励弹窗，确认挑战完成")
                await self._tap_point(session_id, 0.5, 0.88, wait=0.5)
                return True
            result = screen.find_exact("胜利", "失败")
            if result is not None:
                if result.text == "失败":
                    self._log("warn", f"{entry}：自动战斗失败")
                    return False
                confirm = screen.find_exact("确定", "确认")
                if confirm is None:
                    await self._wait(0.3, "ocr_poll")
                    continue
                self._log("info", f"{entry}：胜利结算，点击「{confirm.text}」")
                await self._tap(session_id, confirm)
                await self._wait(0.6)
                # 结算后可能还有奖励弹窗，按已验证的关闭位处理
                follow = await self._read(session_id)
                close = follow.find_exact("点击关闭")
                if close is not None:
                    await self._tap(session_id, close)
                    await self._wait(0.4)
                return True
            # 仍停留在副本详情页说明「挑战」没有真正开战
            if screen.find_exact("扫荡上一难度") is not None:
                return False
            await self._wait(0.5, "dungeon_poll")
        self._log("warn", f"{entry}：等待副本结算超时")
        return False

    async def _dungeon_remaining(
        self,
        session_id: str,
        screen: Screen,
        anchor: OcrItem,
    ) -> int | None:
        anchor_cy = (anchor.bounds[1] + anchor.bounds[3]) / 2
        labels = []
        for item in screen.items:
            cy = (item.bounds[1] + item.bounds[3]) / 2
            if item.text.strip() == "剩余次数" and 0.025 < cy - anchor_cy < 0.11:
                labels.append(item)
        if not labels:
            return None
        label = min(labels, key=lambda item: item.bounds[1])
        region = (
            max(0.0, label.bounds[0] - 0.04),
            max(0.0, label.bounds[1] - 0.01),
            min(1.0, label.bounds[2] + 0.06),
            min(1.0, label.bounds[3] + 0.04),
        )
        local = await self._read(session_id, region=region)
        for item in local.items:
            if re.fullmatch(r"\d+", item.text.strip()):
                return int(item.text.strip())
        return None

    async def _sweep_dungeon(self, session_id: str, entry: str) -> None:
        """扫荡：优先复用当前已打开的副本详情弹窗，避免重进 tab 后找不到按钮。"""
        screen = await self._read(session_id)
        if screen.find_exact("扫荡上一难度") is None:
            screen = await self._open_activity_tab(session_id, "副本")
            if screen is None:
                return
            anchor = screen.find(entry)
            if anchor is None:
                self._log("warn", f"{entry}：无法重新进入，扫荡跳过")
                return
            await self._tap(session_id, anchor, dy=-0.025)
            screen = await self._read(session_id)
        sweep = screen.find_exact("扫荡上一难度", "一键扫荡") or screen.find_exact("扫荡")
        if sweep is None:
            self._log("warn", f"{entry}：无扫荡入口（可能未通关过），跳过")
            return
        self._log("info", f"{entry}：点击「{sweep.text}」")
        await self._tap(session_id, sweep)
        for _ in range(10):
            if self._stopping:
                return
            screen = await self._read(session_id)
            confirm = screen.find_exact("确定", "确认")
            if confirm is not None:
                await self._tap(session_id, confirm)
                await self._wait(0.6)
                self._progress.dungeons_done += 1
                self._progress.dungeon_sweeps += 1
                self._log("info", f"{entry}：扫荡完成")
                return
            close = screen.find_exact("点击关闭")
            if close is not None:
                await self._tap(session_id, close)
                await self._wait(0.4)
                if screen.has("奖励"):
                    # 扫荡完成同样可能直接给「奖励/点击关闭」而不是确定按钮
                    self._progress.dungeons_done += 1
                    self._progress.dungeon_sweeps += 1
                    self._log("info", f"{entry}：扫荡完成（奖励弹窗）")
                    return
                continue
            if screen.find_exact("失败") is not None:
                self._log("warn", f"{entry}：扫荡失败，不计数")
                return
            await self._wait(0.5, "sweep_poll")
        self._log("warn", f"{entry}：扫荡未确认结算，不计数")

    async def _tower_bootstrap(self, session_id: str) -> None:
        if self._tower_floors <= 0:
            return
        fails = 0
        for floor in range(self._tower_floors):
            if self._stopping:
                return
            screen = await self._open_activity_tab(session_id, "挑战")
            if screen is None:
                return
            anchor = None
            for word in BOOTSTRAP_TOWER_ENTRIES:
                anchor = screen.find_exact(word) or screen.find(word)
                if anchor is not None:
                    break
            if anchor is None:
                self._log("warn", "未找到挑战之塔入口，跳过爬塔")
                return
            self._log("info", f"爬塔第 {floor + 1} 层：进入「{anchor.text}」")
            await self._tap(session_id, anchor)
            screen = await self._read(session_id)
            recommended = None
            for item in screen.items:
                left, top, right, bottom = item.bounds
                cx, cy = (left + right) / 2, (top + bottom) / 2
                if not (0.35 <= cx <= 0.70 and 0.55 <= cy <= 0.75):
                    continue
                match = COMPACT_POWER_PATTERN.fullmatch(item.text.strip())
                if match is None:
                    continue
                scale = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[
                    match.group(2).upper()
                ]
                recommended = int(float(match.group(1)) * scale)
                break
            if recommended is None:
                self._log("warn", "未确认挑战之塔页或建议战力，结束爬塔")
                return
            if self._progress.power and recommended > self._progress.power:
                self._log(
                    "info",
                    f"建议战力 {recommended} 高于当前 {self._progress.power}，跳过爬塔",
                )
                return
            start = (
                screen.find_exact(TOWER_START)
                or screen.find_exact("挑战", "继续挑战")
                or screen.find_exact("开始")
            )
            if start is None:
                self._log("warn", "爬塔页未找到开始按钮，结束爬塔")
                return
            await self._tap(session_id, start)
            finished = await self._play_run(session_id)
            if finished and not self._last_run_failed:
                self._progress.tower_floors += 1
                fails = 0
            else:
                fails += 1
                self._log("warn", f"爬塔失败（连续 {fails} 次）")
                if fails >= 2:
                    self._log("warn", "爬塔连续失败 2 次，停止")
                    return

    async def _travel_until_low(self, session_id: str) -> bool:
        """反复游历，直到体力低于 travelStamina（默认 100）或无法继续。

        返回 True 表示体力已确认并压到下限，可以继续提升与推关；
        返回 False 表示无法确认体力或游历失败，调用方应退回单轮推关。
        """
        floor = self._travel_stamina
        if floor <= 0:
            return True
        for _ in range(10):
            if self._stopping:
                return False
            screen = await self._read(session_id)
            stamina = self._parse_stamina(screen)
            if stamina is None:
                self._log("warn", "未确认当前体力，跳过游历")
                return False
            self._progress.stamina = stamina
            if stamina < floor:
                self._log("info", f"体力 {stamina} < {floor}，停止游历")
                return True
            if not await self._travel(session_id):
                return False
        return False

    async def _travel(self, session_id: str) -> bool:
        """游历一次：确认目标倍率后才扣体力，不足则留给推关。"""
        if self._stopping or self._travel_stamina <= 0:
            return False
        await self._ensure_adventure(session_id)
        screen = await self._read(session_id)
        stamina = self._parse_stamina(screen)
        if stamina is None:
            self._log("warn", "未确认当前体力，跳过游历")
            return False
        self._progress.stamina = stamina
        if stamina < TRAVEL_COST:
            self._log(
                "info",
                f"体力 {stamina} < {TRAVEL_COST}，跳过游历，留给推关",
            )
            return False
        anchor = screen.find("历险", "游历")
        if anchor is None:
            self._log("warn", "未找到历险/游历入口，跳过")
            return False
        self._log("info", f"进入游历：停止阈值 {self._travel_stamina} · 本次固定 {TRAVEL_COST} 体力")
        await self._tap(session_id, anchor, dy=-0.025)

        target_tier = f"{TRAVEL_COST // 5}倍奖励"
        tiers = TRAVEL_TIERS
        last_tier_index = -1
        waiting_for_change = False
        for _ in range(12):
            screen = await self._read(session_id)
            start = screen.find_exact("开始游历")
            tier = next((name for name in tiers if screen.find_exact(name) is not None), None)
            if start is None or tier is None:
                # 面板尚未打开或 OCR 读到旧帧时，不能在未知页面盲点加档。
                await self._wait(0.3, "debounce")
                continue
            if tier == target_tier:
                break
            tier_index = tiers.index(tier)
            if waiting_for_change:
                if tier_index <= last_tier_index:
                    # 未确认上一次加档已生效，不重复点击，避免从 20 倍绕回 1 倍。
                    await self._wait(0.3, "debounce")
                    continue
                waiting_for_change = False
            # 倍率 + 按钮固定在右下；每次点击后必须观察到档位前进。
            await self._adapter_getter().tap(session_id, 0.725, 0.835, 80, 6)
            last_tier_index = tier_index
            waiting_for_change = True
            await self._wait(0.3, "debounce")
        else:
            self._log("warn", f"未确认游历档位「{target_tier}」，不消耗体力")
            await self._back_to_adventure(session_id)
            return False

        start = screen.find_exact("开始游历")
        if start is None:
            self._log("warn", "游历页未找到开始按钮，返回")
            await self._back_to_adventure(session_id)
            return False
        await self._tap(session_id, start)
        completed = False
        for _ in range(60):
            if self._stopping:
                return False
            screen = await self._read(session_id)
            if screen.find("游历结束", "游历完成") is not None:
                back = screen.find_exact("返回")
                if back is not None:
                    await self._tap(session_id, back)
                    completed = True
                    break
                continue
            cont = screen.find("继续游历")
            if cont is not None:
                await self._tap(session_id, cont)
                continue
            if screen.find_exact(*WHEEL_TITLES) is not None:
                spin = screen.find_exact("转动")
                back = screen.find_exact("返回")
                if spin is not None:
                    await self._tap(session_id, spin)
                elif back is not None:
                    await self._tap(session_id, back)
                continue
            if screen.has("点击关闭"):
                await self._adapter_getter().tap(session_id, 0.5, 0.88, 80, 6)
                await self._wait(0.3, "debounce")
                continue
            await self._wait(0.8, "ocr_poll")
        if completed:
            self._progress.travel_spent += TRAVEL_COST
            self._log("info", f"游历结束，累计投入 {self._progress.travel_spent} 体力")
        else:
            self._log("warn", "游历未确认结算，不计入已完成次数")
        await self._back_to_adventure(session_id)
        return completed

    async def _bootstrap_stage(self, session_id: str) -> None:
        for _ in range(30):
            if self._stopping:
                return
            if self._max_runs and self._progress.stage_runs >= self._max_runs:
                self._log("info", "达到本轮推关上限，进入提升")
                return
            if self._progress.stage_fail_streak >= self._max_stage_fails:
                self._log(
                    "warn",
                    f"同一关连续失败 {self._progress.stage_fail_streak} 次，停止推关",
                )
                return
            screen = await self._read(session_id)
            if self._in_run(screen):
                finished = await self._play_run_with_retries(session_id)
            else:
                start = screen.adventure_entry()
                if start is None:
                    await self._ensure_adventure(session_id)
                    screen = await self._read(session_id)
                    start = screen.adventure_entry()
                if start is None:
                    self._log("warn", "未找到「开始」按钮，结束推关")
                    return
                await self._tap(session_id, start)
                finished = await self._play_run_with_retries(
                    session_id, replay=True, record=True
                )
            if finished and not self._last_run_failed:
                self._progress.stage_runs += 1
                self._progress.stage_fail_streak = 0
                screen = await self._read(session_id)
                stamina = self._parse_stamina(screen)
                if stamina is not None:
                    self._progress.stamina = stamina
                    if stamina < 5:
                        self._log("info", f"体力 {stamina} 不足 5，结束推关")
                        return
            elif self._last_run_failed:
                self._progress.stage_fails += 1
                self._progress.stage_fail_streak += 1
                self._log(
                    "warn",
                    f"推关失败：累计 {self._progress.stage_fails} 次，"
                    f"同一关连续 {self._progress.stage_fail_streak} 次",
                )
                return
            else:
                self._log("warn", "续跑后仍未结算，本次不计入失败，结束推关")
                return
        self._log("info", "达到本轮推关上限，进入提升")

    async def _retry_stage(self, session_id: str) -> None:
        if self._progress.stage_fail_streak < 1:
            return
        if self._progress.stage_fail_streak >= self._max_stage_fails:
            self._log("info", "该关已放弃，不再尝试")
            return
        await self._ensure_adventure(session_id)
        screen = await self._read(session_id)
        start = screen.adventure_entry()
        if start is None:
            self._log("warn", "回推时未找到「开始」按钮，结束")
            return
        self._log("info", "提升完成，回推被卡关卡一次")
        await self._tap(session_id, start)
        finished = await self._play_run(session_id, replay=True, record=True)
        if finished and not self._last_run_failed:
            self._progress.stage_runs += 1
            self._progress.stage_fail_streak = 0
            self._log("info", "回推成功，继续推关")
            await self._bootstrap_stage(session_id)
        else:
            self._progress.stage_fails += 1
            self._progress.stage_fail_streak += 1
            self._log("warn", "回推仍失败，按规则不再尝试")

    async def _upgrade(self, session_id: str) -> None:
        """只走已实测的提升链路：天赋攻防各一级，再强化一次装备。

        2026-11-16 真机修正：点天赋卡片若材料不足，游戏弹出的是「道具获取 /
        金币 / 当前数量 / 黑市购买 / 30元」付费引导弹窗，而不是直接升级。
        旧实现只看「文本变化」就记一次提升，实际是误报，且后续盲点可能误触
        「30元 / 前往」。现在必须：识别材料弹窗→安全关闭（只点底部 X）→
        不记成功；只有「等级 N」数字真的变大才算提升。
        """
        await self._ensure_adventure(session_id)
        # 底部导航是可横向滚动的 tab：真机上「天赋」在 cx 0.67~0.77 间漂移，
        # 优先用 OCR 精确命中标签；读不到再用经验坐标兜底。
        screen = await self._read(session_id)
        talent_tab = screen.find_exact("天赋")
        if talent_tab is not None:
            await self._tap(session_id, talent_tab)
        else:
            await self._adapter_getter().tap(session_id, 0.75, 0.954, 80, 6)
        await self._wait(0.5)
        screen = await self._read(session_id)
        if not screen.has("天赋"):
            self._log("warn", "未确认天赋页，跳过提升")
            return

        for x, name in ((0.50, "攻击"), (0.8125, "防御")):
            before_level = self._talent_level(screen, x)
            if self._has_material_dialog(screen):
                await self._close_material_dialog(session_id)
                self._log("warn", "天赋页残留材料弹窗，已关闭")
                screen = await self._read(session_id)
            if self._has_gem_dialog(screen) and not self._allow_gem_breakthrough:
                self._log("warn", "天赋需要宝石，已按配置跳过")
                break
            await self._adapter_getter().tap(session_id, x, 0.792, 80, 6)
            await self._wait(0.5)
            screen = await self._read(session_id)
            if self._has_material_dialog(screen):
                # 材料/金币不足：这是付费引导弹窗，不是升级成功。
                self._log("warn", f"天赋{name}材料不足，弹出获取引导，跳过")
                await self._close_material_dialog(session_id)
                screen = await self._read(session_id)
                break
            after_level = self._talent_level(screen, x)
            if after_level is not None and before_level is not None and after_level > before_level:
                self._progress.upgrade_steps += 1
                self._log("info", f"天赋{name}提升一次：等级 {before_level} → {after_level}")

        await self._adapter_getter().tap(session_id, 0.25, 0.943, 80, 6)
        await self._wait(0.5)
        screen = await self._read(session_id)
        if screen.has("装备"):
            # 第一个戒指槽位；详情页只点「一键强化」，绝不点旁边的「卸下」。
            await self._adapter_getter().tap(session_id, 0.133, 0.234, 80, 6)
            await self._wait(0.5)
            detail = await self._read(session_id)
            strengthen = detail.find_exact("一键强化")
            if strengthen is not None:
                before_level = self._equip_level(detail)
                await self._tap(session_id, strengthen)
                after = await self._read(session_id)
                if self._has_material_dialog(after):
                    self._log("warn", "装备强化材料不足，已关闭获取引导")
                    await self._close_material_dialog(session_id)
                else:
                    after_level = self._equip_level(after)
                    if (
                        after_level is not None
                        and before_level is not None
                        and after_level > before_level
                    ):
                        self._progress.upgrade_steps += 1
                        self._log("info", f"装备一键强化一次：{before_level} → {after_level}")
                if after.has("卸下"):
                    await self._adapter_getter().tap(session_id, 0.5, 0.792, 80, 6)
                    await self._wait(0.3)
        await self._adapter_getter().tap(session_id, 0.5, 0.954, 80, 6)
        await self._wait(0.5)

    def _talent_level(self, screen: Screen, x: float) -> int | None:
        """读取某个天赋槽位的「等级 N」数字；槽位按 x 坐标就近匹配。"""
        candidates: list[tuple[float, int]] = []
        for item in screen.items:
            m = re.fullmatch(r"等级\s*(\d+)", item.text.strip())
            if not m:
                continue
            cx = (item.bounds[0] + item.bounds[2]) / 2
            candidates.append((abs(cx - x), int(m.group(1))))
        if not candidates:
            return None
        candidates.sort(key=lambda entry: entry[0])
        return candidates[0][1]

    @staticmethod
    def _equip_level(screen: Screen) -> int | None:
        """装备强化等级，真机形如「10/20」；匹配第一个「数字/数字」。"""
        for item in screen.items:
            m = re.fullmatch(r"(\d+)\s*/\s*(\d+)", item.text.strip())
            if m:
                return int(m.group(1))
        return None

    def _has_material_dialog(self, screen: Screen) -> bool:
        """材料不足的付费引导弹窗：含获取引导词且出现货币/价格，避免误判普通页。"""
        texts = screen.texts()
        has_prompt = screen.has("道具获取", "获取途径", "黑市购买", "当前数量")
        has_cost = any(
            screen.has("金币", "钻石", "宝石") or re.search(r"\d+\s*元", t) for t in texts
        )
        return has_prompt and has_cost

    async def _close_material_dialog(self, session_id: str) -> None:
        """只点弹窗底部的圆形 X（真机 0.5,0.885），绝不碰「30元/前往/购买」。"""
        await self._adapter_getter().tap(session_id, 0.5, 0.885, 80, 6)
        await self._wait(0.4)

    def _has_gem_dialog(self, screen: Screen) -> bool:
        return screen.has("宝石") or screen.has("钻石")

    # ---------- 账号切换 ----------

    async def _switch_account(self, session_id: str, account: str) -> bool:
        """通过最近登录角色切号；只有最终主城角色名精确匹配才返回成功。"""
        target = account.strip()
        if not target or target == FORBIDDEN_ACCOUNT:
            return False
        screen = await self._read(session_id)
        current = self._detect_account_name(screen)
        if current == target and screen.adventure_entry() is not None:
            return True
        if current == FORBIDDEN_ACCOUNT:
            self._log("error", f"当前为主账号「{FORBIDDEN_ACCOUNT}」，拒绝自动操作")
            return False
        if screen.adventure_entry() is None:
            if screen.find("公告", "特惠", "礼包") is not None:
                # 当前账号主城被公告/特惠弹窗挡住，先清理再判定
                if not await self._back_to_adventure(session_id):
                    return False
                screen = await self._read(session_id)
                if current == target and screen.adventure_entry() is not None:
                    return True
            self._log("warn", "切号前未确认主城，停止切换")
            return False

        await self._tap_point(session_id, 0.065, 0.060, wait=0.5)
        screen = await self._read(session_id)
        choose = screen.find_exact("选择服务器")
        if choose is not None:
            await self._tap(session_id, choose)
        elif screen.has("个人信息"):
            await self._tap_point(session_id, 0.730, 0.475, wait=0.5)
        else:
            self._log("warn", "个人信息页未找到选择服务器")
            return False

        for _ in range(8):
            screen = await self._read(session_id)
            role = screen.find_exact(target)
            if role is not None:
                await self._tap(session_id, role)
                break
            if not screen.has("最近登录"):
                self._log("warn", "未确认最近登录角色列表")
                return False
            await self._adapter_getter().swipe(session_id, 0.5, 0.72, 0.5, 0.32, 300)
            await self._wait(0.5)
        else:
            self._log("warn", f"最近登录角色中未找到「{target}」")
            return False

        for _ in range(8):
            screen = await self._read(session_id)
            enter = screen.find_exact("开始游戏", "进入游戏")
            if enter is not None:
                await self._tap(session_id, enter)
                break
            await self._wait(1.0, "ocr_poll")
        else:
            return False

        for _ in range(8):
            screen = await self._read(session_id)
            detected = self._detect_account_name(screen)
            if detected == target and screen.adventure_entry() is not None:
                self._log("info", f"已切换并核验账号「{target}」")
                return True
            if detected == target and screen.find("公告", "特惠", "礼包") is not None:
                # 切号成功后可能弹出钥匙特惠等付费弹窗，先清理再核验主城
                if not await self._back_to_adventure(session_id):
                    return False
                continue
            if detected and detected != target:
                self._log("error", f"切号身份不符：期望「{target}」，实际「{detected}」")
                return False
            await self._wait(1.0, "ocr_poll")
        self._log("warn", f"切号后未能核验账号「{target}」")
        return False

    # ---------- 区服遍历（server_sweep） ----------

    async def _server_sweep(self, session_id: str) -> None:
        screen = await self._read(session_id)
        entry = screen.find(*SERVER_LIST_WORDS)
        if entry is None:
            await self._ensure_adventure(session_id)
            screen = await self._read(session_id)
            entry = screen.find(*SERVER_LIST_WORDS)
        if entry is None:
            raise AutomationUnavailable("未找到服务器入口，请先停在主城或选区页")
        self._log("info", f"打开区服列表：「{entry.text}」")
        await self._tap(session_id, entry)
        names = await self._collect_server_names(session_id)
        if not names:
            raise AutomationUnavailable("未能识别区服列表，请检查 OCR 或手动打开选区页")
        self._log("info", f"识别到 {len(names)} 个区服：{' / '.join(names)}")
        start = self._find_server_index(names, self._server_from)
        if start is None:
            raise AutomationUnavailable(f"区服列表中未找到起始区服「{self._server_from}」")
        end = len(names) - 1
        if self._server_to:
            found = self._find_server_index(names, self._server_to)
            if found is None:
                raise AutomationUnavailable(f"区服列表中未找到结束区服「{self._server_to}」")
            end = found
        targets = names[start : end + 1]
        self._log("info", f"待处理区服（{len(targets)}）：{' / '.join(targets)}")
        if self._server_dry_run:
            self._log("info", "当前为区服枚举模式（serverDryRun=true），不执行切换")
            return
        for name in targets:
            if self._stopping:
                return
            if not await self._enter_server(session_id, name):
                self._log("warn", f"进入区服「{name}」失败，跳过")
                continue
            self._progress.servers_done += 1
            self._log("info", f"进入区服「{name}」，开始检测角色")
            await self._bootstrap_or_create(session_id, name)
        self._log("info", f"区服遍历结束：已处理 {self._progress.servers_done} 个区服")

    @staticmethod
    def _find_server_index(names: list[str], target: str) -> int | None:
        if not target:
            return None
        exact = [i for i, name in enumerate(names) if name.strip() == target.strip()]
        if exact:
            return exact[0]
        fuzzy = [i for i, name in enumerate(names) if target.strip() in name]
        return fuzzy[0] if fuzzy else None

    async def _collect_server_names(self, session_id: str) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        last_signature = ""
        for _ in range(12):
            screen = await self._read(session_id)
            signature = "|".join(screen.texts())
            for item in screen.items:
                text = item.text.strip()
                if self._looks_like_server(text) and text not in seen:
                    seen.add(text)
                    names.append(text)
            if signature == last_signature:
                break
            last_signature = signature
            await self._adapter_getter().swipe(session_id, 0.5, 0.72, 0.5, 0.32, 300)
            await self._wait(0.6)
        return names

    @staticmethod
    def _looks_like_server(text: str) -> bool:
        if not text or len(text) < 3 or len(text) > 20:
            return False
        if any(word in text for word in ("进入游戏", "开始游戏", "推荐", "维护", "服务器")):
            return False
        return bool(re.search(r"区$|服$", text)) or ("区" in text and re.search(r"\d", text))

    async def _enter_server(self, session_id: str, name: str) -> bool:
        for _ in range(8):
            screen = await self._read(session_id)
            anchor = screen.find_exact(name) or screen.find(name)
            if anchor is not None:
                self._log("info", f"选择区服「{name}」")
                await self._tap(session_id, anchor)
                screen = await self._read(session_id)
                enter = screen.find(*SERVER_ENTER_WORDS)
                if enter is not None:
                    await self._tap(session_id, enter)
                    await self._wait(1.2)
                    return True
                self._log("warn", f"区服「{name}」未找到进入按钮")
                return False
            await self._adapter_getter().swipe(session_id, 0.5, 0.72, 0.5, 0.32, 300)
            await self._wait(0.5)
        return False

    async def _bootstrap_or_create(self, session_id: str, server: str) -> None:
        for _ in range(8):
            if self._stopping:
                return
            screen = await self._read(session_id)
            if screen.adventure_entry() is not None or screen.find("冒险") is not None:
                self._log("info", f"区服「{server}」已有角色，执行起号")
                await self._bootstrap(session_id)
                return
            create = screen.find("创建角色", "输入角色名", "随机")
            if create is not None:
                self._log("info", f"区服「{server}」无角色，尝试建角")
                await self._create_character(session_id)
                await self._follow_tutorial(session_id)
                await self._bootstrap(session_id)
                return
            await self._wait(1.0)
        self._log("warn", f"区服「{server}」未能识别主城或建角页，跳过")

    async def _create_character(self, session_id: str) -> None:
        screen = await self._read(session_id)
        random_btn = screen.find("随机", "随机名字")
        if random_btn is not None:
            self._log("info", "使用随机角色名")
            await self._tap(session_id, random_btn)
        screen = await self._read(session_id)
        confirm = screen.find("创建角色", "创建", "进入游戏", "确定")
        if confirm is not None:
            await self._tap(session_id, confirm)
        self._progress.accounts_created += 1
        self._log("info", "已尝试建角；若需手工输入角色名，请在设备上完成")
        await self._wait(1.5)

    async def _follow_tutorial(self, session_id: str, max_steps: int = 80) -> None:
        """新手引导跟随：有明确动作就点，否则点屏幕下方推进，直到出现主城「开始」。"""
        for _ in range(max_steps):
            if self._stopping:
                return
            screen = await self._read(session_id)
            if screen.adventure_entry() is not None:
                self._log("info", "新手引导完成，已进入主城")
                return
            action = screen.find(
                "跳过", "确定", "领取", "继续", "点击继续", "下一天", "开始", "关闭"
            )
            if action is not None:
                await self._tap(session_id, action)
            else:
                await self._adapter_getter().tap(session_id, 0.5, 0.86, 80, 6)
            await self._wait(0.5)
        self._log("warn", "新手引导跟随达到步数上限，转入常规流程")

    async def _play_run(
        self,
        session_id: str,
        *,
        replay: bool = False,
        record: bool = False,
    ) -> bool:
        """单局战斗：快速模式先按录制坐标定时点击，必要时回落到逐帧识别。

        返回 True 表示检测到结算并正常结束，False 表示放弃/超时。
        """
        self._last_run_failed = False
        if replay and self._fast_stage and self._stage_script:
            outcome = await self._replay_stage(session_id)
            if outcome is not None:
                return outcome
        self._recorded = []
        self._last_tap_ts = None
        self._recording = record
        try:
            return await self._play_run_ocr(session_id)
        finally:
            self._recording = False
            if record:
                self._remember_recorded()

    async def _play_run_with_retries(
        self,
        session_id: str,
        *,
        replay: bool = False,
        record: bool = False,
    ) -> bool:
        """单局未结算时自动续跑，最多重试 MAX_STAGE_RETRIES 次。

        超时只代表本次预算用完，不算游戏失败，直接在局内继续推进；
        真实失败或界面卡死（`_last_run_failed`）不再重试。续跑不再回放录制序列，
        避免把已推进的局内进度按旧坐标拖回去。
        连续卡住达到阈值时调用「卡住自愈」：杀进程重启一次；重启后仍卡则停止。
        """
        self._hard_stuck = False
        finished = await self._play_run(session_id, replay=replay, record=record)
        retries = 0
        max_retries = LEAN_STAGE_MAX_RETRIES if self._fast_stage else MAX_STAGE_RETRIES
        while not finished and not self._last_run_failed and not self._stopping:
            if retries >= max_retries:
                self._log("warn", f"推关重试 {max_retries} 次仍未结算，停止本局")
                break
            retries += 1
            self._log(
                "info",
                f"推关未结算，自动续跑（第 {retries}/{max_retries} 次）",
            )
            finished = await self._play_run(session_id)
        if not finished and not self._stopping:
            await self._recover_if_stuck(
                session_id, failed=self._last_run_failed, force=self._hard_stuck
            )
        return finished

    async def _recover_if_stuck(
        self, session_id: str, *, failed: bool, force: bool = False
    ) -> bool:
        """卡住自愈：连续卡住/失败达到阈值时，杀进程重启游戏一次。

        `force` 用于已确认的硬卡死（例如事件转盘永久停在「转盘中」），
        不再等连续两局，直接重启；这类界面任何 OCR 兜底点击都不会恢复。
        """
        if self._stopping or self._fatal_stuck:
            return False
        self._stuck_streak += 1
        if not force and self._stuck_streak < STUCK_RESTART_LIMIT:
            self._log("warn", f"连续卡住 {self._stuck_streak}/{STUCK_RESTART_LIMIT} 局，继续观察")
            return False
        recovered = await self._restart_game(
            session_id, f"连续卡住 {self._stuck_streak} 局" if not force else "界面硬卡死"
        )
        if recovered:
            self._stuck_streak = 0
        return recovered

    async def _restart_game(self, session_id: str, reason: str) -> bool:
        """杀进程后经桌面 launcher 重启一次，并等待回到冒险页。"""
        if self._stopping or self._fatal_stuck:
            return False
        if self._restart_count >= RESTART_MAX_TIMES:
            self._fatal_stuck = True
            self._log("error", f"{reason}：已重启过一次仍无法恢复，停止自动化")
            return False

        package = self._game_package()
        self._restart_count += 1
        self._log(
            "warn",
            f"{reason}，杀进程重启游戏（第 {self._restart_count}/{RESTART_MAX_TIMES} 次）",
        )
        try:
            await self._adapter_getter().stop_app(session_id, package)
            await self._wait(RESTART_SETTLE_S, "restart")
            await self._adapter_getter().launch_app(session_id, package)
            await self._wait(2.0, "restart")
            # 重启后可能有开屏广告/登录页，给若干轮把界面拉回冒险页
            for _ in range(12):
                if self._stopping:
                    return False
                if await self._ensure_adventure(session_id):
                    self._log("info", "游戏已重启并回到冒险页，继续任务")
                    return True
                await self._wait(2.0, "restart")
            self._fatal_stuck = True
            self._log("error", "重启后无法回到冒险页，停止自动化")
            return False
        except Exception as exc:  # noqa: BLE001 - 重启失败也要落到状态里
            self._fatal_stuck = True
            self._log("error", f"杀进程重启失败：{exc}")
            return False

    @staticmethod
    def _wheel_stuck(screen: Screen) -> bool:
        """判定事件转盘卡住：OCR 常读不到小字「转盘中」，要用上下文兜底。

        真机 2026-11-16：转盘卡住时只能识别到标题「传说技能」，
        按钮既不是「开始」也没有「继续/返回」结果入口。
        """
        if screen.has(WHEEL_SPIN_HINT):
            return True
        return (
            screen.find_exact("传说技能") is not None
            and screen.find_exact("开始", "继续", "下一天", "返回", "X", "×") is None
        )

    @staticmethod
    def _game_package() -> str:
        """游戏包名：优先环境变量，其次 config，最后默认值。"""
        pkg = os.environ.get("CAPYAUTO_GAME_PACKAGE", "")
        if pkg:
            return pkg
        try:
            from app.config import settings

            return settings.game_package
        except Exception:  # noqa: BLE001 - 配置不可用时用默认值
            return "com.hb.cncapy.and"

    async def _replay_stage(self, session_id: str) -> bool | None:
        """快速模式回放：按录制坐标和间隔定时点击，每 N 次做一次界面校验。

        True/False 表示已经确认结算（False 且 `_last_run_failed` 为真表示真实失败）；
        None 表示无法确认，调用方应回落到逐帧识别。
        """
        taps = self._stage_script
        if not taps:
            return None
        # 主推进锚点与双选项右侧锚点分开：每次主锚点后补一次右侧选项
        option = next((tap for tap in reversed(taps) if tap.kind == "option"), None)
        anchors = [tap for tap in taps if tap.kind != "option"]
        if not anchors:
            anchors = taps
        # 精简模式在「全量录制」基础上再提速：节拍压缩、选项补点更快、
        # 命中抖动加大以提高容错、校验间隔放宽以减少 OCR 次数。
        gap_scale = self._lean_gap_scale
        option_gap = self._lean_option_gap
        tap_jitter = self._lean_jitter
        check_every = self._fast_stage_check_every
        self._log(
            "info",
            f"快速模式：回放 {len(anchors)} 次已录制点击"
            + ("（含右侧选项锚点）" if option is not None else "")
            + f"（节拍 x{gap_scale:g} · 每 {check_every} 次校验一次）",
        )
        for index, tap in enumerate(anchors, 1):
            if self._stopping:
                return False
            jitter = 1 + random.uniform(
                -FAST_STAGE_GAP_JITTER, FAST_STAGE_GAP_JITTER
            )
            await self._sleep(max(0.03, tap.gap * gap_scale * self._speed * jitter))
            await self._tap_jittered(session_id, tap.x, tap.y, jitter=tap_jitter)
            if option is not None:
                await self._sleep(random.uniform(*option_gap))
                await self._tap_jittered(session_id, option.x, option.y, jitter=tap_jitter)
            if index % check_every:
                continue
            screen = await self._read(session_id)
            if screen.has("失败") or screen.has("胜利") or screen.has("最高旅程"):
                self._last_run_failed = screen.has("失败")
                back = screen.find("返回主城", "再次挑战", "返回", "确定")
                if back is not None:
                    self._log("info", f"快速模式：关卡结算「{back.text}」")
                    await self._tap(session_id, back)
                    return await self._back_to_adventure(session_id)
            settle = screen.find(*SETTLE_WORDS)
            if settle is not None:
                self._log("info", f"快速模式：本轮结束「{settle.text}」")
                await self._tap(session_id, settle)
                return await self._back_to_adventure(session_id)
            if screen.adventure_entry() is not None and not self._in_run(screen):
                self._log("info", "快速模式：已确认回到冒险页，本轮结束")
                return True
            if not self._in_run(screen):
                self._log("warn", "快速模式：界面偏离局内，切回逐帧识别")
                return None
        return None

    async def _play_run_ocr(self, session_id: str) -> bool:
        """逐帧 OCR 的单局战斗循环。"""
        self._last_run_failed = False
        deadline = self._clock() + self._max_run_seconds
        idle_rounds = 0
        stuck = 0
        wheel_spin_rounds = 0
        dig_index = 0
        merchant_rounds = 0
        start_retries = 0
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
            if self._wheel_stuck(screen):
                # 加速器下转盘动画可能永久停住：没有结果按钮也没有返回箭头。
                # 不进入常规 idle 兜底（那只会反复点屏幕下方中部），
                # 而是短等几轮后标记硬卡死，交给上层立即杀进程重启。
                wheel_spin_rounds += 1
                if wheel_spin_rounds == 1:
                    self._log("warn", "事件转盘等待结果，未识别到可点击动作")
                if wheel_spin_rounds >= WHEEL_SPIN_MAX_ROUNDS:
                    self._log("warn", "事件转盘长时间无结果，判定硬卡死，准备重启")
                    self._last_run_failed = True
                    self._hard_stuck = True
                    return False
                await self._wait(1.0, "ocr_poll")
                continue
            # 已确认的事件转盘使用「开始」旋转，不能交给冒险页重试或底层「下一天」
            if (
                screen.find_exact("传说技能") is not None
                or screen.has("方尖碑")
                or (screen.has("你发现了一座方") and screen.find_exact("开始") is not None)
                or (
                    screen.find_exact("开始") is not None
                    and any(DAY_PATTERN.search(item.text) for item in screen.items)
                )
            ):
                wheel_start = screen.find_exact("开始")
                if wheel_start is not None:
                    self._log("info", "转动事件转盘")
                    await self._tap(session_id, wheel_start)
                    idle_rounds = 0
                    continue
            # 仍停留在冒险页说明「开始」没点进去（可能被弹窗拦了），重试几次
            start = screen.find_exact("开始")
            if start is not None and not self._in_run(screen):
                start_retries += 1
                if start_retries > 3:
                    self._log("warn", "多次点击「开始」仍未进入关卡，放弃本轮")
                    self._last_run_failed = True
                    return False
                self._log("warn", f"仍在冒险页，重新点击「开始」（第 {start_retries} 次）")
                await self._tap(session_id, start)
                idle_rounds = 0
                continue
            if self._is_skill_modal(screen):
                await self._pick_skills(session_id, screen)
                idle_rounds = 0
                stuck = 0  # 技能弹窗内多次选卡会累积签名，出来后必须清零避免误伤下一天
                continue
            # 结算页：胜利/失败/生存天数，点返回结束本轮
            if screen.has("胜利") or screen.has("失败") or screen.has("最高旅程"):
                if screen.has("失败"):
                    self._last_run_failed = True
                back = screen.find("返回主城", "再次挑战", "返回", "确定")
                if back is not None:
                    self._log("info", f"关卡结算：「{back.text}」")
                    await self._tap(session_id, back)
                    return await self._back_to_adventure(session_id)
            # 挖宝小游戏：逐格翻牌，翻完自动结束。
            # 加轮次上限：翻完 DIG_MAX_ROUNDS 轮仍停在挖宝页就放弃本局，
            # 由上层「卡住自愈」杀进程重启，避免无限翻牌卡死。
            if screen.has(DIG_HINT):
                if dig_index >= len(DIG_CELLS) * DIG_MAX_ROUNDS:
                    self._log("warn", f"挖宝翻牌 {dig_index} 次仍未退出，判定卡住")
                    self._last_run_failed = True
                    return False
                cell = DIG_CELLS[dig_index % len(DIG_CELLS)]
                dig_index += 1
                self._log("info", f"挖宝翻牌：第 {dig_index} 张")
                await self._tap_point(session_id, cell[0], cell[1])
                idle_rounds = 0
                continue
            # 幸运商人：先选 100% 机器再点「试一试」，否则按钮是禁用态
            if screen.find_exact("幸运商人") is not None:
                merchant_rounds += 1
                if merchant_rounds > 6:
                    self._log("info", "幸运商人次数已用完，点返回箭头退出")
                    await self._tap_point(session_id, 0.055, 0.905, wait=0.5)
                    continue
                self._log("info", "幸运商人：选择 100% 机器并试一试")
                await self._tap_point(session_id, 0.155, 0.545, wait=0.4)
                await self._tap_point(session_id, 0.500, 0.905, wait=0.5)
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
                        await self._tap_point(session_id, 0.098, 0.872, wait=0.5)
                idle_rounds = 0
                continue
            if screen.find_exact("神话技能") is not None:
                result_continue = screen.find_exact("继续")
                if result_continue is not None:
                    self._log("info", "确认神话技能结果")
                    await self._tap(session_id, result_continue)
                    idle_rounds = 0
                    continue
                spin = screen.find_exact("转动")
                if spin is not None:
                    self._log("info", "转动神话技能转盘")
                    await self._tap(session_id, spin)
                    idle_rounds = 0
                    continue
            if self._is_slot_result(screen):
                close_result = screen.find_exact("X", "×")
                self._log("info", "关闭转盘结果")
                if close_result is not None:
                    await self._tap(session_id, close_result)
                else:
                    await self._tap_point(session_id, 0.5, 0.90, wait=0.4)
                idle_rounds = 0
                continue
            settle = screen.find(*SETTLE_WORDS)
            if settle is not None:
                self._log("info", f"本轮结束：「{settle.text}」")
                await self._tap(session_id, settle)
                return await self._back_to_adventure(session_id)
            # 「请选择一项…」类弹窗：底部按钮往往被禁用，需要在列表里挑一项
            if screen.has("请选择"):
                option = self._prompt_option(screen)
                if option is not None:
                    self._log("info", f"选择馈赠：「{option.text}」")
                    await self._tap(session_id, option)
                    idle_rounds = 0
                    continue
            # 「是否…？」契约类弹窗：两个选项在屏幕下方，优先选正向
            if screen.has("是否"):
                option = self._prompt_option(screen, min_cy=0.72)
                if option is not None:
                    self._log("info", f"契约选择：「{option.text}」")
                    await self._tap(session_id, option, kind="option")
                    idle_rounds = 0
                    continue
            if screen.find_exact("战斗中") is not None:
                idle_rounds = 0
                await self._wait(0.8, "ocr_poll")
                continue
            close_detail = screen.find_exact("X", "×")
            if close_detail is not None:
                self._log("info", "关闭技能详情")
                await self._tap(session_id, close_detail)
                idle_rounds = 0
                continue
            action = screen.find_exact(*STAGE_ACTIONS)
            # stuck 只用于阻止对「同一个按钮」反复点击，不能误伤新出现的动作。
            # 真机：选完技能后签名短暂无变化使 stuck 累加到 3，若仍用 stuck<3
            # 会连新出现的「下一天」都不点，卡死直到超时（2026-11-16 实测）。
            if action is not None:
                text = action.text.strip()
                if text != last_action or stuck < 3:
                    if text != last_action:
                        self._log("info", f"点击「{text}」")
                        last_action = text
                    await self._tap(session_id, action)
                    idle_rounds = 0
                    continue
                # 同一按钮已连点多次且界面不动：跳过，交给后续 idle 兜底
            # 没有标准动作按钮时，可能是二选一的奇遇选项（如「休息 / 搜索」）
            option = self._choice_option(screen)
            if option is not None:
                self._log("info", f"奇遇选项：「{option.text}」")
                await self._tap(session_id, option, kind="option")
                idle_rounds = 0
                continue
            if self._in_run(screen) and action is None:
                idle_rounds = 0
                await self._wait(0.8, "ocr_poll")
                continue
            idle_rounds += 1
            if idle_rounds == 4:
                self._log("warn", "连续多轮未识别到可点击动作，尝试点击屏幕下方中部")
                await self._tap_point(session_id, 0.5, 0.92, wait=0.4)
            if idle_rounds >= 6:
                self._log("warn", "界面长时间无响应，放弃当前关卡")
                self._last_run_failed = True
                return False
            await self._wait(0.8, "ocr_poll")
        self._log("warn", "本轮推关超时，未检测到结算界面")
        # 超时只代表本次预算用完，交给上层续跑，不计为游戏失败
        return False

    def _finalize_button(self, screen: Screen) -> OcrItem | None:
        for word in FINALIZE_WORDS:
            for item in screen.items:
                if item.text.strip() == word:
                    return item
        return None

    def _prompt_option(
        self, screen: Screen, *, min_cy: float = 0.33
    ) -> OcrItem | None:
        """「请选择/是否…」弹窗里的候选项，优先正向选项，其次取最上面一个"""
        options: list[OcrItem] = []
        for item in screen.items:
            left, top, right, bottom = item.bounds
            cy = (top + bottom) / 2
            cx = (left + right) / 2
            text = item.text.strip()
            if not (min_cy <= cy <= 0.78 and cx <= 0.80):
                continue
            if len(text) < 2 or len(text) > 6 or "。" in text or "请选择" in text:
                continue
            if LEVEL_PATTERN.match(text) or text in SKILL_NON_CARDS:
                continue
            if DAY_PATTERN.search(text):
                continue
            options.append(item)
        for preferred in ("签订", "接受", "同意", "继续", "领取"):
            for item in options:
                if preferred in item.text:
                    return item
        options.sort(key=lambda entry: entry.bounds[1])
        return options[0] if options else None

    def _is_slot_result(self, screen: Screen) -> bool:
        if screen.find_exact("转动") is not None:
            return False
        if screen.find("剩余旋转次数") is not None:
            return True
        return (
            screen.find_exact("神话技能") is not None
            and screen.find_exact("大吉", "小吉") is not None
        )

    def _in_run(self, screen: Screen) -> bool:
        """是否处于关卡内：技能弹窗、天数指示、推进按钮或结算按钮任一命中"""
        if self._is_skill_modal(screen):
            return True
        # 新手教程页的天数常被识别成单个「天」，靠底部「选择技能」兜底
        if screen.find_exact("选择技能") is not None:
            return True
        if any(DAY_PATTERN.search(item.text) for item in screen.items):
            return True
        if (
            screen.has(DIG_HINT)
            or screen.find_exact(*RUN_EVENT_TITLES) is not None
            or screen.has("你发现了一座方")
        ):
            return True
        if self._is_slot_result(screen):
            return True
        if screen.has("运气不佳"):
            return True
        if screen.has("点击关闭"):
            return True
        return screen.find(*STAGE_ACTIONS) is not None or screen.find(*SETTLE_WORDS) is not None

    def _choice_option(self, screen: Screen) -> OcrItem | None:
        """底部一排二/三选一的奇遇按钮：取最右（右边）的那个"""
        options: list[OcrItem] = []
        for item in screen.items:
            left, top, right, bottom = item.bounds
            cy = (top + bottom) / 2
            text = item.text.strip()
            if cy < 0.84 or len(text) < 2 or len(text) > 8:
                continue
            if re.fullmatch(r"[\d/]+", text):
                continue
            if text in STAGE_ACTIONS + SETTLE_WORDS + ("开始", "冒险"):
                continue
            # 底部导航栏标签，不是奇遇选项
            if text in {"竞技", "挑战", "副本", "冒险", "主城"}:
                continue
            if text in SKILL_NON_CARDS or text in {"大吉", "小吉"} or text.endswith("中"):
                continue
            options.append(item)
        # 安全选项优先，同级再取最右：避免反复点「战斗（危险）」
        options.sort(
            key=lambda entry: (entry.bounds[0] + entry.bounds[2]) / 2
        )
        if not options:
            return None
        safe = [
            entry
            for entry in options
            if not any(word in entry.text for word in DANGER_OPTION_WORDS)
        ]
        return (safe or options)[-1]

    # ---------- 技能三选一 ----------

    def _is_skill_modal(self, screen: Screen) -> bool:
        if screen.has(SKILL_HINT):
            return True
        return any(item.text.strip() == SKILL_TITLE for item in screen.items)

    def _skill_cards(self, screen: Screen) -> list[OcrItem]:
        # 卡片一定在「从下方选择一个技能」提示下方，避免把弹窗标题当成卡片
        hint = screen.find_exact(SKILL_HINT)
        min_cy = 0.30
        if hint is not None:
            min_cy = (hint.bounds[1] + hint.bounds[3]) / 2 + 0.015
        cards: list[OcrItem] = []
        for item in screen.items:
            left, top, right, bottom = item.bounds
            cy = (top + bottom) / 2
            cx = (left + right) / 2
            text = item.text.strip()
            if not (min_cy <= cy <= 0.78 and cx <= 0.62):
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
        """技能弹窗的底部确认按钮。

        真机实测确认词是「领悟」或「下一天」（cy≈0.91），旧实现只找含
        「选择技能」且 cy>=0.72 的项——那是顶部标题，永远命中不到，导致
        选完卡却点不了确认、卡在弹窗里（表现为推关长时间不动）。
        """
        for item in screen.items:
            text = item.text.strip()
            cy = (item.bounds[1] + item.bounds[3]) / 2
            if cy < 0.72:
                continue
            if text in SKILL_CONFIRM_WORDS or SKILL_TITLE in text:
                return item
        return None

    def _choose_card(self, cards: list[OcrItem], priority: list[str]) -> OcrItem:
        # 快速模式下直接选第一张，跳过优先级遍历以压缩选卡耗时
        if self._speed < 1.0 or not priority:
            return cards[0]
        for keyword in priority:
            for card in cards:
                if keyword and keyword in card.text:
                    return card
        return cards[0]

    async def _pick_skills(self, session_id: str, screen: Screen) -> None:
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
                choice = self._choose_card(cards, self._skill_priority)
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

    async def _ensure_adventure(self, session_id: str) -> bool:
        screen = await self._read(session_id)
        if screen.has("未完成的冒险"):
            # 杀进程重启后游戏会问「是否继续挑战」：选取消，丢弃半局残留状态，
            # 否则主城入口被弹窗挡住，后续所有阶段都会被跳过。
            cancel = screen.find_exact("取消")
            if cancel is not None:
                self._log("info", "清理重启残留：取消未完成冒险")
                await self._tap(session_id, cancel)
                screen = await self._read(session_id)
        if screen.adventure_entry() is not None:
            return True
        nav = screen.find("冒险")
        if nav is not None:
            await self._tap(session_id, nav)
            screen = await self._read(session_id)
            if screen.adventure_entry() is not None:
                return True
        if await self._back_to_adventure(session_id):
            return True
        self._log("warn", "未能确认冒险页")
        return False

    async def _back_to_adventure(self, session_id: str) -> bool:
        tried_arrow = False
        tried_close = False
        for _ in range(6):
            screen = await self._read(session_id)
            if self._wheel_stuck(screen):
                # 事件转盘动画卡死时没有任何返回入口（返回键也无效），
                # 唯一恢复手段是杀进程重启；重启成功则重新判定冒险页。
                if not await self._restart_game(session_id, "返回冒险页时事件转盘卡住"):
                    return False
                continue
            blocking_popup = screen.find("公告") is not None or (
                screen.find("礼包", "特惠", "锦鲤", "冠军公会", "秘藏箱") is not None
                and screen.find("购买", "立即前往", "免费福利") is not None
            )
            if screen.adventure_entry() is not None and not blocking_popup:
                return True
            shop_nav = screen.find_exact("商城")
            if shop_nav is not None and (shop_nav.bounds[1] + shop_nav.bounds[3]) / 2 > 0.9:
                await self._adapter_getter().tap(session_id, 0.5, 0.954, 80, 6)
                await self._wait(0.5)
                continue
            challenge_nav = screen.find_exact("挑战")
            if (
                challenge_nav is not None
                and (challenge_nav.bounds[1] + challenge_nav.bounds[3]) / 2 > 0.9
            ):
                await self._adapter_getter().tap(session_id, 0.098, 0.955, 80, 6)
                await self._wait(0.5)
                continue
            # 家园 / 公会信息等全屏子页面：先点右上角 X，避免误触左下「编辑」
            if not tried_close and screen.find_exact(*SUBPAGE_CLOSE_WORDS) is not None:
                tried_close = True
                await self._adapter_getter().tap(session_id, 0.932, 0.132, 80, 6)
                await self._wait(0.6)
                continue
            # 挖宝小游戏没有返回键，必须先把卡牌翻完才能退出
            if screen.find_exact("挖宝") is not None or screen.has(DIG_HINT):
                self._log("info", "返回途中遇到挖宝小游戏，先翻完卡牌")
                for index, (cell_x, cell_y) in enumerate(DIG_CELLS, 1):
                    if self._stopping:
                        return False
                    await self._tap_point(session_id, cell_x, cell_y)
                    if index % 3 == 0:
                        await self._wait(0.4)
                await self._wait(0.6)
                continue
            # 付费商城（每日特惠等）含真实价格：盲点关闭位可能落到购买按钮，只走返回箭头
            if (
                SHOP_PRICE_PATTERN.search("|".join(screen.texts()))
                and screen.find("每日特惠", "礼包") is not None
            ):
                if tried_arrow:
                    raise AutomationUnavailable("付费商城页返回失败，停止自动操作")
                tried_arrow = True
                await self._adapter_getter().tap(session_id, 0.098, 0.955, 80, 6)
                await self._wait(0.5)
                continue
            # 全屏公告/活动弹窗：只点已验证关闭位，每点一次都重新确认上下文
            if screen.find("公告", "特惠", "礼包", "锦鲤", "冠军公会", "秘藏箱") is not None:
                for close_y in (0.83, 0.886, 0.768, 0.815, 0.868, 0.939):
                    await self._adapter_getter().tap(session_id, 0.5, close_y, 80, 6)
                    await self._wait(0.4, "debounce")
                    screen = await self._read(session_id)
                    if (
                        screen.adventure_entry() is not None
                        and screen.find("公告", "礼包", "锦鲤", "冠军公会", "秘藏箱") is None
                    ):
                        return True
                    if screen.find("公告", "特惠", "礼包", "锦鲤", "冠军公会", "秘藏箱") is None:
                        break
                continue
            # 特权卡含购买文案，不能让「购买后立即获得」命中通用结算动作
            is_privilege_card = screen.find_exact("每日福利") is not None or (
                screen.find_exact("领取全部") is not None
                and screen.find_exact("免广告卡", "月卡", "终身卡") is not None
            )
            if is_privilege_card and screen.find("购买") is not None:
                if tried_arrow:
                    raise AutomationUnavailable("特权卡页返回失败，停止自动操作")
                tried_arrow = True
                await self._adapter_getter().tap(session_id, 0.098, 0.955, 80, 6)
                await self._wait(0.5)
                continue
            if screen.find("充值", "购买", "广告") is not None:
                raise AutomationUnavailable("遇到未知付费或广告页面，停止自动返回")
            finalize = screen.find(*FINALIZE_WORDS)
            if finalize is not None:
                await self._tap(session_id, finalize)
                continue
            back = screen.find(*BACK_WORDS)
            if back is not None:
                await self._tap(session_id, back)
                continue
            if screen.find("宝石", "钻石") is not None:
                raise AutomationUnavailable("遇到未知付费或广告页面，停止自动返回")
            # 子页面通常在左下角有返回箭头
            if not tried_arrow:
                tried_arrow = True
                for arrow_x, arrow_y in BACK_ARROWS:
                    await self._adapter_getter().tap(session_id, arrow_x, arrow_y, 80, 6)
                    await self._wait(0.5)
                continue
            # 部分全屏子页面只有右上角关闭按钮
            if not tried_close:
                tried_close = True
                await self._adapter_getter().tap(session_id, 0.932, 0.132, 80, 6)
                await self._wait(0.6)
                continue
            break
        self._log("warn", "返回冒险页失败，请检查当前界面")
        return False

    # ---------- 基础能力 ----------

    async def _read(
        self,
        session_id: str,
        region: tuple[float, float, float, float] | None = None,
    ) -> Screen:
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                png = await self._adapter_getter().screenshot(session_id)
                if region is None:
                    items = await asyncio.to_thread(self._ocr, png)
                else:
                    items = await asyncio.to_thread(self._ocr, png, region)
                return Screen(list(items))
            except Exception as exc:  # 截图偶发截断，重新截一张再试
                last_exc = exc
                if attempt == 0:
                    await self._wait(0.5, "ocr_poll")
        raise AutomationUnavailable(f"截图识别失败：{last_exc}")

    async def _tap(self, session_id: str, item: OcrItem, *, dy: float = 0.0,
                   kind: str = "next") -> None:
        left, top, right, bottom = item.bounds
        await self._tap_point(
            session_id,
            (left + right) / 2,
            (top + bottom) / 2 + dy,
            wait=0.5,
            kind=kind,
        )

    async def _tap_point(
        self,
        session_id: str,
        x: float,
        y: float,
        *,
        wait: float = 0.4,
        kind: str = "next",
    ) -> None:
        """按归一化坐标点击；录制中会把坐标和间隔记进快速模式脚本"""
        self._record_tap(x, y, kind=kind)
        await self._adapter_getter().tap(session_id, x, y, 80, 6)
        await self._wait(wait)

    async def _tap_jittered(
        self, session_id: str, x: float, y: float, *, jitter: float | None = None
    ) -> None:
        """回放点击加低偏移，避免每次都落在完全相同的像素。

        jitter 可传入（精简模式用更大偏移提高容错），缺省用全量模式的幅度。
        """
        span = FAST_STAGE_JITTER if jitter is None else jitter
        jx = min(max(x + random.uniform(-span, span), 0.01), 0.99)
        jy = min(max(y + random.uniform(-span, span), 0.01), 0.99)
        await self._adapter_getter().tap(session_id, jx, jy, 80, 6)

    def _record_tap(self, x: float, y: float, *, kind: str = "next") -> None:
        if not self._recording:
            return
        # 用单调时钟测点击间隔：不占用注入的 clock（单局预算按它计时）
        now = time.monotonic()
        gap = 1.0 if self._last_tap_ts is None else now - self._last_tap_ts
        self._last_tap_ts = now
        self._recorded.append(
            StageTap(
                x,
                y,
                min(max(gap, FAST_STAGE_MIN_GAP), FAST_STAGE_MAX_GAP),
                kind,
            )
        )

    def _remember_recorded(self) -> None:
        """只保留最长的一次录制，避免超时截断的短序列覆盖完整脚本"""
        if len(self._recorded) < FAST_STAGE_MIN_TAPS:
            return
        if len(self._recorded) <= len(self._stage_script):
            return
        recorded = list(self._recorded)
        # 本次没遇到双选项时，保留上一次录到的右侧锚点，避免丢失
        old_option = next(
            (tap for tap in reversed(self._stage_script) if tap.kind == "option"),
            None,
        )
        if old_option is not None and not any(
            tap.kind == "option" for tap in recorded
        ):
            recorded.append(old_option)
        self._stage_script = recorded
        self._save_stage_script()

    def _load_stage_script(self) -> list[StageTap]:
        try:
            raw = json.loads(self._stage_script_path.read_text("utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(raw, dict):
            return []
        taps: list[StageTap] = []
        for entry in raw.get("taps") or []:
            try:
                kind = str(entry.get("kind", "next"))
                taps.append(
                    StageTap(
                        float(entry["x"]),
                        float(entry["y"]),
                        float(entry.get("gap", 1.0)),
                        kind if kind in ("next", "option") else "next",
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return taps

    def _save_stage_script(self) -> None:
        payload = {
            "savedAt": time.time(),
            "taps": [
                {
                    "x": round(tap.x, 4),
                    "y": round(tap.y, 4),
                    "gap": round(tap.gap, 3),
                    "kind": tap.kind,
                }
                for tap in self._stage_script
            ],
        }
        try:
            self._stage_script_path.parent.mkdir(parents=True, exist_ok=True)
            self._stage_script_path.write_text(
                json.dumps(payload, ensure_ascii=False), "utf-8"
            )
        except OSError as exc:
            self._log("warn", f"快速模式脚本保存失败：{exc}")

    async def _wait(self, seconds: float, category: str = "animation") -> None:
        """动画等待随速度缩放；OCR 轮询与点击防抖保持固定间隔。"""
        delay = max(0.2, seconds * self._speed) if category == "animation" else seconds
        await self._sleep(delay)

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
