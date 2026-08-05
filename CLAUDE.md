# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 仓库性质

两层身份叠加,改动时都要顾及:

1. **竞赛作品**(已获首届 OPC 软件与智能体开发大赛第一名):AI 课程顾问 Agent。赛题规格 `doc/统一赛题.docx`,知识素材 `doc/学生个人课程资料.docx`(素材A)、`doc/教师个人培训资料.docx`(素材B)、`doc/平台与企业服务资料.docx`(素材C)。
2. **A 级测试单(L3)交付**:在竞赛版之上叠加的多租户 SaaS 平台(`doc/测试单.docx`,提取文本在 `doc/_测试单_text.txt`)。评分维度:RAG 25% / Agent Skill 25% / 商业化支付 15% / Admin 后台 20% / AI 对话 10% / 部署 5%,加分项:真实支付 +3、Docker Compose +2、数据看板 +2、中英双语 +1。

所有资料中的机构/人物/价格均为竞赛模拟数据。公网演示 <https://edu-demo.openneo.ai>。

## 常用命令

后端命令均在 `server/` 目录执行,虚拟环境 `.venv`(Windows 用 `.venv/Scripts/python`)。

```bash
# 安装依赖
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"

# 首次/重建知识库(摄入 doc/*.txt → 切块向量化 → LLM 抽取 ontology,幂等)
.venv/Scripts/python scripts/build_kb.py                    # 完整摄入+抽取+派生链接
.venv/Scripts/python scripts/build_kb.py --no-extract       # 仅切块向量化
.venv/Scripts/python scripts/build_kb.py --kb kb-a          # 仅构建指定知识库
.venv/Scripts/python scripts/build_kb.py --chunks-only-print  # 调试:仅打印切块

# 启动服务(监听 .env 的 HOST/PORT,默认 0.0.0.0:7000;自动挂载 web/dist 与 /mcp)
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 7000
```

### 测试

```bash
# 本体事实回归(须先 build_kb;pytest,可 -k 选单个用例)
.venv/Scripts/python -m pytest ../tests/test_ontology_facts.py -v
.venv/Scripts/python -m pytest ../tests/test_ontology_facts.py -k "price" -v

# 25 组官方验收用例(需服务已启动;报告 → data/acceptance_report.md)
.venv/Scripts/python ../tests/run_acceptance.py

# 17 组 SaaS API 级测试(A级测试单口径,报告 → data/saas_check_report.md + .json)
.venv/Scripts/python ../tests/run_saas_checks.py [BASE_URL]

# RAG 准确率检测(用 demo1 三个智能体实测,报告 → data/rag_accuracy_report.md)
.venv/Scripts/python scripts/rag_accuracy_check.py [BASE_URL]
```

`run_acceptance.py` / `run_saas_checks.py` / `rag_accuracy_check.py` 都是**打真实 HTTP 的黑盒脚本**,不是 pytest,默认 `http://127.0.0.1:7000`,须先起服务。只有 `test_ontology_facts.py` 是 pytest。

### 运维与交付物脚本

```bash
.venv/Scripts/python scripts/reset_demo_data.py       # 重置演示数据(须先停服务)
.venv/Scripts/python scripts/seed_agent_prompts.py    # 补默认提示词/欢迎语(幂等)
.venv/Scripts/python scripts/reextract_all.py         # 强制重抽全部文档 ontology
.venv/Scripts/python scripts/verify_mcp_agents.py     # 校验三个 MCP 端点工具契约
.venv/Scripts/python scripts/gen_test_record_xlsx.py  # 生成 A级测试记录表 xlsx
.venv/Scripts/python scripts/make_pdfs.py             # doc/ 三份 docx → PDF(RAG 演示需要)
.venv/Scripts/python scripts/md2docx.py <in.md> <out.docx>   # 交付文档转 Word(需 Word COM)
.venv/Scripts/python scripts/chat_smoke.py            # 端到端对话冒烟
```

`reset_demo_data.py` 重建的标准演示账号,**密码统一 `demo1234`**:`admin`(平台超管)、`demo1`(旗舰版,3 知识域 + 3 份 PDF + 3 智能体)、`demo2`(标准版)、`demo3`(免费版)。测试脚本依赖 demo1 存在。

### 前端(`web/`)

