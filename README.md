<p align="center">
  <img src="https://edu-demo.openneo.ai/assets/hero.png" alt="AI 课程顾问" width="600" />
</p>

<h1 align="center">AI 教育顾问 SaaS 平台</h1>

<p align="center">
  <strong>AI Course Advisor · 多租户智能体运营平台</strong><br/>
  结构化本体 RAG · 多路检索引用溯源 · 规则引擎零硬编码 · 真实支付 · 中英双语
</p>

<p align="center">
  <a href="https://edu-demo.openneo.ai/portal"><strong>🚀 立即体验（管理工作台）</strong></a>
  &nbsp;·&nbsp;
  <a href="https://github.com/OpenNeo-AI/ai-course-agent-platform"><strong>⭐ GitHub</strong></a>
</p>

---

## 这是什么

本项目为 **A级测试单（L3）交付**：在首届 OPC 软件与智能体开发大赛第一名作品「AI 课程顾问」基础上，扩展为可按机构授权的多租户 SaaS 平台。教育机构注册后即可拥有自己的 AI 课程顾问智能体，上传课程资料自动构建 RAG 知识库、配置知识域边界、开通套餐后解锁留资/质检/运营分析等能力。

技术内核：课程信息抽取为结构化本体（Ontology），早鸟折扣、团报叠加、退费阶梯、前置要求等业务规则全部对象化存入库内，由通用规则引擎确定性执行，**代码中不包含任何一条业务数值**。回答时三路并行检索（向量语义 + FTS5 中文关键词 + 本体精确匹配），每个结论标注出自哪份文档的哪个章节。

> 🏆 底层竞赛版获首届 OPC 软件与智能体开发大赛第一名，25 组官方验收用例全部通过。

---

## 在线演示

**唯一入口：<https://edu-demo.openneo.ai/portal>**

> 登录后按身份自适应：超管看到租户/套餐/订单/看板，租户管理员看到自己的机构与智能体。各智能体的独立前台对话链接在「智能体设置」中获取。

**演示账号（密码均 `demo1234`）**

| 账号 | 角色 | 套餐 | 说明 |
|------|------|------|------|
| `admin` | 平台超管 | -- | 租户管理 / 套餐定价 / 订单 / 数据看板 |
| `demo1` | 租户管理员 | 旗舰版 | 3 知识域 + 3 智能体，全部能力开放 |
| `demo2` | 租户管理员 | 标准版 | 最多 3 智能体，知识域/RAG/本体/Skill |
| `demo3` | 租户管理员 | 免费版 | 1 智能体，累计 10 次对话，功能锁定 |

---

## A级测试单交付

评分维度：RAG 25% / Agent Skill 25% / 商业化支付 15% / Admin 后台 20% / AI 对话 10% / 部署 5%。加分项：真实支付 +3、Docker Compose +2、数据看板 +2、中英双语 +1。

### ① RAG 知识问答（25%）

文档（.pdf/.docx/.doc/.txt）上传后经后台异步线程解析 → 按章节可配置切块（`CHUNK_SIZE`/`CHUNK_OVERLAP`）→ 火山方舟 Embedding 向量化，写入 `knowledge_chunks` + FTS5(trigram) + vec0 向量表。查询时 LLM 结构化改写 → 三路并行召回（向量 KNN / FTS5 关键词 / 本体精确事实）→ RRF 融合 → rerank → top-k 生成。

- 回答强制附 `出自《文档名》·章节` 结构化引用，前端以卡片渲染
- 本体精确命中（价格/日期/营期）直取结构化事实，杜绝数字幻觉
- 知识库外问题明确答「不在知识范围内」，不编造
- sqlite-vec 不可用时向量路降级，主流程由 FTS5 + 本体支撑
- 无素材 A/B/C 概念：身份体系以**知识域**为唯一单位，智能体在配置中声明对接哪些域，范围外不可见

<p align="center">
  <img src="pics/学生咨询.png" alt="RAG 带引用问答" width="700" />
</p>

### ② Agent Skill（25%）

两个 A 级测试单要求的 Agent Skill，自描述元数据（含 JSON Schema）由 `GET /api/skills` 输出供评审查验：

| Skill | 参数 | 返回 |
|---|---|---|
| `get_course_detail` 查询课程详情 | `product_name: string`（必填） | 时间/地点/费用/师资/大纲 + 适用优惠规则 + 引用 |
| `recommend_course_type` 推荐适合班型 | `city: string`、`time_preference: string` | 最匹配 1-2 个班型 + 理由 + 引用 |

另有 6 个基础工具（`get_welcome`/`list_products`/`recommend_products`/`ask_knowledge`/`calculate_fee`/`get_enrollment_info`）+ `set_session_context` 会话上下文 + `capture_lead` 留资工具。**一份实现，三种暴露**：Agent 会话循环（function-calling 真流式 SSE）/ MCP server（3 个 streamable HTTP 端点 + stdio）/ REST（`POST /api/tool`）。

