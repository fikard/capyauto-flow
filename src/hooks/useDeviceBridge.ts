import { useCallback, useEffect, useRef, useState } from 'react';
import { DeviceApiError, deviceClient } from '../api/deviceClient';
import type {
  BridgeMode,
  DeviceInfoPayload,
  HealthPayload,
  OcrPayload,
  SessionPayload,
  TapPayload,
  UsersPayload,
} from '../types/device';

const DEFAULT_PACKAGE = 'com.hb.cncapy.and';

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
    if (current) await run(() => deviceClient.closeSession(current.sessionId));
  }, [run]);

  const switchMode = useCallback(async (next: BridgeMode) => {
    setMode(next);
    if (next === 'real' && !sessionRef.current) {
      await connect();
    }
  }, [connect]);

  const tap = useCallback(async (x: number, y: number) => {
    const current = sessionRef.current;
    if (!current) return null;
    const generation = generationRef.current;
    const alive = () => generationRef.current === generation && sessionRef.current?.sessionId === current.sessionId;
    const result = await run(() => deviceClient.tap(current.sessionId, x, y), alive);
    if (result && alive()) setLastTap(result);
    return result;
  }, [run]);

  const launchGame = useCallback(async (packageName = DEFAULT_PACKAGE) => {
    const current = sessionRef.current;
    if (!current) return null;
    const generation = generationRef.current;
    const alive = () => generationRef.current === generation && sessionRef.current?.sessionId === current.sessionId;
    return run(() => deviceClient.launchApp(current.sessionId, packageName, 0), alive);
  }, [run]);

  const stopGame = useCallback(async (packageName = DEFAULT_PACKAGE) => {
    const current = sessionRef.current;
    if (!current) return null;
    const generation = generationRef.current;
    const alive = () => generationRef.current === generation && sessionRef.current?.sessionId === current.sessionId;
    return run(() => deviceClient.stopApp(current.sessionId, packageName), alive);
  }, [run]);

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

  const runOcr = useCallback(async () => {
    const current = sessionRef.current;
    if (!current) return null;
    const generation = generationRef.current;
    const alive = () => generationRef.current === generation && sessionRef.current?.sessionId === current.sessionId;
    const result = await run(() => deviceClient.ocr(current.sessionId), alive);
    if (result && alive()) setOcr(result);
    return result;
  }, [run]);

  useEffect(() => {
    if (mode === 'real') {
      refreshDevices();
    }
  }, [mode, refreshDevices]);

  return {
    mode, switchMode, health, devices, device, session, error, busy,
    lastTap, users, ocr, connect, disconnect, tap,
    launchGame, stopGame, loadUsers, switchUser, toggleAirplane, runOcr,
    refreshDevices, defaultPackage: DEFAULT_PACKAGE,
  };
}