```bash
npm install && npm run build   # 产物 web/dist,由后端直接伺服
npm run dev                    # 开发模式 :5173,已配 /api 与 /mcp 代理到 :7000
npm run lint                   # oxlint
```

`npm run build` 会先跑 `tsc -b`,类型错误会直接中断构建。

### 部署

```bash
# 部署前必须:构建前端 + 跑验收
cd web && npm run build
cd ../server && .venv/Scripts/python ../tests/run_acceptance.py

DEPLOY_HOST=<IP> DEPLOY_USER=<user> bash deploy/deploy.sh
```

`deploy.sh` 用 **tar-over-ssh 管道**同步代码(Windows git-bash 无 rsync),远端装依赖 → `systemctl restart opc-edu` → nginx + certbot。它会校验 `web/dist` 已构建,否则拒绝部署。远端 `.env` 在 `/opt/opc-edu/.env`,**不随同步传输**,改配置项要单独上传。详见 `deploy/README.md`。

### Docker Compose(评审一键部署路径,与上面的 systemd 部署互不干扰)

```bash
cp .env.example .env      # 至少填 VOLCANO_API_KEY
docker compose up -d      # → http://localhost:7000,首启后台初始化 6—10 分钟
docker compose logs -f    # STATUS 变 healthy 即可用
```

多阶段构建(`node:22-alpine` 编译前端 → `python:3.12-slim` 运行时),单进程 uvicorn 同时伺服 API/SPA/MCP,无 nginx。Docker 相关文件集中在 `docker/`(`Dockerfile`/`entrypoint.sh`/`README.md`),`docker-compose.yml` 与 `.dockerignore` 留在仓库根——前者是一键入口,后者只在构建上下文根生效。首启由 `docker/entrypoint.sh` 建库 → `build_kb.py` 摄入官方三域 → `reset_demo_data.py` 建演示租户,幂等(命名卷 `opc-data` 已初始化则跳过)。改端口 `DOCKER_PORT=8080`,要本体图谱数据加 `DOCKER_FULL_EXTRACT=1`(默认跳过 LLM 抽取以压缩等待)。评审用法详见 `docker/README.md`。

改依赖时注意:`server/pyproject.toml` 的 `mcp` **必须锁 `<2`**(2.0 移除了 `mcp.server.fastmcp`,`app/mcp_server.py` 依赖它);`pyjwt`/`cryptography` 已显式声明,勿依赖间接引入——本地 venv 装得上不代表干净环境装得上。

密钥来自仓库根 `.env`,键位与分组见 `.env.example`(LLM 凭据 / 运行参数 / JWT / 阿里云短信 / 微信支付 / 支付宝)。**`.env` 与 `wink.pem` 严禁提交**。

## 架构要点

### 三层知识,单一 SQLite 文件(`data/app.db`)

- **结构化本体(Palantir 范式)**:8 类对象类型(知识域/班型/营期/地点/师资/费用项/规则/文档)+ 10 类链接类型,Schema 在 `data/config/ontology_schema.yaml`(portal 可维护)。`app/core/ingest/extract.py` 按章 LLM 抽取实体与类型化关系(抽取 Schema `data/config/schemas/extract.json`,提示 `prompts/extract_hints.md`),跨章同名实体深合并;`app/core/ontology/graph.py` 计算派生链接(归属/溯源/前置链/变体/规则适用),链接三分来源 extracted/derived/manual。
- **规则对象化**:早鸟/团报/叠加/退费/前置/推荐策略全部是规则对象,由 `app/core/ontology/engine.py` 通用解释器执行,**代码里零业务数值**。新增优惠或推荐策略应当写库内规则,而不是加分支。
- **身份体系以知识域为唯一单位,无素材 A/B/C 类型**:实体/规则/知识块经 文档→知识库→知识域 链路归属(无 material 列)。推荐逻辑也是库内 `recommend` 规则(声明式 needs/match/日期来源/限额);费用按产品/营期数据推断,无按类型分支。
- **检索库**:`knowledge_chunks` + sqlite-vec `vec0`(向量)+ FTS5 trigram(中文关键词)。
- **多路检索**(`app/core/retrieval/`):query LLM 结构化改写 → 三路并行召回(向量/FTS/本体精确匹配)→ RRF 融合 → rerank → top-k。本体精确命中(价格/日期)直取结构化事实,回答末尾标注文档名+章节。

