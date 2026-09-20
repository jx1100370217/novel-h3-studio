#!/usr/bin/env bash
set -euo pipefail

# Install the password-protected gateway as a persistent user service and,
# when Tailscale is authenticated, expose it through a stable Funnel address.
# Run this script as the normal desktop user, not with sudo.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_FILE="$UNIT_DIR/novel-h3-public-workbench.service"
mkdir -p "$UNIT_DIR"

cat > "$UNIT_FILE" <<EOF
[Unit]
Description=Novel H3 Studio public workbench gateway
After=novel-h3-workbench-persistent.service
Wants=novel-h3-workbench-persistent.service

[Service]
Type=simple
WorkingDirectory=$ROOT_DIR
ExecStart=$PYTHON_BIN -m novel_h3.public_gateway
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now novel-h3-public-workbench.service

# A previous setup may have left a temporary Cloudflare tunnel enabled.  It
# is not needed once Funnel is active and its URL changes after every restart.
systemctl --user disable --now novel-h3-public-tunnel.service 2>/dev/null || true

if ! command -v tailscale >/dev/null 2>&1; then
  echo "网关已启动：http://127.0.0.1:8766/"
  echo "未检测到 Tailscale；安装并登录后再次运行本脚本即可启用固定公网地址。"
  exit 0
fi

if ! sudo tailscale funnel --bg 8766; then
  echo "网关已启动，但 Tailscale Funnel 尚未启用或尚未登录。"
  echo "完成 Tailscale 登录并启用 Funnel 后，再次运行本脚本。"
  exit 0
fi

HOSTNAME="$(sudo tailscale status --json | "$PYTHON_BIN" -c \
  'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
if [[ -z "$HOSTNAME" ]]; then
  echo "Funnel 已启动，但没有读到 Tailscale DNS 名称。"
  exit 1
fi

mkdir -p "$ROOT_DIR/runtime"
cat > "$ROOT_DIR/runtime/public-progress-address.txt" <<EOF
https://$HOSTNAME/
完整可编辑工作台，必须密码认证；凭证保存在 runtime/public-workbench-credentials.json。
公网地址由 Tailscale Funnel 提供；保持 tailscaled 服务运行即可持续使用。
EOF

echo "固定公网工作台：https://$HOSTNAME/"
