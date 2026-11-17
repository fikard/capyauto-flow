#!/bin/bash
# 生成 autox/config.local.json —— 端侧脚本的后端地址来源。
#
# 端口唯一事实源 = devgate 注册表；IP 取本机局域网地址。
# 生成的文件不入库（见 .gitignore），换网络 / 换端口时重跑本脚本即可。
#
# 用法:
#   bash scripts/gen-autox-config.sh
#   bash scripts/gen-autox-config.sh --ip 192.168.1.23 --port 8084
#   bash scripts/gen-autox-config.sh --dry-run false   # 实机验收时才关 dry-run
#   CAPYAUTO_BACKEND_PORT=9000 bash scripts/gen-autox-config.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEVGATE="${DEVGATE_BIN:-$HOME/Desktop/self_project/devgate/bin/devgate}"
TARGET="${CAPYAUTO_AUTOX_CONFIG:-$ROOT/autox/config.local.json}"
PORT="${CAPYAUTO_BACKEND_PORT:-}"
LAN_IP="${CAPYAUTO_LAN_IP:-}"
DRY_RUN="${CAPYAUTO_AUTOX_DRY_RUN:-true}"

while [ $# -gt 0 ]; do
  case "$1" in
    --ip) LAN_IP="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --dry-run) DRY_RUN="$2"; shift 2 ;;
    --output) TARGET="$2"; shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

# devgate 不可用时才用兜底值（与 scripts/web.sh 一致），不做静默硬编码。
if [ -z "$PORT" ] && [ -x "$DEVGATE" ]; then
  PORT="$("$DEVGATE" port capyauto-flow backend 2>/dev/null || true)"
fi
PORT="${PORT:-8084}"

if [ -z "$LAN_IP" ]; then
  for iface in en0 en1; do
    LAN_IP="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
    [ -n "$LAN_IP" ] && break
  done
fi

case "$PORT" in
  ''|*[!0-9]*) echo "错误：端口非法 $PORT" >&2; exit 2 ;;
esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "错误：端口超出 1~65535: $PORT" >&2; exit 2
fi
if [ -z "$LAN_IP" ]; then
  echo "错误：未探测到局域网 IP，请用 --ip 指定（手机需能访问该地址）" >&2
  exit 2
fi
if [ "$DRY_RUN" != "true" ] && [ "$DRY_RUN" != "false" ]; then
  echo "错误：--dry-run 只能是 true 或 false" >&2; exit 2
fi

mkdir -p "$(dirname "$TARGET")"
cat > "$TARGET" <<EOF
{
  "backendUrl": "http://${LAN_IP}:${PORT}",
  "dryRun": ${DRY_RUN}
}
EOF

echo "已生成 $TARGET"
echo "  backendUrl = http://${LAN_IP}:${PORT} (端口来自 devgate / --port)"
echo "  dryRun     = ${DRY_RUN}"
echo "提醒：手机与电脑需在同一局域网，且后端需监听 0.0.0.0 而非仅 127.0.0.1。"