降级策略：缺参返回 `need` 追问、实体不存在返回 `available` 列表、模型异常固定文案，Skill 调用失败降级为 LLM 直答，不报错终止。

### ③ 商业化支付（15%，加分项真实支付 +3）

渠道注册表 `payments.CHANNELS`（`PaymentChannel` 基类），三种渠道：

| 渠道 | 实现 | 下单返回 |
|------|------|----------|
| 模拟支付 | `MockChannel`，确认即成功（演示标注不扣款） | 确认按钮 |
| 微信 Native 扫码 | V2 API，MD5 签名，XML，回调验签 | `code_url` 二维码 |
| 支付宝电脑网站 | `alipay.trade.page.pay`，RSA2 签名 | `pay_url` 跳转 |

流程：选套餐 → 创建订单（`out_trade_no` 商户单号）→ 渠道支付 → 前端 2s 轮询查单 / 渠道异步回调验签 → 订单幂等置 paid → 订阅升级、功能解锁。`create_order` 对渠道严格校验，不静默回退；密钥经 `.env` 注入，PEM 字面 `\n` 自动归一化。

<p align="center">
  <img src="pics/测试单-套餐订阅.png" alt="套餐订阅与订单记录" width="440" />
  <img src="pics/测试单-支付.png" alt="支付渠道选择" width="440" />
</p>
<p align="center">
  <img src="pics/测试单-支付扫码.png" alt="微信扫码支付" width="440" />
  <img src="pics/测试单-支付宝扫码.png" alt="支付宝电脑网站支付" width="440" />
</p>
<p align="center">
  <img src="pics/测试单-支付成功.png" alt="支付成功·订阅升级" width="440" />
</p>

**套餐三档**（价格为演示数据，可在后台在线调整）：

| 套餐 | 月费 | 智能体数 | 对话 | 功能 |
|------|------|----------|------|------|
| 免费版 | ¥0 | 1 | 累计 10 次 | 智能体设置 |
| 标准版 | ¥10/月 | 3 | 无限 | + 知识域管理 / RAG / 本体 / Agent Skill |
| 旗舰版 | ¥20/月 | 不限 | 无限 | + 能力开关 / 对话记录 / 线索转化 / 运营分析 |

注册即开通免费版；配额超额在 `done` 事件回传 `quota_exceeded` 引导升级。功能门禁按 `features_json` 布尔键校验，不硬编码套餐 code 比较。

### ④ Admin 后台（20%，加分项数据看板 +2）

`Portal.tsx` 是按身份自适应的单一工作台：超管经营视图 vs 租户运营视图，套餐不含的 tab 显示 `LockPanel` 引导升级。后端 49 个 `/api/portal/*` 端点 + `/api/tenant/*` + `/api/billing/*`。

**平台超管经营视图：**

- **租户管理**：机构租户列表（套餐/用户数/会话数/累计用量/开通时间）
- **套餐定价**：三档价格、对话限额、功能位在线维护，保存即生效
- **订单管理**：全平台支付流水（订单号/租户/套餐/渠道/金额/状态/时间），支持按状态筛选
- **租户看板**：租户数/用户数/会话数/对话数总量 + 近 14 日会话趋势 + 租户对话排行

<p align="center">
  <img src="pics/测试单-租户管理.png" alt="租户管理" width="440" />
  <img src="pics/测试单-定价维护.png" alt="套餐定价维护" width="440" />
</p>
<p align="center">
  <img src="pics/测试单-订单.png" alt="订单管理" width="440" />
  <img src="pics/测试单-数据看板.png" alt="租户数据看板" width="440" />
</p>

**租户管理员运营视图：** 机构信息（含统一服务宗旨注入提示词）/ 智能体设置（模型·能力开关·知识域挂载·系统提示词，每个智能体独立前台链接 `/b/<slug>`）/ 知识域与课程资料（上传即异步解析切块向量化）/ 本体图谱（8 类对象 10 类链接可视化、7 种布局、在线编辑审计）/ 对话记录（脱敏·时间筛选·质检）/ 线索转化工单 / 运营分析（高频问题·未答问题·推荐分布·LLM 洞察）/ 用量统计 / 套餐订阅。

<p align="center">
  <img src="pics/测试单-知识域.png" alt="知识域与课程资料" width="330" />
  <img src="pics/测试单-本体知识.png" alt="本体图谱" width="330" />
  <img src="pics/测试单-对话记录.png" alt="对话记录（脱敏）" width="330" />
</p>
<p align="center">
  <img src="pics/测试单-运营分析.png" alt="运营分析" width="330" />
  <img src="pics/测试单-用量统计.png" alt="用量统计" width="330" />
  <img src="pics/测试单-线索转换.png" alt="线索转化工单" width="330" />
