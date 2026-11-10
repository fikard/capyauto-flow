export interface ScriptFile {
  name: string;
  path: string;
  category: 'core' | 'tasks' | 'config' | 'docs';
  description: string;
  content: string;
}

export const SCRIPT_FILES: ScriptFile[] = [
  {
    name: 'main.js',
    path: 'main.js',
    category: 'core',
    description: '主入口调度脚本：环境自检、守护线程启动、账号状态轮询与全局异常恢复',
    content: `/**
 * CapyScript - 放置类游戏全自动流水线
 * 运行环境: AutoX.js v6.x+ (配备 PaddleOCR-NCNN 离线推理)
 * 权限要求: 无障碍服务, 悬浮窗, 媒体投影截屏, 忽略电池优化
 */

const Automator = require('./core/automator.js');
const Vision = require('./core/vision.js');
const FSM = require('./core/fsm.js');
const Logger = require('./core/logger.js');
const AccountManager = require('./tasks/account_manager.js');
const DailyHarvest = require('./tasks/daily_harvest.js');
const StagePusher = require('./tasks/stage_pusher.js');
const GuildEngine = require('./tasks/guild_engine.js');

// 1. 初始化运行环境与前置检查
function initEnvironment() {
    Logger.initFloating();
    Logger.info("正在执行系统权限与依赖自检...");

    if (!auto.service) {
        toast("请先开启无障碍服务！");
        app.startActivity({ action: "android.settings.ACCESSIBILITY_SETTINGS" });
        exit();
    }

    if (!requestScreenCapture(true)) {
        toast("未授权截屏权限，脚本无法识别图像！");
        exit();
    }

    device.keepScreenOn(3600 * 1000); // 开启常亮防息屏
    Logger.info("系统权限准备完毕，截屏与无障碍就绪");
}

// 2. 启动全局弹窗阻断守护子线程
function startWatchdogThread() {
    threads.start(function() {
        Logger.info("守护子线程已就绪 (拦截意外弹窗与首充促销)");
        while (true) {
            try {
                // 扫描常见阻断弹窗与叉号
                let closeBtn = textMatches(/(关闭|跳过|残忍拒绝|暂不升级|取消|我知道了)/).findOnce();
                if (closeBtn) {
                    Logger.warn("守护线程检测到阻断弹窗: " + closeBtn.text() + "，立即自动消除");
                    closeBtn.click();
                    sleep(1200);
                }
            } catch (e) {
                // 忽略守护异常，保证主线程不受干扰
            }
            sleep(2000); // 每2秒轮询一次
        }
    });
}

// 3. 主调度主循环
function main() {
    initEnvironment();
    startWatchdogThread();

    Logger.info("开始加载账号矩阵配置...");
    let accounts = AccountManager.loadAccounts();

    for (let i = 0; i < accounts.length; i++) {
        let acc = accounts[i];
        if (acc.doneToday) {
            Logger.info("账号 [" + acc.id + "] 今日已完成，跳过");
            continue;
        }

        Logger.info("====== 切换至账号: " + acc.id + " (" + acc.type + ") ======");
        
        // 唤起对应分身或登录凭证
        let launched = AccountManager.switchToAccount(acc);
        if (!launched) {
            Logger.error("账号唤起失败，尝试跳至下一个账号");
            continue;
        }

        sleep(5000); // 等待游戏加载

        // 执行业务任务流
        try {
            // 步骤 A: 主城体力游历与日常收菜
            DailyHarvest.runHarvest();

            // 步骤 B: 公会贡献与船票提交
            GuildEngine.runGuildTasks();

            // 步骤 C: 主线推关与技能决策
            StagePusher.runStagePush(3); // 尝试推关 3 关

            // 标记账号完成
            AccountManager.markAccountDone(acc.id);
            Logger.info("账号 [" + acc.id + "] 任务流水线全部执行完毕！");

            // 步骤 D: 切换蜂窝网络重置 IP (防多账号IP风控)
            AccountManager.resetDynamicIp();

        } catch (err) {
            Logger.error("账号任务发生未捕获异常: " + err);
        } finally {
            AccountManager.killCurrentApp(acc);
            sleep(3000);
        }
    }

    device.cancelKeepingAwake();
    Logger.info("所有账号流水线已全部处理完毕，已释放唤醒锁，自动休眠！");
}

main();
`
  },
  {
    name: 'config.json',
    path: 'config.json',
    category: 'config',
    description: '账号矩阵、技能优先级与防封触控抖动配置文件',
    content: `{
  "global": {
    "targetPackage": "com.game.capy",
    "enableWatchdog": true,
    "enableScreenDarkening": true,
    "enableDynamicIpReset": true,
    "maxDefeatRetries": 2
  },
  "touchSettings": {
    "gaussianStdev": 6,
    "pressDurationMean": 80,
    "pressDurationStdev": 20,
    "reactionMinDelay": 400,
    "reactionMaxDelay": 850
  },
  "skillPriorityList": [
    "越战越硬",
    "伤害减免",
    "普攻减免",
    "格挡率",
    "冰刺",
    "冰冻精通",
    "连击强化",
    "暴击概率",
    "越战越勇",
    "生命强化"
  ],
  "accounts": [
    {
      "id": "main_01",
      "type": "clone_user_0",
      "userId": 0,
      "enabled": true,
      "doneToday": false
    },
    {
      "id": "alt_island_02",
      "type": "clone_user_999",
      "userId": 999,
      "enabled": true,
      "doneToday": false
    },
    {
      "id": "alt_phone_03",
      "type": "phone_auth",
      "user": "13800138000",
      "pass": "Capy2026!",
      "enabled": true,
      "doneToday": false
    },
    {
      "id": "alt_guest_04",
      "type": "guest",
      "uuid": "guest_c8f391a0",
      "enabled": true,
      "doneToday": false
    }
  ]
}`
  },
  {
    name: 'core/automator.js',
    path: 'core/automator.js',
    category: 'core',
    description: '拟人化手势层：高斯随机抖动坐标与三次贝塞尔拟人手势滑动',
    content: `// core/automator.js
const Automator = {
    // 随机高斯分布函数，模拟人类手指物理击打偏移
    randomGaussian: function(mean, stdev) {
        let u1 = Math.random(), u2 = Math.random();
        while (u1 <= Number.EPSILON) u1 = Math.random();
        let randStdNormal = Math.sqrt(-2.0 * Math.log(u1)) * Math.sin(2.0 * Math.PI * u2);
        return mean + randStdNormal * stdev;
    },

    // 拟人化微抖动点击（解决绝对坐标机械检测）
    humanClick: function(x, y, stdev = 6) {
        let realX = Math.round(this.randomGaussian(x, stdev));
        let realY = Math.round(this.randomGaussian(y, stdev));
        let pressTime = Math.round(this.randomGaussian(80, 20)); // 按压时长 60~100ms
        
        press(realX, realY, Math.max(40, pressTime));
        let delay = random(400, 850); // 拟人反应生理停顿
        sleep(delay);
        return { realX, realY, pressTime, delay };
    },

    // 贝塞尔曲线模拟人类手指滑动弧度
    humanSwipe: function(x1, y1, x2, y2, duration = 350) {
        let cx = (x1 + x2) / 2 + random(-50, 50);
        let cy = (y1 + y2) / 2 + random(-50, 50);
        gesture(duration, [x1, y1], [cx, cy], [x2, y2]);
        sleep(random(500, 1000));
    },

    // 随机微小滚动浏览
    humanScroll: function(direction = "down") {
        let startY = direction === "down" ? device.height * 0.7 : device.height * 0.3;
        let endY = direction === "down" ? device.height * 0.4 : device.height * 0.6;
        let startX = device.width / 2 + random(-40, 40);
        this.humanSwipe(startX, startY, startX + random(-20, 20), endY, random(300, 500));
    }
};

module.exports = Automator;
`
  },
  {
    name: 'core/vision.js',
    path: 'core/vision.js',
    category: 'core',
    description: '视觉决策与离线 OCR：PaddleOCR-NCNN 离线推理与技能三选一加权匹配',
    content: `// core/vision.js
const Automator = require('./automator.js');
let config = {};
try {
    config = JSON.parse(files.read('./config.json'));
} catch (e) {
    config = {
        skillPriorityList: ["越战越硬", "伤害减免", "普攻减免", "格挡率", "冰刺", "冰冻精通", "连击强化", "暴击概率"]
    };
}

const Vision = {
    skillPriorityList: config.skillPriorityList,

    // 模板图片匹配 (OpenCV 实现)
    findImage: function(templateName, threshold = 0.8) {
        let screen = captureScreen();
        let templatePath = "./assets/images/" + templateName;
        if (!files.exists(templatePath)) {
            screen.recycle();
            return null;
        }
        let template = images.read(templatePath);
        let p = images.findImage(screen, template, { threshold: threshold });
        screen.recycle();
        template.recycle();
        return p;
    },

    // 局内技能选择决策 (基于离线 OCR)
    chooseBestSkill: function(ocrPlugin) {
        let img = captureScreen();
        // 调用本地离线 OCR (PaddleOCR-NCNN / MLKit 插件)
        // 插件返回: [{ text: "越战越硬", bounds: { left: 80, top: 920, right: 320, bottom: 980 } }]
        let results = [];
        if (ocrPlugin && typeof ocrPlugin.detect === 'function') {
            results = ocrPlugin.detect(img);
        } else {
            // AutoX.js 内置 OCR 兜底
            let ocr = $ocr || gmlkit;
            results = ocr.detect(img);
        }
        img.recycle();

        let bestCandidate = null;
        let highestRank = 9999;

        for (let item of results) {
            for (let rank = 0; rank < this.skillPriorityList.length; rank++) {
                let targetSkill = this.skillPriorityList[rank];
                if (item.text.indexOf(targetSkill) !== -1) {
                    if (rank < highestRank) {
                        highestRank = rank;
                        bestCandidate = item;
                    }
                }
            }
        }

        if (bestCandidate) {
            // 点击命中的最高优先级技能中心
            let cx = (bestCandidate.bounds.left + bestCandidate.bounds.right) / 2;
            let cy = (bestCandidate.bounds.top + bestCandidate.bounds.bottom) / 2;
            Automator.humanClick(cx, cy);
            return { success: true, skill: bestCandidate.text, rank: highestRank };
        }

        // 若三张卡牌均不在优先级库，点击正中第2张卡牌保底
        let fallbackX = device.width / 2;
        let fallbackY = device.height * 0.65;
        Automator.humanClick(fallbackX, fallbackY);
        return { success: true, skill: "保底中央卡牌", rank: 9999 };
    }
};

module.exports = Vision;
`
  },
  {
    name: 'core/fsm.js',
    path: 'core/fsm.js',
    category: 'core',
    description: '有限状态机引擎：管理游戏生命周期与超时熔断看门狗',
    content: `// core/fsm.js
const Logger = require('./logger.js');

class GameFSM {
    constructor() {
        this.state = "IDLE";
        this.stateStartTime = Date.now();
        this.timeoutLimit = 45000; // 单状态最大允许 45s 超时熔断
    }

    setState(newState) {
        Logger.fsm("状态迁移: [" + this.state + "] -> [" + newState + "]");
        this.state = newState;
        this.stateStartTime = Date.now();
    }

    checkTimeout() {
        let elapsed = Date.now() - this.stateStartTime;
        if (elapsed > this.timeoutLimit) {
            Logger.warn("状态 [" + this.state + "] 已持续 " + Math.round(elapsed / 1000) + "s，触发超时熔断！");
            this.handleTimeout();
            return true;
        }
        return false;
    }

    handleTimeout() {
        // 尝试点击通用返回键或者屏幕边缘退出异常弹窗
        back();
        sleep(1000);
        this.setState("MAIN_CITY");
    }
}

module.exports = GameFSM;
`
  },
  {
    name: 'core/logger.js',
    path: 'core/logger.js',
    category: 'core',
    description: '本地持久化日志与 AutoX.js 悬浮窗可视化监控界面',
    content: `// core/logger.js
const Logger = {
    window: null,

    initFloating: function() {
        if (!floaty) return;
        this.window = floaty.window(
            '<card cardBackgroundColor="#cc111827" cardCornerRadius="8dp">' +
            '  <vertical padding="8dp">' +
            '    <text id="title" text="CapyScript 监控中" textColor="#f59e0b" textSize="12sp" textStyle="bold"/>' +
            '    <text id="msg" text="正在初始化..." textColor="#e5e7eb" textSize="10sp" maxLines="4"/>' +
            '  </vertical>' +
            '</card>'
        );
        this.window.setPosition(20, 120);
    },

    updateFloating: function(text) {
        if (this.window && this.window.msg) {
            ui.run(() => {
                this.window.msg.setText(text);
            });
        }
    },

    log: function(level, tag, msg) {
        let time = new java.text.SimpleDateFormat("HH:mm:ss").format(new java.util.Date());
        let line = "[" + time + "] [" + level + "] [" + tag + "] " + msg;
        console.log(line);
        this.updateFloating(msg);
        files.append("/sdcard/CapyScript/run.log", line + "\\n");
    },

    info: function(msg) { this.log("INFO", "SYS", msg); },
    warn: function(msg) { this.log("WARN", "SYS", msg); },
    error: function(msg) { this.log("ERROR", "SYS", msg); },
    fsm: function(msg) { this.log("FSM", "STATE", msg); },
    ocr: function(msg) { this.log("OCR", "VISION", msg); }
};

module.exports = Logger;
`
  },
  {
    name: 'tasks/account_manager.js',
    path: 'tasks/account_manager.js',
    category: 'tasks',
    description: '账号矩阵生命周期管理：Android 多用户分身切换、凭证轮换与飞行模式重置 IP',
    content: `// tasks/account_manager.js
const Automator = require('../core/automator.js');
const Logger = require('../core/logger.js');

const AccountManager = {
    configFile: "./config.json",

    loadAccounts: function() {
        let content = files.read(this.configFile);
        let json = JSON.parse(content);
        return json.accounts || [];
    },

    markAccountDone: function(accId) {
        let content = files.read(this.configFile);
        let json = JSON.parse(content);
        for (let acc of json.accounts) {
            if (acc.id === accId) {
                acc.doneToday = true;
                acc.lastDoneTime = new Date().toISOString();
            }
        }
        files.write(this.configFile, JSON.stringify(json, null, 2));
    },

    // 唤起对应分身 (支持 User 0 与 User 999 炼妖壶/Island 双开沙盒)
    switchToAccount: function(acc) {
        let pkg = "com.game.capy";
        if (acc.type === "clone_user_0") {
            Logger.info("启动主空间 App (User 0)");
            app.launch(pkg);
            return true;
        } else if (acc.type === "clone_user_999") {
            Logger.info("通过 shell 启动工作区/双开分身 (User 999)");
            shell("am start --user " + (acc.userId || 999) + " -n " + pkg + "/com.unity3d.player.UnityPlayerActivity", true);
            return true;
        } else if (acc.type === "phone_auth") {
            Logger.info("执行账号密码热注销并重新登录: " + acc.user);
            return this.reloginCredentials(acc.user, acc.pass);
        }
        return false;
    },

    // 游戏内凭证切换
    reloginCredentials: function(user, pass) {
        app.launch("com.game.capy");
        sleep(4000);
        // 点击右上角设置 -> 切换账号 -> 输入密码 (略)
        return true;
    },

    // 强制杀掉应用释放手机运存与降温
    killCurrentApp: function(acc) {
        let pkg = "com.game.capy";
        Logger.info("强制停止应用，释放后台资源与内存");
        shell("am force-stop " + pkg, true);
    },

    // 切换飞行模式重置蜂窝基站分配的公网动态 IP (防集中提交被封号)
    resetDynamicIp: function() {
        Logger.info("正在执行飞行模式跳跃，重置设备公网 IP...");
        // 开启飞行模式
        shell("settings put global airplane_mode_on 1", true);
        shell("am broadcast -a android.intent.action.AIRPLANE_MODE --ez state true", true);
        sleep(5000);
        // 关闭飞行模式恢复网络
        shell("settings put global airplane_mode_on 0", true);
        shell("am broadcast -a android.intent.action.AIRPLANE_MODE --ez state false", true);
        sleep(4000);
        Logger.info("动态 IP 已刷新完成，网络已重新接入");
    }
};

module.exports = AccountManager;
`
  },
  {
    name: 'tasks/guild_engine.js',
    path: 'tasks/guild_engine.js',
    category: 'tasks',
    description: '公会模块：公会签到、金币捐赠3次拉满、航海船票提交反哺主号',
    content: `// tasks/guild_engine.js
const Automator = require('../core/automator.js');
const Vision = require('../core/vision.js');
const Logger = require('../core/logger.js');

function runGuildTasks() {
    Logger.info(">>> 开始执行公会建设与航海船票供奉任务...");
    
    // 1. 进入公会
    let pGuild = Vision.findImage("guild_icon.png");
    if (pGuild) {
        Automator.humanClick(pGuild.x, pGuild.y);
    } else {
        // 默认主城公会坐标兜底
        Automator.humanClick(device.width * 0.82, device.height * 0.88);
    }
    sleep(2500);

    // 2. 每日金币捐献 (固定拉满3次)
    Logger.info("执行公会金币3次建设...");
    for (let i = 1; i <= 3; i++) {
        Automator.humanClick(device.width * 0.5, device.height * 0.72);
        sleep(800);
    }

    // 3. 提交航海船票
    Logger.info("进入航海大厅，提交小号积攒的公会船票...");
    Automator.humanClick(device.width * 0.75, device.height * 0.35); // 船票 Tab
    sleep(1500);
    Automator.humanClick(device.width * 0.5, device.height * 0.82); // 一键提交
    sleep(1000);

    // 4. 返回主城
    Automator.humanClick(60, 80);
    sleep(1500);
    Logger.info("公会日常建设任务完成，已返回主城");
    return true;
}

module.exports = { runGuildTasks };
`
  },
  {
    name: 'tasks/stage_pusher.js',
    path: 'tasks/stage_pusher.js',
    category: 'tasks',
    description: '主线推关与局内决策：战斗监听、三选一技能识别、胜负重试',
    content: `// tasks/stage_pusher.js
const Automator = require('../core/automator.js');
const Vision = require('../core/vision.js');
const Logger = require('../core/logger.js');

function runStagePush(maxStages = 2) {
    Logger.info(">>> 开始主线自动推关任务，目标关卡数: " + maxStages);

    let cleared = 0;
    while (cleared < maxStages) {
        // 点击主城中央“出战”按钮
        Automator.humanClick(device.width * 0.5, device.height * 0.82);
        sleep(3000);

        let battleOver = false;
        let battleStartTime = Date.now();

        while (!battleOver) {
            // 检查战斗是否超时 (一局通常不超过 3 分钟)
            if (Date.now() - battleStartTime > 180 * 1000) {
                Logger.warn("战斗已持续 3 分钟超时，强制重置");
                break;
            }

            // 检查是否触发升级“技能三选一”
            let upgradeTitle = textMatches(/(选择技能|提升战力|请选择)/).findOnce();
            if (upgradeTitle) {
                Logger.ocr("触发技能升级弹窗，调用 PaddleOCR 识别技能选项...");
                let decision = Vision.chooseBestSkill();
                Logger.info("已选技能: " + decision.skill);
                sleep(1500);
                continue;
            }

            // 检查战斗结算 (胜利 / 失败)
            let winBtn = textMatches(/(点击继续|领取奖励|下一关)/).findOnce();
            if (winBtn) {
                Logger.info("恭喜！通关本关卡！");
                Automator.humanClick(winBtn.bounds().centerX(), winBtn.bounds().centerY());
                cleared++;
                battleOver = true;
                sleep(2500);
                break;
            }

            let defeatBtn = textMatches(/(再次挑战|返回主城|复活)/).findOnce();
            if (defeatBtn) {
                Logger.warn("战败！小号战力达到当前瓶颈，返回主城强化");
                Automator.humanClick(defeatBtn.bounds().centerX(), defeatBtn.bounds().centerY());
                battleOver = true;
                sleep(2500);
                return cleared; // 战败直接退出推关流程
            }

            sleep(1000); // 战斗进行中每秒轮询一次
        }
    }

    Logger.info("主线推关阶段目标已达成，当前已通关: " + cleared + " 关");
    return cleared;
}

module.exports = { runStagePush };
`
  },
  {
    name: 'tasks/daily_harvest.js',
    path: 'tasks/daily_harvest.js',
    category: 'tasks',
    description: '主城收菜与日常扫荡：20倍体力游历、战力属性加点、地牢扫荡',
    content: `// tasks/daily_harvest.js
const Automator = require('../core/automator.js');
const Logger = require('../core/logger.js');

function runHarvest() {
    Logger.info(">>> 开始主城日常收菜与体力游历...");

    // 1. 点击进入游历宝箱
    Automator.humanClick(device.width * 0.25, device.height * 0.78);
    sleep(1500);

    // 2. 领取累计挂机宝箱
    Automator.humanClick(device.width * 0.5, device.height * 0.85);
    sleep(1200);

    // 3. 点击20倍体力快速游历
    Logger.info("消耗体力执行 20 倍快速游历升级...");
    Automator.humanClick(device.width * 0.78, device.height * 0.85);
    sleep(2000);

    // 4. 属性加点 (小号优先拉满“生命”与“攻击”，提升挂机生存率)
    Logger.info("升级攻击与生命基础属性...");
    Automator.humanClick(device.width * 0.35, device.height * 0.65); // 攻击
    sleep(500);
    Automator.humanClick(device.width * 0.65, device.height * 0.65); // 生命
    sleep(1000);

    // 5. 返回主城
    Automator.humanClick(60, 80);
    sleep(1200);
    Logger.info("主城体力收菜完毕！");
    return true;
}

module.exports = { runHarvest };
`
  },
  {
    name: 'README_DEPLOY.md',
    path: 'README_DEPLOY.md',
    category: 'docs',
    description: 'Android 真机部署步骤、ADB 调试指令与无障碍权限配置指南',
    content: `# CapyScript 安卓真机部署与运行指南

## 1. 宿主软件安装
- 下载并安装 **AutoX.js v6.6+** (开源无需Root版本)。
- 安装配套的 **PaddleOCR-NCNN** 离线推理扩展插件（安装后首次启动脚本时会自动加载本地模型权重）。

## 2. 必备系统权限清单
进入手机【设置】 -> 【应用管理】 -> 【AutoX.js】:
1. **无障碍服务 (AccessibilityService)**: 必须开启。
2. **显示悬浮窗 (Display over other apps)**: 用于显示监控悬浮窗。
3. **截屏录屏权限**: 勾选“不再提示”并允许。
4. **忽略电池优化 / 后台无限制运行**: 防止锁屏或省电模式杀进程。

## 3. 部署代码到手机存储
通过无线 ADB 或 USB 数据线将工程文件夹推送到手机指定目录：

\`\`\`bash
# 1. 连接手机 (无线调试)
adb connect 192.168.1.xxx:5555

# 2. 创建工程目录
adb shell mkdir -p /sdcard/CapyScript/

# 3. 推送完整工程包
adb push . /sdcard/CapyScript/
\`\`\`

## 4. 启动与急停
- 打开 AutoX.js，在文件列表进入 \`/sdcard/CapyScript/\`。
- 点击 \`main.js\` 右侧的运行图标即可启动。
- **急停按键**：按手机【音量下键】可立即强制中止所有后台自动化线程。
`
  }
];
