#!/bin/sh
# 首次启动自动初始化数据库(幂等):建库 → 摄入知识素材 → 建演示账号。
# data/ 挂载为卷,第二次启动检测到标记文件即跳过,直接起服务。
set -e

DATA_DIR=/app/server/data
FLAG="$DATA_DIR/.docker-seeded"

mkdir -p "$DATA_DIR"

if [ ! -f "$FLAG" ]; then
  echo "──────────────────────────────────────────────"
  echo " 首次启动:初始化数据库与演示数据"
  echo "──────────────────────────────────────────────"

  # 向量化必须有密钥:ingest_text 直接调用 embedding 接口且无降级兜底,
  # 缺密钥会在摄入阶段抛错,导致库只建了表却没有知识块。
  if [ -z "$VOLCANO_API_KEY" ] && [ -z "$ARK_EMBED_KEY" ] && [ -z "$ARK_API_KEY" ]; then
    echo "!! 未检测到 LLM 密钥(VOLCANO_API_KEY / ARK_EMBED_KEY)。"
    echo "!! 将只建表结构,跳过知识库摄入 —— RAG 问答不可用。"
    echo "!! 请在 .env 中配置密钥后删除卷重建:docker compose down -v && docker compose up -d"
    SKIP_INGEST=1
  fi

  cd /app/server

  if [ "$SKIP_INGEST" = "1" ]; then
    # 仅触发建表 + 套餐/超管种子(get_db 连接时执行 SCHEMA 与迁移)
    python -c "from app.core.db import get_db;
with get_db() as d: print('  表结构与套餐种子已就绪')"
  else
    # 本体 LLM 抽取按章调模型,三份 PDF 合计数分钟且非 RAG 必需,
    # 默认跳过以压缩评审等待;需要完整本体图谱时设 DOCKER_FULL_EXTRACT=1。
    # 两个脚本都要一致地跳过,否则 reset_demo_data 仍会全量抽取。
    if [ "$DOCKER_FULL_EXTRACT" = "1" ]; then
      echo "[1/2] 构建官方知识库(解析素材 → 切块 → 向量化 → 本体抽取)…"
      python scripts/build_kb.py
      export DEMO_SKIP_EXTRACT=0
    else
      echo "[1/2] 构建官方知识库(解析素材 → 切块 → 向量化,跳过本体抽取)…"
      python scripts/build_kb.py --no-extract
      export DEMO_SKIP_EXTRACT=1
    fi

    echo "[2/2] 创建演示账号(admin / demo1 / demo2 / demo3,密码 demo1234)…"
    python scripts/reset_demo_data.py
  fi

  touch "$FLAG"
  echo "──────────────────────────────────────────────"
  echo " 初始化完成,启动服务"
  echo "──────────────────────────────────────────────"
else
  echo "检测到已初始化的数据卷,跳过种子步骤。"
fi

cd /app/server
exec "$@"
