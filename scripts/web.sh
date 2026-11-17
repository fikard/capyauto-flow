#!/bin/bash
# capyauto-flow Web 服务统一入口（devgate 生成）
#
# 用法:
#   bash scripts/web.sh start   [--fg] [--backend] [--frontend]   # 默认全部服务；--fg 前台（仅单服务）
#   bash scripts/web.sh stop    [--backend] [--frontend]
#   bash scripts/web.sh restart [--backend] [--frontend]
#   bash scripts/web.sh status
#
# 端口唯一事实源 = devgate 注册表（/Users/fikard/.config/devgate/registry.yaml）。
# devgate 不可用/未登记时回退到下方兜底值，保证脚本在任何机器上都能跑。
# PID 落 .devgate/pids/，日志落 .devgate/logs/。
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEVGATE="${DEVGATE_BIN:-$HOME/Desktop/self_project/devgate/bin/devgate}"
dg_port() { [ -x "$DEVGATE" ] && "$DEVGATE" port "$1" "$2" 2>/dev/null || echo "$3"; }

# ───────────── 还原用户 PATH ─────────────
# ⚠️ 从 agent 里跑这个脚本时，PATH 最前面是 agent 自带的 python
# （没装项目依赖），用它拉服务会得到 ModuleNotFoundError；
# 而同一个脚本在 Terminal 里跑是好的。行为必须一致，所以主动摘掉。
purge_path() {
  local out="" seg oldifs="$IFS"
  IFS=":"
  for seg in $PATH; do
    case "$seg" in
      */.workbuddy/binaries/*|*/.workbuddy/plugins/*|*WorkBuddy.app/Contents/Resources/*) continue ;;
    esac
    out="${out:+$out:}$seg"
  done
  IFS="$oldifs"
  echo "$out"
}
PATH="$(purge_path)"
export PATH
# agent 还用 PYTHONPATH 注入 sitecustomize —— 不清掉的话，项目代码里
# 普通的 mkdir/open 都会被它拦（实测 PermissionError: EEXIST on mkdir）。
# ⚠️ 同理别碰 CONDA_*：没有自带 venv 的项目靠 conda base 活着。
unset PYTHONHOME PYTHONPATH PYTHONEXECUTABLE VIRTUAL_ENV \
      __PYVENV_LAUNCHER__ PYTHONNOUSERSITE 2>/dev/null || true

# ───────────── 端口（devgate → 环境变量 → 兜底）─────────────
CAPYAUTO_BACKEND_PORT="${CAPYAUTO_BACKEND_PORT:-$(dg_port capyauto-flow backend 8084)}"
export CAPYAUTO_BACKEND_PORT
CAPYAUTO_FRONTEND_PORT="${CAPYAUTO_FRONTEND_PORT:-$(dg_port capyauto-flow frontend 5178)}"
export CAPYAUTO_FRONTEND_PORT
PID_DIR="$ROOT/.devgate/pids"
LOG_DIR="$ROOT/.devgate/logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

# ───────────── 服务 → 端口 / 工作目录 / 命令 ─────────────
svc_port() { case "$1" in backend) echo "$CAPYAUTO_BACKEND_PORT" ;; frontend) echo "$CAPYAUTO_FRONTEND_PORT" ;;  esac; }
svc_cwd()  { case "$1" in backend) echo "$ROOT/backend" ;; frontend) echo "$ROOT" ;;  esac; }
svc_cmd()  { case "$1" in backend) echo '.venv/bin/python -m app' ;; frontend) echo 'npm run dev' ;;  esac; }
SERVICES=("backend" "frontend")

svc_pidfile() { echo "$PID_DIR/.web-$1.pid"; }
svc_log()     { echo "$LOG_DIR/web-$1.log"; }

# ───────────── 工具函数 ─────────────
is_running() {
  local pf="$1" pid
  [ -f "$pf" ] || return 1
  pid="$(cat "$pf" 2>/dev/null)" || return 1
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null
}

port_listening() {
  # ⚠️ 必须 --noproxy：本机有 HTTP 代理时，curl 127.0.0.1:8082 会走代理，
  # 代理返回 502/503 也让 curl 退出 0 —— 于是"端口可达"永远为真，
  # 服务再也起不来。lsof 兜底是因为有些服务对 GET / 返回非 2xx。
  command -v curl >/dev/null 2>&1 &&
    curl -s -o /dev/null --noproxy '*' --max-time 2 "http://127.0.0.1:$1/" 2>/dev/null && return 0
  lsof -tiTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

start_one() {
  local name="$1" port cwd cmd pidfile log
  port="$(svc_port "$name")"; cwd="$(svc_cwd "$name")"; cmd="$(svc_cmd "$name")"
  pidfile="$(svc_pidfile "$name")"; log="$(svc_log "$name")"
  if [ -z "$cmd" ]; then echo "[$name] 未定义启动命令"; return 1; fi
  if is_running "$pidfile"; then
    echo "[$name] 已在运行 (PID $(cat "$pidfile"))，跳过"; return 0
  fi
  if port_listening "$port"; then
    echo "[$name] 端口 $port 已被占用（可能由其它方式启动），跳过"; return 0
  fi
  echo "[$name] 启动中 → :$port  ($cmd)"
  # </dev/null 不能省：后台进程若继承 shell 的 stdin（管道），调用方会一直
  # 等到 stdin 关闭才返回 —— 实测 web.sh start 卡了 4 分钟不退出。
  (
    cd "$cwd" || exit 1
    nohup bash -c "exec $cmd" </dev/null >>"$log" 2>&1 &
    echo $! >"$pidfile"
  )
  local i
  for i in $(seq 1 20); do port_listening "$port" && break; sleep 0.5; done
  if is_running "$pidfile"; then
    echo "[$name] 已启动 PID=$(cat "$pidfile")  日志=$log"
  else
    echo "[$name] 启动失败（进程已退出）。日志尾部："
    tail -n 20 "$log" 2>/dev/null
    rm -f "$pidfile"; return 1
  fi
}

stop_one() {
  local name="$1" pidfile port pid
  pidfile="$(svc_pidfile "$name")"; port="$(svc_port "$name")"
  if is_running "$pidfile"; then
    pid="$(cat "$pidfile")"
    echo "[$name] 停止中 (PID $pid)…"
    kill "$pid" 2>/dev/null || true
    local i
    for i in $(seq 1 10); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
    kill -0 "$pid" 2>/dev/null && { echo "[$name] 未退出，强制 kill -9"; kill -9 "$pid" 2>/dev/null || true; }
    rm -f "$pidfile"; echo "[$name] 已停止"; return 0
  fi
  if port_listening "$port"; then
    local pids
    pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null)"
    if [ -n "$pids" ]; then
      echo "[$name] 非本脚本管理，按端口 kill: $pids"
      kill -TERM $pids 2>/dev/null || true
      rm -f "$pidfile"; return 0
    fi
    echo "[$name] 端口 $port 有服务但拿不到 PID，无法停止"
  fi
  rm -f "$pidfile"
  echo "[$name] 未运行"
}

status_one() {
  local name="$1" pidfile port extra=""
  pidfile="$(svc_pidfile "$name")"; port="$(svc_port "$name")"
  if is_running "$pidfile"; then
    if port_listening "$port"; then extra="端口可达"; else extra="PID存活"; fi
    printf "  [%-10s] 运行  PID=%-6s  http://127.0.0.1:%s/  (%s)\n" "$name" "$(cat "$pidfile")" "$port" "$extra"
  elif port_listening "$port"; then
    printf "  [%-10s] 运行  (端口 %s 被其它进程占用，非本脚本管理)\n" "$name" "$port"
  else
    printf "  [%-10s] 停止  http://127.0.0.1:%s/\n" "$name" "$port"
  fi
}

# ───────────── 参数解析 ─────────────
ACTION="${1:-status}"; shift || true
FG=0; PICK=""
for a in "$@"; do
  case "$a" in
    --backend) PICK="$PICK backend" ;;
    --frontend) PICK="$PICK frontend" ;;
    --fg) FG=1 ;;
    *) echo "未知参数: $a"; exit 1 ;;
  esac
done
[ -n "$PICK" ] || PICK=" ${SERVICES[*]} "

case "$ACTION" in
  start)
    if [ "$FG" -eq 1 ]; then
      n="$(echo "$PICK" | wc -w | tr -d ' ')"
      [ "$n" -eq 1 ] || { echo "--fg 仅支持单个服务"; exit 1; }
      name="$(echo "$PICK" | tr -d ' ')"
      cd "$(svc_cwd "$name")" && exec bash -c "$(svc_cmd "$name")"
    fi
    for name in $PICK; do start_one "$name"; done
    ;;
  stop)    for name in $PICK; do stop_one "$name"; done ;;
  restart) for name in $PICK; do stop_one "$name"; start_one "$name"; done ;;
  status)
    echo "capyauto-flow Web 服务统一入口（devgate 生成） 服务状态："
    for name in ${SERVICES[*]}; do status_one "$name"; done
    ;;
  *)
    echo "用法: bash scripts/web.sh {start|stop|restart|status} [--fg] [--backend] [--frontend]"
    exit 1
    ;;
esac
