import { useCallback, useEffect, useRef, useState } from 'react';
import { DeviceApiError, deviceClient } from '../api/deviceClient';
import type {
  AccountRecord,
  AutomationPayload,
  AutomationTask,
  BridgeMode,
  CurrentAppPayload,
  DeviceInfoPayload,
  HealthPayload,
  OcrPayload,
  SessionPayload,
  SwipeDirection,
  TapPayload,
  UsersPayload,
  VerifyPayload,
} from '../types/device';
import type { OcrRegion, PipelineConfig } from '../types/pipeline';

const DEFAULT_PACKAGE = 'com.hb.cncapy.and';
/** 游戏由「冲鸭变速器」沙箱托管，桌面快捷方式「冒险者日记」是唯一合法启动入口 */
export const LAUNCHER_HOST_PACKAGE = 'com.joke.chongya';
export const LAUNCHER_ICON_LABEL = '冒险者日记';

export function useDeviceBridge() {
  const [mode, setMode] = useState<BridgeMode>('sim');
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [devices, setDevices] = useState<DeviceInfoPayload[]>([]);
  const [device, setDevice] = useState<DeviceInfoPayload | null>(null);
  const [session, setSession] = useState<SessionPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [lastTap, setLastTap] = useState<TapPayload | null>(null);
  const [users, setUsers] = useState<UsersPayload | null>(null);
  const [ocr, setOcr] = useState<OcrPayload | null>(null);
  const [automation, setAutomation] = useState<AutomationPayload | null>(null);
  const [currentApp, setCurrentApp] = useState<CurrentAppPayload | null>(null);
  const [verifyResult, setVerifyResult] = useState<VerifyPayload | null>(null);
  const [verifyBusy, setVerifyBusy] = useState(false);
  // 真机账号集合唯一来源：/api/accounts（与仿真域的演示数据严格分开）
  const [accounts, setAccounts] = useState<AccountRecord[]>([]);
  const sessionRef = useRef<SessionPayload | null>(null);
  sessionRef.current = session;
  // 会话代际：每次连接尝试 / 断开都会自增，用于丢弃陈旧在途响应
  const generationRef = useRef(0);
  const connectingRef = useRef<Promise<void> | null>(null);

  const run = useCallback(async <T,>(work: () => Promise<T>, alive?: () => boolean): Promise<T | null> => {
    setBusy(true);
    setError(null);
    try {
      return await work();
    } catch (exc) {
      if (!alive || alive()) {
        const message = exc instanceof DeviceApiError ? `${exc.code}: ${exc.message}` : String(exc);
        setError(message);
      }
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const refreshDevices = useCallback(async () => {
    const health = await run(() => deviceClient.health());
    if (health) setHealth(health);
    const list = await run(() => deviceClient.listDevices());
    if (list) setDevices(list.devices);
    return list?.devices ?? [];
  }, [run]);

  const connect = useCallback(async (serial?: string) => {
    const pending = connectingRef.current;
    if (pending) return pending;
    const task = (async () => {
      const generation = ++generationRef.current;
      try {
        const list = await refreshDevices();
        if (generationRef.current !== generation) return;
        const target = list.find((row) => row.serial === serial) ?? list.find((row) => row.state === 'device');
        if (!target) return;
        setDevice(target);
        const previous = sessionRef.current;
        if (previous) {
          sessionRef.current = null;
          setSession(null);
          setLastTap(null);
          setUsers(null);
          setOcr(null);
          setCurrentApp(null);
          await run(() => deviceClient.closeSession(previous.sessionId));
        }
        if (generationRef.current !== generation) return;
        const created = await run(() => deviceClient.createSession(target.serial, 5));
        if (!created) return;
        if (generationRef.current !== generation) {
          // 创建期间已被断开或新一轮连接接管，回收本次会话避免泄漏
          await run(() => deviceClient.closeSession(created.sessionId));
          return;
        }
        sessionRef.current = created;
        setSession(created);
      } finally {
        connectingRef.current = null;
      }
    })();
    connectingRef.current = task;
    return task;
  }, [refreshDevices, run]);

  const disconnect = useCallback(async () => {
    generationRef.current += 1;
    const current = sessionRef.current;
    sessionRef.current = null;
    setSession(null);
    setLastTap(null);
    setOcr(null);
    setUsers(null);
    setCurrentApp(null);
    if (current) await run(() => deviceClient.closeSession(current.sessionId));
  }, [run]);

  const switchMode = useCallback(async (next: BridgeMode) => {
    setMode(next);
    if (next === 'real' && !sessionRef.current) {
      await connect();
    }
  }, [connect]);

  // 仿真域的高斯/按压参数透传到真机注入，不再只用后端默认值
  const tap = useCallback(
    async (x: number, y: number, pressMs = 80, sigma = 6, pressStdev = 20) => {
      const current = sessionRef.current;
      if (!current) return null;
      const generation = generationRef.current;
      const alive = () =>
        generationRef.current === generation && sessionRef.current?.sessionId === current.sessionId;
      const result = await run(
        () => deviceClient.tap(current.sessionId, x, y, pressMs, sigma, pressStdev),
        alive
      );
      if (result && alive()) setLastTap(result);
      return result;
    },
    [run]
  );

  const swipe = useCallback(
    async (direction: SwipeDirection) => {
      const current = sessionRef.current;
      if (!current) return null;
      const generation = generationRef.current;
      const alive = () =>
        generationRef.current === generation && sessionRef.current?.sessionId === current.sessionId;
      const paths: Record<SwipeDirection, [number, number, number, number]> = {
        up: [0.5, 0.75, 0.5, 0.25],
        down: [0.5, 0.25, 0.5, 0.75],
        left: [0.8, 0.5, 0.2, 0.5],
        right: [0.2, 0.5, 0.8, 0.5],
      };
      const [x1, y1, x2, y2] = paths[direction];
      return run(() => deviceClient.swipe(current.sessionId, x1, y1, x2, y2), alive);
    },
    [run]
  );

  const pressKey = useCallback(
    async (key: string) => {
      const current = sessionRef.current;
      if (!current) return null;
      const generation = generationRef.current;
      const alive = () =>
        generationRef.current === generation && sessionRef.current?.sessionId === current.sessionId;
      return run(() => deviceClient.key(current.sessionId, key), alive);
    },
    [run]
  );

  const refreshCurrentApp = useCallback(async () => {
    const current = sessionRef.current;
    if (!current) return null;
    const generation = generationRef.current;
    const alive = () =>
      generationRef.current === generation && sessionRef.current?.sessionId === current.sessionId;
    const result = await run(() => deviceClient.currentApp(current.sessionId), alive);
    if (result && alive()) setCurrentApp(result);
    return result;
  }, [run]);

  const runVerify = useCallback(async (skip: string[] = []) => {
    // 真机验收可能持续数十秒，单独维护 busy，避免长时间锁死其它控制按钮
    setVerifyBusy(true);
    setError(null);
    try {
      const result = await deviceClient.verifyRun(skip);
      setVerifyResult(result);
      return result;
    } catch (exc) {
      const message =
        exc instanceof DeviceApiError ? `${exc.code}: ${exc.message}` : String(exc);
      setError(message);
      return null;
    } finally {
      setVerifyBusy(false);
    }
  }, []);

  const launchGame = useCallback(async (packageName = DEFAULT_PACKAGE) => {
    const current = sessionRef.current;
    if (!current) return null;
    const generation = generationRef.current;
    const alive = () => generationRef.current === generation && sessionRef.current?.sessionId === current.sessionId;
    // 跟随当前用户启动，避免多用户设备上 switch-user 后仍强制回到 user 0
    const activeUserId = users?.users.find((row) => row.current)?.id;
    const result = await run(
      () => deviceClient.launchApp(current.sessionId, packageName, activeUserId),
      alive
    );
    if (result && alive()) {
      // 后端现在返回真实前台（变速器宿主 + STUB1），启动后立刻同步展示，
      // 不再让页面停留在静态游戏包名 com.hb.cncapy.and 上。
      setCurrentApp({
        package: result.package,
        activity: result.activity,
        running: result.running,
        pid: result.pid,
      });
    }
    return result;
  }, [run, users]);

  const stopGame = useCallback(async (packageName = DEFAULT_PACKAGE) => {
    const current = sessionRef.current;
    if (!current) return null;
    const generation = generationRef.current;
    const alive = () => generationRef.current === generation && sessionRef.current?.sessionId === current.sessionId;
    const result = await run(() => deviceClient.stopApp(current.sessionId, packageName), alive);
    if (result && alive()) await refreshCurrentApp();
    return result;
  }, [run, refreshCurrentApp]);

  const loadUsers = useCallback(async () => {
    const current = sessionRef.current;
    if (!current) return null;
    const generation = generationRef.current;
    const alive = () => generationRef.current === generation && sessionRef.current?.sessionId === current.sessionId;
    const result = await run(() => deviceClient.listUsers(current.sessionId), alive);
    if (result && alive()) setUsers(result);
    return result;
  }, [run]);

  const switchUser = useCallback(async (userId: number) => {
    const current = sessionRef.current;
    if (!current) return null;
    const generation = generationRef.current;
    const alive = () => generationRef.current === generation && sessionRef.current?.sessionId === current.sessionId;
    const result = await run(() => deviceClient.switchUser(current.sessionId, userId), alive);
    if (result && alive()) await loadUsers();
    return result;
  }, [loadUsers, run]);

  const toggleAirplane = useCallback(async (enable: boolean) => {
    const current = sessionRef.current;
    if (!current) return null;
    const generation = generationRef.current;
    const alive = () => generationRef.current === generation && sessionRef.current?.sessionId === current.sessionId;
    return run(() => deviceClient.airplane(current.sessionId, enable), alive);
  }, [run]);

  const runOcr = useCallback(async (region: OcrRegion | null = null) => {
    const current = sessionRef.current;
    if (!current) return null;
    const generation = generationRef.current;
    const alive = () => generationRef.current === generation && sessionRef.current?.sessionId === current.sessionId;
    const result = await run(() => deviceClient.ocr(current.sessionId, region), alive);
    if (result && alive()) setOcr(result);
    return result;
  }, [run]);

  /**
   * 配置由 App 的 usePipelineConfig 统一传入（含 skillPriorityList 与全部自动化参数），
   * 本 hook 不再维护第二份配置状态，避免刷新丢失和参数遗漏。
   */
  const startAutomation = useCallback(
    async (task: AutomationTask, config: PipelineConfig) => {
      const current = sessionRef.current;
      if (!current) return null;
      const result = await run(() =>
        deviceClient.automationStart(
          current.sessionId,
          task,
          config.maxRuns,
          config.skillPriorityList,
          config.speed,
          config.towerFloors,
          {
            maxStageFails: config.maxStageFails,
            travelStamina: config.travelStamina,
            allowGemTalentBreakthrough: config.allowGemTalentBreakthrough,
            stageMode: config.stageMode,
            fastStageCheckEvery: config.fastStageCheckEvery,
            account: config.account,
            accounts: task === 'account_sweep' ? config.accountQueue : undefined,
            serverFrom: config.serverFrom,
            serverTo: config.serverTo,
            serverDryRun: config.serverDryRun,
          }
        )
      );
      if (result) setAutomation(result);
      return result;
    },
    [run]
  );

  const stopAutomation = useCallback(async () => {
    const result = await run(() => deviceClient.automationStop());
    if (result) setAutomation(result);
    return result;
  }, [run]);

  /** 手动刷新账号集合（账号页 / 队列填充按钮用），失败时保留上一次结果 */
  const refreshAccounts = useCallback(async () => {
    const result = await run(() => deviceClient.accounts());
    if (result) setAccounts(result.accounts);
    return result?.accounts ?? [];
  }, [run]);

  // 自动化状态与账号集合轮询：真机模式下每 2s 刷新一次，失败不打断主流程
  useEffect(() => {
    if (mode !== 'real') return;
    let alive = true;
    const tick = async () => {
      try {
        const result = await deviceClient.automationStatus();
        if (alive) setAutomation(result);
        const collection = await deviceClient.accounts();
        if (alive) setAccounts(collection.accounts);
      } catch {
        // 后端未就绪时静默跳过
      }
    };
    tick();
    const timer = setInterval(tick, 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [mode]);

  useEffect(() => {
    if (mode === 'real') {
      refreshDevices();
    }
  }, [mode, refreshDevices]);

  return {
    mode, switchMode, health, devices, device, session, error, busy,
    lastTap, users, ocr, automation, connect, disconnect, tap,
    swipe, pressKey, refreshCurrentApp, currentApp,
    launchGame, stopGame, loadUsers, switchUser, toggleAirplane, runOcr,
    startAutomation, stopAutomation,
    accounts, refreshAccounts, refreshDevices, defaultPackage: DEFAULT_PACKAGE,
    launcherHostPackage: LAUNCHER_HOST_PACKAGE, launcherIconLabel: LAUNCHER_ICON_LABEL,
    verifyResult, verifyBusy, runVerify,
  };
}
