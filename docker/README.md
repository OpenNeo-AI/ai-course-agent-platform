# Docker Compose 一键部署手册

AI 课程顾问 SaaS 平台的容器化部署方案：**一条命令**拉起完整服务（后端 API + 前端 SPA + 三个 MCP 端点），首次启动自动建库、摄入知识素材、创建演示账号。

镜像版本 `opc-edu:1.0.0` — 已通过 17 组 SaaS API 测试与 25 组官方验收用例。

### 文件分布

```
opc-edu/
├── docker-compose.yml     ← 一键入口，在这里执行 docker compose 命令
├── .dockerignore          ← 必须在仓库根（只在构建上下文根目录生效）
└── docker/
    ├── Dockerfile         ← 多阶段构建定义
    ├── entrypoint.sh      ← 首启初始化脚本（建库 → 摄入 → 演示账号）
    └── README.md          ← 本文档
```

**所有命令都在仓库根执行**，不要 `cd docker/`。`docker-compose.yml` 已配 `context: .` + `dockerfile: docker/Dockerfile`，构建上下文是仓库根——Dockerfile 里的 `COPY server/ web/ doc/ tests/` 依赖这一点。

---

## 零、环境准备

### 需要什么

| 项 | 要求 | 验证命令 |
|---|---|---|
| Docker Engine | 20.10+ | `docker version` |
| Docker Compose | v2（`docker compose`，中间是空格不是连字符） | `docker compose version` |
| 磁盘 | 空闲 ≥ 2GB | `df -h .` |
| 网络 | 能访问火山方舟 API（对话与向量化） | 见下方 key 说明 |

Windows / macOS 装 **Docker Desktop** 即同时具备两者。Linux 装 Docker Engine 后需确认 compose 插件存在（`docker-compose-plugin` 包）。

### API Key 是硬前提

服务的 RAG 问答依赖火山方舟的对话模型与 embedding 模型，**没有可用的 key 服务会起不来**（健康检查一直不转 healthy）。key 填在 `.env` 的 `VOLCANO_API_KEY`。

```bash
cp .env.example .env
# 编辑 .env，至少填 VOLCANO_API_KEY
```

`.env.example` 列出了全部可配项（LLM / embedding / 短信 / 微信支付 / 支付宝）及其缺省行为，只有 `VOLCANO_API_KEY` 是必填，其余留空会退化为演示模式（例如短信验证码直接在响应里返回，支付走模拟渠道）。

`.env` **不进镜像层**，运行时经 compose 的 `env_file` 注入 —— 这样同一个镜像可以带不同配置跑，密钥也不会被打进交付物。

---

## 一、部署路径 A：源码构建（推荐）

评委拿到源码仓库后的标准流程，三条命令：

```bash
cd opc-edu
cp .env.example .env && vi .env     # 填 VOLCANO_API_KEY
docker compose up -d
```

`docker compose up -d` 会自动完成构建 → 启动 → 后台初始化。首次构建约 2—4 分钟（拉基础镜像 + 编译前端 + 装 Python 依赖）。

访问 <http://localhost:7000>。改端口：`DOCKER_PORT=8080 docker compose up -d`。

## 二、部署路径 B：导入预构建镜像

若已拿到 `opc-edu-1.0.0-image.tar.gz`（无需构建，也不需要 node/python 环境）：

```bash
# 1) 校验完整性(强烈建议,大文件传输易损坏)
sha256sum opc-edu-1.0.0-image.tar.gz
# 应等于 238e7e16e564ef3a073879f2a4edc272bbe9d964359aa39be61d4f95d590b6a5

# 2) 导入
docker load -i opc-edu-1.0.0-image.tar.gz
docker images opc-edu          # 确认 opc-edu:1.0.0 已存在

# 3) 启动(仍需 .env 与 docker-compose.yml)
cp .env.example .env && vi .env
IMAGE_TAG=1.0.0 docker compose up -d --no-build
```

导入路径同样需要 `docker-compose.yml` 与 `.env`，只是跳过了构建步骤。

---

## 三、启动后的等待

容器进程 1 秒内就绪，但**初始化在后台跑 6—10 分钟**：解析 3 份 PDF → 切块 → 向量化（调用远端 embedding）→ 建演示租户与智能体。健康检查的 `start-period` 设为 15 分钟覆盖这段时间，期间探测失败不计入重试。

看进度：

```bash
docker compose logs -f          # 跟踪初始化日志
docker compose ps               # STATUS 变 healthy 即可用
```

初始化完成的标志是日志出现 `Application startup complete.` 且健康状态为 `healthy`。**在此之前访问页面会显示服务未就绪，属正常现象。**

再次启动（卷已存在）约 20 秒转 healthy —— 入口脚本检测到已初始化会跳过摄入。

---

## 四、部署后验证

四步确认部署成功，逐条都能在评审时当场演示：

```bash
# 1) 健康状态
docker compose ps                       # STATUS 应为 healthy
curl -s http://localhost:7000/api/health

# 2) 前端 SPA 可访问
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:7000/    # 200

# 3) 套餐接口(确认演示数据已就绪)
curl -s http://localhost:7000/api/plans | head -c 200

# 4) 17 组 SaaS API 测试,预期 17/17 通过(详见下方「在容器内跑测试」)
docker exec opc-edu sh -c "cd /app/server && python /app/tests/run_saas_checks.py http://127.0.0.1:7000"
```

