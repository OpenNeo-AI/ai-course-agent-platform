# 部署说明

目标:验收作品链接 ≥7 天有效。架构为单机:nginx(80)→ uvicorn/FastAPI(127.0.0.1:8000),
前端静态文件由后端直接伺服(web/dist),MCP 端点同域 `/mcp`。

## 远端准备(首次)
1. Linux 服务器,安装 python3.11+、nginx、rsync;
2. 创建 `/opt/opc-edu/.env`(从仓库根 .env 复制,**含密钥,不随 rsync 传输**);
3. 防火墙放行 80 端口。

## 部署
```bash
# 本地:先构建前端并跑通验收
cd web && npm run build
cd ../server && .venv/Scripts/python ../tests/run_acceptance.py

# 一键部署
DEPLOY_HOST=<服务器IP> DEPLOY_USER=<用户> bash deploy/deploy.sh
```

## 验证
- 落地页:`http://<IP>/`,学生 H5 `/s`,教师 H5 `/t`,通用 `/c`
- 健康检查:`curl http://<IP>/api/health`
- MCP:在 OpenClaw/WorkBuddy 中配置 MCP server URL `http://<IP>/mcp`

## 运维
- 日志/状态:`systemctl status opc-edu`、`journalctl -u opc-edu -f`
- 重启:`systemctl restart opc-edu`
- 备份:`/opt/opc-edu/server/data/`(app.db + config + uploads)整体复制即可
