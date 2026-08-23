#!/bin/bash
# Tuppy 生产部署脚本（VPS: /usr/local/bin/tuppy-deploy.sh）
#
# 触发方式：前台「更新」按钮 POST /deploy → www 写 .deploy-trigger
#           → root crontab 每分钟 [ -f .deploy-trigger ] 时运行本脚本
# （不是自动轮询：只有点按钮才会部署，push 本身不会触发）
#
# 行为：sudo -u www git fetch origin/main（带重试）→ reset --hard → 仅代码变更才 restart
# 日志：每次运行追加到 deploy.log，便于排查（根除原脚本 fetch 静默失败的问题）
set -u
REPO=/www/wwwroot/tuppy.oahubs.com
LOG="$REPO/deploy.log"
cd "$REPO" || exit 1
exec >> "$LOG" 2>&1
echo "$(date '+%F %T') --- deploy triggered ---"

# 写部署结果状态文件，供前台「更新」按钮右侧显示成功/失败图标
STATUS="$REPO/.deploy-status.json"
write_status(){
  local s="$1" m="$2"
  cat > "$STATUS" <<EOF
{"ts":"$(date '+%F %T')","status":"$s","msg":"$m"}
EOF
  chown www:www "$STATUS" 2>/dev/null || true
}

# VPS->GitHub 偶发 GnuTLS 抖动：fetch 加重试（最多 6 次，单次上限 40s，失败间隔 3s）
OK=0
for attempt in 1 2 3 4 5 6; do
  if timeout 40 sudo -u www git fetch -q --depth=1 origin main 2>/dev/null; then
    OK=1
    break
  fi
  echo "$(date '+%F %T') fetch attempt $attempt failed (GnuTLS/network), retry in 3s"
  sleep 3
done
if [ "$OK" -ne 1 ]; then
  echo "$(date '+%F %T') fetch failed after 6 retries, skip this round"
  write_status fail "fetch failed after 6 retries (GnuTLS/network)"
  exit 0
fi

LOCAL=$(sudo -u www git rev-parse HEAD)
REMOTE=$(sudo -u www git rev-parse origin/main)
if [ "$LOCAL" = "$REMOTE" ]; then
  echo "$(date '+%F %T') already up to date ($LOCAL)"
  write_status ok "already up to date ($LOCAL)"
  exit 0
fi

sudo -u www git reset -q --hard origin/main
echo "$(date '+%F %T') deploy $LOCAL -> $REMOTE"

# 只有代码文件变更才重启（docs/README/CHANGELOG 变更只 pull 不重启）
if sudo -u www git diff --name-only "$LOCAL" HEAD | grep -qvE '^(docs/|README|CHANGELOG)'; then
  systemctl restart tuppy
  sleep 2
  CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8321/login || echo 000)
  if [ "$CODE" = "200" ]; then
    echo "$(date '+%F %T') restart ok, web healthy ($CODE)"
    write_status ok "deployed $LOCAL -> $REMOTE, restart ok"
  else
    echo "$(date '+%F %T') WARN: web not healthy after restart: $CODE"
    write_status ok "deployed $LOCAL -> $REMOTE (WARN web $CODE)"
  fi
else
  echo "$(date '+%F %T') docs-only change, no restart"
  write_status ok "docs-only change, no restart"
fi