浏览器验证：打开 <http://localhost:7000>，用 `demo1 / demo1234` 登录 `/portal`，进入任一智能体的前台链接提问「集训营多少钱」，回答应给出具体价格并在末尾标注「出自《…》章节」。右上角 中/EN 可切换双语界面。

---

## 五、提交给比赛方

### 建议的交付物清单

| 交付物 | 说明 | 必要性 |
|---|---|---|
| 源码仓库 | 含 `docker/`(Dockerfile + entrypoint)与仓库根 `docker-compose.yml` | **必需** |
| 本文档 `docker/README.md` | 一键部署操作说明 | **必需** |
| `.env.example` | 全部环境变量说明（已在仓库根） | **必需** |
| `opc-edu-1.0.0-image.tar.gz` | 预构建镜像（72MB），供不便构建的评委直接导入 | 可选附件 |

**主交付走源码仓库。** 评委执行 `docker compose up -d` 自行构建，比收一个二进制镜像更能验证项目真实性与可复现性，也避免了大文件传输。镜像 tar 作为备选附件，用于评委环境不便构建（无外网拉基础镜像等）的情况。

### 导出镜像文件

若比赛方明确要求提交镜像文件：

```bash
# 打版本标签并导出(gzip 压缩后约 72MB)
docker tag opc-edu:latest opc-edu:1.0.0
docker save opc-edu:1.0.0 | gzip -9 > opc-edu-1.0.0-image.tar.gz

# 生成校验值,随文件一并提交
sha256sum opc-edu-1.0.0-image.tar.gz > opc-edu-1.0.0-image.tar.gz.sha256
```

评委侧用 `docker load -i opc-edu-1.0.0-image.tar.gz` 导入，再按上文「部署路径 B」启动。

**注意：镜像不含 `.env`**（密钥不进交付物）。评委必须自备 `VOLCANO_API_KEY` 才能跑通 RAG 问答；若比赛方不便自备，需在提交说明里单独提供一个测试用 key，或注明该项需现场演示。

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

测试脚本已随镜像发布（`/app/tests`），评审可直接执行：

```bash
# 17 组 SaaS API 级测试(RAG 5 / Skill 4 / 商业化 3 / Admin 3 / 部署 2)
docker exec opc-edu sh -c "cd /app/server && python /app/tests/run_saas_checks.py http://127.0.0.1:7000"

# 25 组官方验收用例(事实 8 / 边界 4 / 推荐 5 / 多轮 3 / 异常 5)
docker exec opc-edu sh -c "cd /app/server && python /app/tests/run_acceptance.py"

# RAG 准确率统计
docker exec opc-edu sh -c "cd /app/server && python scripts/rag_accuracy_check.py http://127.0.0.1:7000"
```

## 镜像构成

多阶段构建：`node:22-alpine` 编译前端 → `python:3.12-slim` 运行时内置前端产物，单进程 uvicorn 同时伺服 API、SPA 与 MCP，无需额外 nginx。系统依赖只装 `antiword`（解析旧版 `.doc`）与 `curl`（健康检查）。

## 故障排查

**端口被占用** — `failed to bind host port 0.0.0.0:7000`：宿主已有服务占用 7000，改用 `DOCKER_PORT=8080 docker compose up -d`。

**启动即退出** — 查 `docker compose logs`。最常见是 `.env` 缺失或 `VOLCANO_API_KEY` 为空。

**一直 unhealthy** — 若超过 15 分钟仍未 healthy，多为 embedding 接口不可达（网络或 key 失效）。`docker compose logs | grep -i error` 可定位。

**想从干净状态复现** — `docker compose down -v && docker compose up -d`。

**`docker-compose` 命令不存在** — 本项目用 Compose **v2** 语法（`docker compose`，空格分隔）。若环境只有 v1 的 `docker-compose`（连字符），请升级 Docker 或安装 `docker-compose-plugin`。

**Linux 下报 permission denied** — 当前用户不在 `docker` 组。`sudo usermod -aG docker $USER` 后重新登录，或所有命令前加 `sudo`。注意用 `sudo` 时环境变量不会传递，`DOCKER_PORT=8080 sudo docker compose up -d` 无效，要写成 `sudo DOCKER_PORT=8080 docker compose up -d`。

**镜像 tar 导入后报格式错误** — 大概率是传输损坏。先核对 SHA256 是否等于 `238e7e16e564ef3a073879f2a4edc272bbe9d964359aa39be61d4f95d590b6a5`，不一致则重新获取文件。

**RAG 问答返回「无法确认」或空回复** — 检查 `VOLCANO_API_KEY` 是否有效、额度是否耗尽：`docker compose logs | grep -i -E "embed|401|403|quota"`。注意智能体回答「无法确认」有时是**正确行为** —— 赛题红线要求资料范围外的问题不得编造，平台服务类问题（素材 C 未提供）就应答无法确认。

---

## 附：与非容器部署的关系

Docker 路径与传统部署（`deploy/deploy.sh` + systemd + nginx）**共用同一套源码与脚本**，`build_kb.py`、`reset_demo_data.py` 在两种环境下行为一致，仅默认值不同：容器内默认跳过 ontology 抽取以压缩评审等待，本地运行默认执行完整抽取。

公网演示环境：<https://edu-demo.openneo.ai>（systemd + nginx 部署，与 Docker 路径互不影响）。
