# 多阶段构建:stage1 编译前端 → stage2 Python 运行时(内置前端产物)
# 评审用法见仓库根 docker-compose.yml 与 docker/README.md
# 注意:构建上下文是仓库根(compose 已配 context: . + dockerfile: docker/Dockerfile),
# 故下方 COPY 路径均以仓库根为基准,不要改成相对 docker/ 的路径

# ---------- stage 1: 前端 ----------
FROM node:22-alpine AS web
WORKDIR /build

# 先只拷依赖清单,命中缓存后再拷源码,改代码不必重装依赖
COPY web/package.json web/package-lock.json* ./
RUN npm install

COPY web/ ./
# tsc -b && vite build,产物 /build/dist
RUN npm run build

# ---------- stage 2: 运行时 ----------
FROM python:3.12-slim AS runtime

# antiword: 解析旧版 .doc(parse.py 优先调用,缺失则该格式报错)
# curl: 容器健康检查
RUN apt-get update && apt-get install -y --no-install-recommends \
        antiword curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app/server

# 依赖层:先建出包目录再装,使 pyproject 未变时命中缓存,改源码不重装依赖。
# 不加 `|| true`——依赖装不上必须让构建失败,否则缺包会拖到运行时才暴露。
COPY server/pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py && pip install --no-cache-dir -e .

# 应用源码(editable 安装已就位,覆盖占位包目录即可)
COPY server/app ./app
COPY server/scripts ./scripts

# 初始配置(prompts/schema/agents.yaml 随库提交,data/ 其余部分为运行时数据)
COPY server/data/config ./data/config

# 知识素材:build_kb.py 读 doc/*.txt,reset_demo_data.py 读 doc/pdf/*.pdf
COPY doc/ /app/doc/

# 验收与 SaaS 测试脚本(评审可在容器内直接跑)
COPY tests/ /app/tests/

# 环境变量样例:部署者的配置清单,DEPLOY-2 用例亦按 /app/.env.example 断言
COPY .env.example /app/.env.example

# 前端产物 → main.py 的 WEB_DIST = server/../web/dist
COPY --from=web /build/dist /app/web/dist

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 7000
ENV HOST=0.0.0.0 PORT=7000

# start-period 需覆盖首启初始化:解析 3 份 PDF + 向量化 + 逐章 LLM 抽取,
# 实测约 6—10 分钟(取决于模型响应),期间探测失败不计入 retries。
HEALTHCHECK --interval=15s --timeout=5s --start-period=15m --retries=5 \
    CMD curl -fsS http://127.0.0.1:7000/api/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7000"]