</p>
<p align="center">
  <img src="pics/测试单-机构信息.png" alt="机构信息与统一服务宗旨" width="500" />
</p>

**认证：** 支持手机验证码登录、账户密码登录、机构注册开通（机构名称 + 账户名 + 密码 + 手机号 + 短信验证码，阿里云 Dysmsapi，未配置时进演示模式验证码随响应返回），注册即开通免费版。

<p align="center">
  <img src="pics/测试单-登录1.png" alt="验证码登录" width="320" />
  <img src="pics/测试单-登录2.png" alt="密码登录" width="320" />
  <img src="pics/测试单-注册.png" alt="机构注册开通" width="320" />
</p>

### ⑤ AI 对话（10%）

SSE 真流式逐 token 输出，事件流 `start → tool(工具进度) → delta(回复分片) → done(引用/配额)`。Agent 会话循环按智能体能力动态装配工具（`lead_capture` 开启则纳入留资工具，`tenant_bot` 开启则追加两个 Agent Skill），`MAX_TOOL_ROUNDS` 限制工具轮数，会话状态持久化到 `sessions.state_json` 支持多轮继承。

租户智能体前台 `/b/<slug>` 对话，回答带「引用出处」卡片（文档名+章节+原文语句）；用户表达报名意向时 `capture_lead` 工具采集姓名/联系方式/意向班型，写入 `leads` 工单转人工跟进。对话质检（旗舰版能力）由 LLM 三维评分（准确性/规范性/体验）+ 红线检测，支持单条与批量。

<p align="center">
  <img src="pics/测试单-智能体对话.png" alt="租户智能体前台对话（富文本表格回答）" width="400" />
  <img src="pics/测试单-线索跟进.png" alt="引用出处卡片 + 留资转人工" width="400" />
</p>

### ⑥ 部署（5%，加分项 Docker Compose +2）

**Docker Compose 一键部署（评审路径）**：多阶段构建（`node:22-alpine` 编译前端 → `python:3.12-slim` 运行时），单进程 uvicorn 同时伺服 API/SPA/MCP，无 nginx 依赖。首启由 `docker/entrypoint.sh` 幂等初始化：建库 → 摄入官方三知识域 → 建演示账号，命名卷 `opc-data` 已初始化则跳过。

```bash
cp .env.example .env            # 至少填 VOLCANO_API_KEY
docker compose up -d            # -> http://localhost:7000，首启约 6-10 分钟
docker compose logs -f          # STATUS 变 healthy 即可用
```

生产路径：单机 nginx → uvicorn/systemd + Let's Encrypt，`deploy/deploy.sh` 以 tar-over-ssh 同步代码并自动重启。两条路径互不干扰。

### 加分项汇总

| 加分项 | 分值 | 实现 |
|--------|------|------|
| 真实支付 | +3 | 微信 Native（V2 MD5）+ 支付宝电脑网站（RSA2），回调验签幂等；Mock 渠道用于演示 |
| Docker Compose | +2 | 多阶段镜像 + 首启自动初始化，`docker compose up -d` 一键 |
| 数据看板 | +2 | 平台经营看板（总量/趋势/排行）+ 运营分析（高频/未答/推荐分布/质检均分/LLM 洞察） |
| 中英双语 | +1 | 自研轻量 i18n（`web/src/i18n.tsx`），界面文案与后端数据文案全组件覆盖，一键切换 |

<p align="center">
  <img src="pics/测试单-英文.png" alt="中英双语·智能体设置" width="440" />
  <img src="pics/测试单-英文2.png" alt="中英双语·数据看板" width="440" />
</p>

---

## 架构总览

```
   web/ (React 19 + Vite 8 · 移动优先 H5 · 自研 i18n 中英双语)
   ├─ /portal (按身份自适应工作台)  · /b/<slug> (租户智能体前台)
   └─ /login /register /pricing    · 三通道对话 /s /t /c

                │ REST + SSE (真流式 function-calling)
                ▼
   server/ (FastAPI 单服务)
   ├─ api/saas.py      auth/billing/tenant/skills/usage
   ├─ api/portal.py    49 个管理后台端点 (知识域/本体/智能体/质检/工单/分析/订单/渠道)
   ├─ /mcp · /mcp/student · /mcp/teacher  (MCP streamable HTTP · Bearer 渠道令牌)
   └─ core/ (所有实现共享)
       ├─ ingest/      文档解析 → 切块 → 向量化 → LLM 本体抽取
       ├─ ontology/    8 类对象 + 10 类链接 + 通用规则引擎 (零业务数值)
       ├─ retrieval/   query 改写 → 三路召回 → RRF 融合 → rerank
       ├─ tools.py     6 基础工具 + 2 Skill + 留资 (Agent/MCP/REST 共用)
       ├─ payments.py  Mock / 微信 Native / 支付宝 渠道注册表
       ├─ tenancy.py   多租户/套餐/配额/订阅/作用域
       ├─ quality.py   对话质检 (LLM 三维评分 + 红线)
       └─ llm.py       火山方舟 OpenAI 兼容客户端 (对话/embedding/rerank)

                │
   data/ (SQLite 单文件, WAL)
   ├─ domains · kbs · documents (知识域三级结构)
   ├─ entities · relations · edges · rules (本体 + 规则对象化)
   ├─ knowledge_chunks + vec0 (向量) + FTS5 trigram (全文)
   ├─ sessions · messages · quality_checks · leads · insights (会话 + 运营)
   └─ tenants · users · plans · subscriptions · usage_monthly · payment_orders · sms_codes · tenant_agents · channel_tokens (SaaS)
```