### 多租户 SaaS 层

23 张表都在 `app/core/db.py` 的 `SCHEMA` 常量里,SaaS 部分:`tenants` `users` `plans` `subscriptions` `usage_monthly` `payment_orders` `sms_codes` `tenant_agents`。迁移函数 `_migrate_saas` / `_migrate_saas_plans` / `_seed_saas` / `_migrate_drop_materials` 在启动时按序执行。

- **归属链**:`tenant → domains → kbs → documents`。任何跨租户查询都必须先解析出 tenant_id 再收敛 kb_ids——`portal.py` 里的 `_tenant_kb_ids(db, tenant_id)` 必须在 `with get_db()` 块**内部**调用,否则拿到已关闭的连接。
- **套餐三档**(`SAAS_PLANS`,元组格式 `(code, name, price, chat_limit, features_json, agent_limit)`):`free` ¥0 / 10 次累计对话 / 1 智能体;`standard` / 无限对话 / 3 智能体;`flagship` / 无限 / 不限。功能门禁是 `features_json` 里的布尔键:`agent_settings`(全档)、`domains` `rag_manage` `ontology` `skills`(standard+)、`agent_caps` `sessions` `leads` `analytics`(flagship 独占)。
- **门禁实现**:`portal.py` 的 `_principal(request)` 从 JWT 或 portal token 解析出超管 / 租户管理员;`_require_active_sub` 校验订阅有效,`_require_feature(db, p, feature, label)` 校验套餐含该布尔键。新增受限功能加一个 feature key,不要硬编码套餐 code 比较。
- **配额**:`tenancy.quota_state` 对免费版用累计次数(`usage_total`)而非月度计数。
- **异步文档摄入**:上传后走 `threading.Thread(target=_background_ingest)` + `_INGEST_LOCK`,用 `get_db_autocommit()` 而非 `get_db()`——解析/向量化/抽取会长时间持写事务,同步执行会 `database is locked`。注册时的入门文档也因此用 `do_extract=False`。
- **认证**:`app/core/auth.py` pbkdf2_sha256 + pyjwt HS256。**pyjwt 要求 `sub` 是字符串**,签发时 `str(user["id"])`、解码后 `int()`。
- **短信**:`app/core/sms.py` 阿里云 Dysmsapi,手写 POP V1.0 HMAC-SHA1 签名(无 SDK),5 分钟有效、60 秒重发、每小时 5 条。未配置时进演示模式,验证码随响应返回。
- **支付**:`app/core/payments.py` 的 `PaymentChannel` 基类 + `MockChannel` / `WechatNativeChannel`(V2 MD5)/ `AlipayPageChannel`(RSA2),注册在 `CHANNELS`。订单生命周期 `create_order` → `pay_success`(幂等)/ `query_order`(前端轮询)/ `pay_by_out_trade_no`(回调)。`create_order` 对渠道**严格校验、不静默回退**。密钥经 `_norm_pem` 处理字面 `\n`,`_load_public_key` 容忍无 PEM 头的裸 base64。

### 知识域与智能体对接

知识域(`domains`)→ 知识库(`kbs`)→ 文档(`documents`)三级;文档支持 .txt/.docx/.doc/.pdf(`app/core/ingest/parse.py`)。官方三通道由 `data/config/agents.yaml` 定义域列表;租户智能体存在 `tenant_agents`(`slug` 唯一,各自 `config_json`),每个有独立前台链接 `/b/<slug>`。`app/core/scope.py` 与 `tenancy.scope_for_agent` 解析作用域,**范围外内容不参与该智能体的 RAG/推荐/计算**。

### 一份工具,三种暴露

`app/core/tools.py` 六个工具(`get_welcome` / `list_products` / `recommend_products` / `ask_knowledge` / `calculate_fee` / `get_enrollment_info` + `set_session_context`)同时服务:

1. `app/agent/loop.py` 会话循环(function calling + 会话状态持久化)
2. `app/mcp_server.py` 三个 MCP server(FastMCP streamable HTTP:`/mcp` 平台、`/mcp/student`、`/mcp/teacher`,各按作用域收敛;stdio 调试 `python -m app.mcp_server stdio [platform|student|teacher]`)
3. REST(`app/api/portal.py` 与 `app/api/saas.py`)

