# Docker Compose 一键部署

AI 课程顾问 SaaS 平台的容器化部署方案：**一条命令**拉起完整服务（后端 API + 前端 SPA + 三个 MCP 端点），首次启动自动建库、摄入知识素材、创建演示账号。

## 前置条件

- Docker Engine 20.10+ 与 Docker Compose v2（`docker compose version` 可验证）
- 仓库根目录存在 `.env`，且至少配置 `VOLCANO_API_KEY`（对话与向量化都要用；参考 `.env.example`）

```bash
cp .env.example .env
# 编辑 .env，填入 VOLCANO_API_KEY
```

`.env` 不进镜像层，运行时经 `env_file` 注入。

## 启动

```bash
docker compose up -d
```

访问 <http://localhost:7000>。改端口：`DOCKER_PORT=8080 docker compose up -d`。

### 首次启动需要等待

容器进程 1 秒内就绪，但**初始化在后台跑 6—10 分钟**：解析 3 份 PDF → 切块 → 向量化（调用远端 embedding）→ 建演示租户与智能体。健康检查的 `start-period` 设为 15 分钟覆盖这段时间，期间探测失败不计入重试。

看进度：

```bash
docker compose logs -f          # 跟踪初始化日志
docker compose ps              # STATUS 变 healthy 即可用
```

初始化完成的标志是日志出现 `Application startup complete.` 且健康状态为 `healthy`。

## 演示账号

| 账号 | 密码 | 身份 | 套餐 |
|---|---|---|---|
| `admin` | `demo1234` | 平台超管 | — |
| `demo1` | `demo1234` | 机构管理员 | 旗舰版（3 智能体 + 3 知识域） |
| `demo2` | `demo1234` | 机构管理员 | 标准版 |
| `demo3` | `demo1234` | 机构管理员 | 免费版（10 次对话） |

登录入口 `/portal`（统一管理工作台，按身份自适应）。官方演示通道 `/s` 学生、`/t` 教师、`/c` 平台。

## 数据持久化

数据库、上传件、报告都落在命名卷 `opc-data`，容器重建不丢数据；再次 `up` 会检测到已初始化并跳过摄入。

```bash
docker compose down            # 停服，保留数据
docker compose down -v         # 停服并删卷(下次启动重新初始化)
docker compose restart         # 重启,秒级完成
```

## 可选：本体图谱数据

默认初始化**跳过** ontology 的 LLM 抽取（耗时数分钟，且 RAG 问答不依赖它）。需要「本体图谱」标签页有实体与关系数据时：

```bash
DOCKER_FULL_EXTRACT=1 docker compose up -d
```

## 在容器内跑测试

测试脚本已随镜像发布，评审可直接执行：

```bash
# 17 组 SaaS API 级测试(RAG 5 / Skill 4 / 商业化 3 / Admin 3 / 部署 2)
docker exec opc-edu sh -c "cd /app/server && python /app/tests/run_saas_checks.py http://127.0.0.1:7000"

# 25 组官方验收用例
docker exec opc-edu sh -c "cd /app/server && python /app/tests/run_acceptance.py"
```

## 镜像构成

多阶段构建：`node:22-alpine` 编译前端 → `python:3.12-slim` 运行时内置前端产物，单进程 uvicorn 同时伺服 API、SPA 与 MCP，无需额外 nginx。系统依赖只装 `antiword`（解析旧版 `.doc`）与 `curl`（健康检查）。

## 故障排查

**端口被占用** — `failed to bind host port 0.0.0.0:7000`：宿主已有服务占用 7000，改用 `DOCKER_PORT=8080 docker compose up -d`。

**启动即退出** — 查 `docker compose logs`。最常见是 `.env` 缺失或 `VOLCANO_API_KEY` 为空。

**一直 unhealthy** — 若超过 15 分钟仍未 healthy，多为 embedding 接口不可达（网络或 key 失效）。`docker compose logs | grep -i error` 可定位。

**想从干净状态复现** — `docker compose down -v && docker compose up -d`。
