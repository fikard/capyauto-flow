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

  const run = useCallback(async <T,>(work: () => Promise<T>): Promise<T | null> => {
    setBusy(true);
    setError(null);
    try {
      return await work();
    } catch (exc) {
      const message = exc instanceof DeviceApiError ? `${exc.code}: ${exc.message}` : String(exc);
      setError(message);
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
    const list = await refreshDevices();
    const target = list.find((row) => row.serial === serial) ?? list.find((row) => row.state === 'device');
    if (!target) return;
    setDevice(target);
    const created = await run(() => deviceClient.createSession(target.serial, 5));
    if (created) setSession(created);
  }, [refreshDevices, run]);

  const disconnect = useCallback(async () => {
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
    const result = await run(() => deviceClient.tap(current.sessionId, x, y));
    if (result) setLastTap(result);
    return result;
  }, [run]);

  const launchGame = useCallback(async (packageName = DEFAULT_PACKAGE) => {
    const current = sessionRef.current;
    if (!current) return null;
    return run(() => deviceClient.launchApp(current.sessionId, packageName, 0));
  }, [run]);

  const stopGame = useCallback(async (packageName = DEFAULT_PACKAGE) => {
    const current = sessionRef.current;
    if (!current) return null;
    return run(() => deviceClient.stopApp(current.sessionId, packageName));
  }, [run]);

  const loadUsers = useCallback(async () => {
    const current = sessionRef.current;
    if (!current) return null;
    const result = await run(() => deviceClient.listUsers(current.sessionId));
    if (result) setUsers(result);
    return result;
  }, [run]);

  const switchUser = useCallback(async (userId: number) => {
    const current = sessionRef.current;
    if (!current) return null;
    const result = await run(() => deviceClient.switchUser(current.sessionId, userId));
    if (result) await loadUsers();
    return result;
  }, [loadUsers, run]);

  const toggleAirplane = useCallback(async (enable: boolean) => {
    const current = sessionRef.current;
    if (!current) return null;
    return run(() => deviceClient.airplane(current.sessionId, enable));
  }, [run]);

  const runOcr = useCallback(async () => {
    const current = sessionRef.current;
    if (!current) return null;
    const result = await run(() => deviceClient.ocr(current.sessionId));
    if (result) setOcr(result);
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