另有两个 A 级测试单要求的 Agent Skill:`get_course_detail`、`recommend_course_type`,自描述元数据(含 JSON Schema)由 `GET /api/skills` 输出供评审查验。Skill 调用失败须降级为 LLM 直答或提示补充参数,不可报错终止。

### 配置即文件

`data/config/llm.yaml`、`prompts/*.md`、`ontology_schema.yaml`、`agents.yaml` 按 mtime 热加载,无需重启。`app/core/config.py` 统一读取,**环境变量(.env)优先于 yaml**。portal 令牌在 `data/config/portal_token.txt`(首次启动生成)。提示词文件:`{role}.md`、`welcome*.md`、`extract.md` + `extract_hints*.md`、`rewrite.md`、`answer.md`、`quality_check.md`、`insight.md`。

**`data/` 整体 gitignored**——首次部署需从服务器备份恢复或跑 `build_kb.py` 初始化;配置文件可经 portal「系统设置」在线编辑。

### 前端

`web/` React + Vite,路由表在 `web/src/main.tsx`:`/`(落地页)、`/s` `/t` `/c`(学生/教师/平台三通道对话)、`/portal`(统一管理工作台)、`/login` `/register`、`/pricing`、`/b/:slug`(租户智能体前台)、`/admin`。SSE 对话事件 `start/tool/delta/done/error`,真流式逐 token。`done` 事件带 `quota` / `quota_exceeded` / `subscription_required`。

`Portal.tsx` 是**按身份自适应的单一工作台**:超管看到 tenants/plans/orders/board/system,租户看到 institution/agents/docs/ontology/sessions/leads/analytics/usage/sub,套餐不含的 tab 显示 `LockPanel` 引导升级。

### i18n(改任何前端文案前必读)

`web/src/i18n.tsx` 自研轻量方案(无 i18next),导出 `I18nProvider` / `useI18n` / `useTData` / `translateData` / `LangSwitch`,语言存 localStorage。

- 界面文案:`DICT` 里加键,组件内 `const { t } = useI18n()` 后用 `{t('key')}`。
- 后端返回的数据文案(套餐名/描述/亮点等):`const td = useTData()` 后 `{td(value)}`,映射表是 `DATA_ZH_EN`。
- **不要在组件里硬编码中文**。此前有大量返工正是因为漏改;新增文案一律走 DICT。
- 模块级常量(如 `LAYOUTS` / `LLM_FIELDS` / `LEAD_STATUS`)不能调 hook,写成**接收 `t` 的函数**再在组件内调用。
- 用户自维护的数据(机构名、知识域内容、提示词)不翻译。
- JSX 里注意 `{t('key')}` 的大括号,以及 `.map(t => ...)` 会遮蔽 i18n 的 `t`(改用别的形参名)。

## 赛题红线(修改任何生成逻辑前必读)

- 不编造事实;资料无实时余位,**不得声称满员/有余位/付款成功/报名完成**。
- 课程回答必须经检索/引擎动态生成;固定模板仅限欢迎语/菜单/重置/错误提示。
- 知识域边界不可混用(由智能体对接配置决定);范围外内容工具不可见。
- 人工服务统一话术「请联系模拟人工课程顾问」;不提供真实联系方式。
- 回答必须带引用(「出自《文档名》章节」)——`loop.py` 有兜底补回逻辑,**勿删**。
- 知识库外的问题要明确说明「该问题不在我的知识范围内」,不得强答。

## 测试约定

- `tests/test_ontology_facts.py`:对各知识域全部已知事实(价格/日期/优惠组合/退费/前置/推荐筛选)做回归断言(按 domain-a/b 取数)。改抽取提示词或引擎后:重跑 `build_kb.py` → 跑本测试;抽取错漏经提示词修正或库内修正后由测试锁死。
- `tests/acceptance_cases.yaml` + `run_acceptance.py`:25 组官方用例(事实8/边界4/推荐5/多轮3/异常5)。断言键:`must`(须含全部词)、`must_not`(不得含词)、`citation`(须含「出自」)、`tools`(须调用过的工具)、`min_len`。新增用例按现有格式追加。
- `tests/run_saas_checks.py`:17 组 API 级测试,分类 RAG≥5 / Skill≥4 / 商业化≥3 / Admin≥3 / 部署≥2,输出 JSON 供测试记录表生成。
