#!/usr/bin/env bash
# 一键部署:本地仓库根目录执行 → 同步代码 → 远端装依赖 → 重启服务 → nginx + 证书
# 用法:DEPLOY_HOST=3.39.24.74 DEPLOY_USER=ubuntu bash deploy/deploy.sh
# 首次部署会把本地 .env 与 server/data/app.db 上传到远端(密钥经 SSH 加密传输,不落仓库)。
set -euo pipefail

HOST="${DEPLOY_HOST:?请设置 DEPLOY_HOST}"
USER_NAME="${DEPLOY_USER:-ubuntu}"
DOMAIN="${DEPLOY_DOMAIN:-edu-demo.openneo.ai}"
KEY="$(cd "$(dirname "$0")/.." && pwd)/wink.pem"
REMOTE="/opt/opc-edu"
SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new"

chmod 600 "$KEY"

# ---- 部署前验证 ----
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# 1) 前端 dist 存在且包含出处卡片核心代码
DIST_JS=("$REPO_ROOT"/web/dist/assets/index-*.js)
if [ ! -f "${DIST_JS[0]}" ] || ! grep -q "引用出处" "${DIST_JS[0]}" 2>/dev/null; then
  echo "❌ 前端未构建或缺少出处卡片代码。请先执行: cd web && npm run build"
  echo "   然后确认 dist/assets/index-*.js 包含「引用出处」。"
  exit 1
fi
echo "✓ 前端构建验证通过(CiteCard 代码存在)"

# 2) 验收用例(若 server/.venv 存在且 Python 可用)
if [ -x "$REPO_ROOT/server/.venv/Scripts/python" ] || [ -x "$REPO_ROOT/server/.venv/bin/python" ]; then
  PY=""
  for p in "$REPO_ROOT/server/.venv/Scripts/python" "$REPO_ROOT/server/.venv/bin/python"; do
    [ -x "$p" ] && PY="$p" && break
  done
  if [ -n "$PY" ] && [ -f "$REPO_ROOT/tests/run_acceptance.py" ]; then
    echo "→ 运行验收用例..."
    "$PY" "$REPO_ROOT/tests/run_acceptance.py" || echo "[warn] 验收用例未全部通过,继续部署"
  fi
fi

# 远端目录准备(首次)
$SSH "$USER_NAME@$HOST" "sudo mkdir -p $REMOTE && sudo chown \$USER:\$USER $REMOTE && mkdir -p $REMOTE/server/data"

# 凭据:远端无 .env 时上传本地 .env
$SSH "$USER_NAME@$HOST" "[ -f $REMOTE/.env ]" || scp -i "$KEY" .env "$USER_NAME@$HOST:$REMOTE/.env"

# 代码同步(tar-over-ssh 管道,无需本地 rsync;排除项与旧 rsync 一致)
tar -czf - \
  --exclude='.venv' --exclude='node_modules' \
  --exclude='server/data/app.db' --exclude='server/data/uploads' \
  --exclude='server/data/reports' \
  --exclude='.env' --exclude='wink.pem' --exclude='__pycache__' --exclude='.git' \
  ./ | $SSH "$USER_NAME@$HOST" "mkdir -p $REMOTE && tar -xzf - -C $REMOTE"

# 知识库:远端无 app.db 时上传本地构建好的库,否则远端自行构建
$SSH "$USER_NAME@$HOST" "[ -f $REMOTE/server/data/app.db ]" \
  || scp -i "$KEY" server/data/app.db "$USER_NAME@$HOST:$REMOTE/server/data/app.db"

$SSH "$USER_NAME@$HOST" bash -s <<EOF
set -e
cd $REMOTE/server
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e .
if [ ! -f data/app.db ]; then .venv/bin/python scripts/build_kb.py; fi
sudo cp ../deploy/opc-edu.service /etc/systemd/system/
sudo cp ../deploy/nginx-opc-edu.conf /etc/nginx/conf.d/opc-edu.conf
sudo systemctl daemon-reload
sudo systemctl enable --now opc-edu.service
sudo systemctl restart opc-edu.service
sleep 2
sudo nginx -t && sudo systemctl reload nginx
# 证书:域名已解析到本机时自动签发;失败仅告警,不阻断
sudo certbot --nginx -d $DOMAIN --non-interactive --agree-tos --register-unsafely-without-email --redirect \
  || echo "[warn] certbot 签发失败(检查域名解析/80端口可达性),当前仅 HTTP 可用"
echo "--- health ---"
curl -s http://127.0.0.1:7000/api/health
EOF
echo ""
echo "部署完成:https://$DOMAIN/"
