from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

# 账号集合里需要记录完成情况的工作项，顺序即推荐执行顺序
WORK_KEYS = ("daily", "guild", "ship", "stage")
WORK_LABELS = {
    "daily": "日常",
    "guild": "公会",
    "ship": "船",
    "stage": "推关",
}
DEFAULT_ACCOUNTS_PATH = Path(__file__).resolve().parents[1] / ".data" / "accounts.json"


def accounts_path() -> Path:
    return Path(os.environ.get("CAPYAUTO_ACCOUNTS") or DEFAULT_ACCOUNTS_PATH)


def load_accounts() -> list[dict[str, Any]]:
    try:
        raw = json.loads(accounts_path().read_text("utf-8"))
    except (OSError, ValueError):
        return []
    items = raw.get("accounts") if isinstance(raw, dict) else None
    return [item for item in items or [] if isinstance(item, dict) and item.get("name")]


def record_work(
    name: str,
    work: str,
    *,
    power: int = 0,
    stamina: int = 0,
    at: float | None = None,
) -> dict[str, Any] | None:
    """记录某个账号一项工作的完成情况，返回更新后的账号条目。"""
    name = (name or "").strip()
    if not name or work not in WORK_KEYS:
        return None
    timestamp = at if at is not None else time.time()
    accounts = load_accounts()
    entry = next((item for item in accounts if item.get("name") == name), None)
    if entry is None:
        entry = {"name": name, "createdAt": timestamp, "works": {}}
        accounts.append(entry)
    works = entry.setdefault("works", {})
    record = works.get(work) or {}
    record["count"] = int(record.get("count", 0)) + 1
    record["doneAt"] = timestamp
    works[work] = record
    entry["updatedAt"] = timestamp
    if power:
        entry["power"] = power
    if stamina:
        entry["stamina"] = stamina
    save_accounts(accounts)
    return entry


def record_account_run(
    name: str,
    run_id: str,
    status: str,
    *,
    current_phase: str = "",
    error: str = "",
    progress: dict[str, Any] | None = None,
    at: float | None = None,
) -> dict[str, Any]:
    """记录一次端侧或 ADB 执行；同一 runId 保留首次开始时间。"""
    name = (name or "").strip()
    run_id = (run_id or "").strip()
    if not name or not run_id:
        raise ValueError("账号名和 runId 不能为空")
    if status not in {"pending", "running", "completed", "failed", "stopped"}:
        raise ValueError(f"未知账号执行状态: {status}")
    timestamp = at if at is not None else time.time()
    accounts = load_accounts()
    entry = next((item for item in accounts if item.get("name") == name), None)
    if entry is None:
        entry = {"name": name, "createdAt": timestamp, "works": {}}
        accounts.append(entry)
    previous = entry.get("lastRun") or {}
    started_at = previous.get("startedAt", timestamp) if previous.get("runId") == run_id else timestamp
    entry["lastRun"] = {
        "runId": run_id,
        "status": status,
        "currentPhase": current_phase,
        "error": error,
        "startedAt": started_at,
        "updatedAt": timestamp,
        "progress": dict(progress or {}),
    }
    entry["updatedAt"] = timestamp
    save_accounts(accounts)
    return entry


def ensure_account(
    name: str, *, power: int = 0, stamina: int = 0, at: float | None = None
) -> dict[str, Any] | None:
    """把账号登记进集合（即使本次还没有任何工作完成）。"""
    name = (name or "").strip()
    if not name:
        return None
    timestamp = at if at is not None else time.time()
    accounts = load_accounts()
    entry = next((item for item in accounts if item.get("name") == name), None)
    if entry is None:
        entry = {"name": name, "createdAt": timestamp, "works": {}}
        accounts.append(entry)
    entry["updatedAt"] = timestamp
    if power:
        entry["power"] = power
    if stamina:
        entry["stamina"] = stamina
    save_accounts(accounts)
    return entry


def reset_account_works(
    names: list[str] | None = None, *, at: float | None = None
) -> dict[str, Any]:
    """清空账号的任务完成状态（works），保留账号身份、存档指标与 lastRun 历史。

    游戏每日 8 点重置日常，调度器在该时点调用本函数，让「今日已完成」标记归零。
    names=None 表示全部账号；传入名单时只重置命中的账号（未知名字忽略）。
    """
    timestamp = at if at is not None else time.time()
    wanted = (
        None
        if names is None
        else {name.strip() for name in names if isinstance(name, str) and name.strip()}
    )
    accounts = load_accounts()
    reset = 0
    for entry in accounts:
        name = entry.get("name", "")
        if wanted is not None and name not in wanted:
            continue
        entry["works"] = {}
        entry["worksResetAt"] = timestamp
        entry["updatedAt"] = timestamp
        reset += 1
    if reset:
        save_accounts(accounts)
    return {"reset": reset, "at": timestamp, "names": sorted(wanted) if wanted is not None else None}


def save_accounts(accounts: list[dict[str, Any]]) -> None:
    path = accounts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps({"accounts": accounts}, ensure_ascii=False), "utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def account_summary() -> list[dict[str, Any]]:
    """账号集合视图：每项工作都给出是否完成，便于批量核对。"""
    summary: list[dict[str, Any]] = []
    for entry in load_accounts():
        works = entry.get("works") or {}
        summary.append(
            {
                "name": entry.get("name", ""),
                "power": entry.get("power", 0),
                "stamina": entry.get("stamina", 0),
                "updatedAt": entry.get("updatedAt"),
                "lastRun": entry.get("lastRun"),
                "works": {
                    key: {
                        "label": WORK_LABELS[key],
                        "done": bool(works.get(key)),
                        "count": int((works.get(key) or {}).get("count", 0)),
                        "doneAt": (works.get(key) or {}).get("doneAt"),
                    }
                    for key in WORK_KEYS
                },
            }
        )
    summary.sort(key=lambda item: item.get("updatedAt") or 0, reverse=True)
    return summary