**技术选型：** Python 3.11+ · FastAPI · MCP Python SDK · SQLite + sqlite-vec + FTS5 · React 19 + Vite 8 + TypeScript + Cytoscape · 豆包 seed 系列（对话/embedding/rerank）· Docker Compose。

---

## 快速开始

### Docker Compose（推荐）

```bash
cp .env.example .env            # 至少填 VOLCANO_API_KEY
docker compose up -d            # -> http://localhost:7000
docker compose logs -f          # 等待 healthy
```

演示账号 `admin` / `demo1` / `demo2` / `demo3`（密码 `demo1234`）。详见 [`docker/README.md`](docker/README.md)。

### 本地开发

```bash
# 后端
cd server
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/python scripts/build_kb.py                       # 摄入+抽取本体
.venv/Scripts/python -m uvicorn app.main:app --port 7000

# 前端（另开终端）
cd web && npm install && npm run dev                           # :5173 代理到 :7000
```

### 测试

```bash
cd server
.venv/Scripts/python -m pytest ../tests/test_ontology_facts.py -v  # 20 项事实回归
.venv/Scripts/python ../tests/run_acceptance.py                    # 25 组官方验收
.venv/Scripts/python ../tests/run_saas_checks.py                   # 17 组 SaaS API（A级口径）
.venv/Scripts/python scripts/rag_accuracy_check.py                # RAG 准确率
```

---

## MCP 接入

三个独立 MCP 端点按智能体知识域收敛：`/mcp/student`（学生课程域）、`/mcp/teacher`（教师培训域）、`/mcp`（全知识域含身份分流）。stdio 调试：`python -m app.mcp_server stdio [platform|student|teacher]`。

渠道令牌鉴权（Bearer）：管理后台签发 `ak_` 前缀令牌后，MCP 连接须携带 `Authorization: Bearer ak_…`；系统尚无任何令牌时保持开放向后兼容。

工具清单：`get_welcome` · `list_products` · `recommend_products` · `ask_knowledge` · `calculate_fee` · `get_enrollment_info` · `capture_lead` + 两个 Agent Skill。

---

## 项目结构

```
├── server/
│   ├── app/
│   │   ├── main.py              # FastAPI 主服务 + SSE + MCP 挂载 + SPA
│   │   ├── mcp_server.py        # MCP streamable HTTP / stdio (3 端点)
│   │   ├── agent/loop.py        # Agent 会话循环 (function calling)
│   │   ├── api/portal.py        # 管理后台 REST (49 端点)
│   │   ├── api/saas.py          # auth/billing/tenant/skills
│   │   └── core/                # ingest/ontology/retrieval/tools/payments/tenancy/quality/llm/db
│   ├── data/config/             # YAML 配置 + Markdown 提示词 (热加载)
│   └── scripts/                 # build_kb · reset_demo_data · rag_accuracy · 测试
├── web/src/                     # React + Vite · 三通道 + Portal + i18n
├── tests/                       # 事实回归 + 25 验收 + 17 SaaS 检查
├── docker/                      # Docker Compose (Dockerfile + entrypoint)
├── deploy/                      # nginx + systemd + deploy.sh
└── doc/ · docs/                 # 竞赛素材 · 交付文档
```

---

## 设计约束（赛题红线）

- 不编造事实；无实时余位，**绝不声称满员/余位/付款成功/报名完成**
- 课程回答必须经检索/引擎生成；固定模板仅限欢迎语/菜单/重置/错误提示
- 知识域边界不可混用；范围外内容工具不可见
- 人工服务统一话术「请联系模拟人工课程顾问」，不提供真实联系方式
- 回答必须带引用——loop 中有兜底补回逻辑，不可删除
- 知识库外问题明确说明「不在知识范围内」

---

## 许可证

MIT License

---

<p align="center">
  <sub>🤖 Built with Claude Code · Volcengine Ark (Doubao) · FastAPI · React · SQLite · Docker</sub>
</p>
