# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 仓库性质

「OPC接单吧·首届软件与智能体开发大赛」参赛项目:AI课程顾问Agent。赛题规格见 `doc/统一赛题.docx`,知识素材为 `doc/学生个人课程资料.txt`(素材A)与 `doc/教师个人培训资料.txt`(素材B),素材C(OPC平台白皮书)暂缺。整体规划见 `docs/开发规划.md`。所有资料中的机构/人物/价格均为竞赛模拟数据。

## 常用命令(均在 server/ 目录,虚拟环境 .venv)

```bash
# 安装依赖(Windows git bash)
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"

# 首次/重建知识库(摄入 doc/*.txt → 切块向量化 → LLM 抽取 ontology,幂等)
.venv/Scripts/python scripts/build_kb.py                    # 完整摄入+抽取+派生链接
.venv/Scripts/python scripts/build_kb.py --no-extract       # 仅切块向量化,跳过 ontology 抽取
.venv/Scripts/python scripts/build_kb.py --kb kb-a          # 仅构建指定知识库
.venv/Scripts/python scripts/build_kb.py --chunks-only-print  # 调试:仅打印切块,不写库

# 启动服务(监听 .env 的 HOST/PORT,默认 0.0.0.0:7000;自动挂载 web/dist 与 /mcp)
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 7000

# 测试
.venv/Scripts/python -m pytest ../tests/test_ontology_facts.py -v   # 事实回归(须先 build_kb)
.venv/Scripts/python ../tests/run_acceptance.py                     # 25 组官方验收用例自测

# MCP 本地调试(stdio 模式,直接对接本地宿主)
.venv/Scripts/python -m app.mcp_server stdio [platform|student|teacher]

# 运维脚本
.venv/Scripts/python scripts/reextract_all.py             # 强制重新抽取全部文档的 ontology
.venv/Scripts/python scripts/verify_mcp_agents.py         # 验证三个 MCP 端点的工具契约一致性

# 前端(web/ 目录)
npm install && npm run build      # 产物 web/dist,由后端直接伺服
npm run dev                       # 开发模式(:5173,已配 /api 与 /mcp 代理到 :7000)

# 部署(先置 DEPLOY_HOST/DEPLOY_USER,详见 deploy/README.md)
# 部署前:先构建前端+跑验收,确保通过
cd web && npm run build && cd ../server && ../tests/run_acceptance.py
bash deploy/deploy.sh   # 需 DEPLOY_HOST=<IP> DEPLOY_USER=<user> 环境变量
```

密钥来自仓库根 `.env`(`VOLCANO_API_KEY`/`VOLCANO_BASE_URL`/`VOLCANO_MODEL` 对话;`ARK_EMBED_KEY`/`ARK_EMBED_URL`/`ARK_EMBED_MODEL` 向量化,缺省回退对话配置)。**`.env` 与 `wink.pem` 严禁提交**。

## 架构要点

**三层知识,单一 SQLite 文件(data/app.db)**
- 结构化本体(Palantir 范式):8 类对象类型(知识域/班型/营期/地点/师资/费用项/规则/文档)+ 10 类链接类型,Schema 定义在 `data/config/ontology_schema.yaml`(portal 可维护);`app/core/ingest/extract.py` 按章 LLM 抽取实体与类型化关系(抽取 Schema 在 `data/config/schemas/extract.json`,抽取提示在 `prompts/extract_hints.md`),跨章同名实体深合并;`app/core/ontology/graph.py` 计算派生链接(归属/溯源/前置链/变体/规则适用),链接三分来源 extracted/derived/manual;规则(早鸟/团报/叠加/退费/前置/推荐策略)为规则对象,由 `app/core/ontology/engine.py` 通用解释器执行,**代码零业务数值**。
- **身份体系以知识域为唯一单位,无素材 A/B/C 类型**:实体/规则/知识块经 文档→知识库→知识域 链路归属(无 material 列);推荐逻辑也是库内 `recommend` 规则(声明式 needs/match/日期来源/限额),引擎通用解释,可按知识域在 portal 维护;费用计算按产品/营期数据推断,无按类型分支。
- 检索库:knowledge_chunks + sqlite-vec vec0(向量)+ FTS5 trigram(中文关键词)。
- 多路检索(`app/core/retrieval/`):query LLM 结构化改写 → 三路并行召回(向量/FTS/本体精确匹配)→ RRF 融合 → rerank → top-k;本体精确命中(价格/日期)直取结构化事实,生成回答末尾标注文档名+章节。
- 提示词文件(`data/config/prompts/`,按 mtime 热加载):`{role}.md`(角色系统提示)、`welcome*.md`(欢迎语)、`extract.md`+`extract_hints*.md`(ontology 抽取)、`rewrite.md`(query 改写)、`answer.md`(回答生成)、`quality_check.md`(质检评分)、`insight.md`(运营洞察)。

**知识域与智能体对接**
- 知识域(domains 表)→ 知识库(kbs 表)→ 文档(documents 表)三级结构;文档上传支持 .txt/.docx/.doc/.pdf(`app/core/ingest/parse.py` 解析)。
- `data/config/agents.yaml` 定义每个智能体对接的知识域列表;`app/core/scope.py` 解析作用域,范围外内容不参与该智能体的 RAG/推荐/计算;portal 勾选即时生效。

**一份工具,三种暴露**
`app/core/tools.py` 六个工具(get_welcome/list_products/recommend_products/ask_knowledge/calculate_fee/get_enrollment_info + set_session_context)同时服务于:① `app/agent/loop.py` 会话循环(function calling + 会话状态持久化)② `app/mcp_server.py` 三个 MCP server(FastMCP,streamable HTTP:`/mcp` 平台/机构、`/mcp/student` 学生、`/mcp/teacher` 教师,各自按智能体作用域收敛;stdio 用 `python -m app.mcp_server [stdio] [platform|student|teacher]`)③ REST(portal `/api/*`,令牌鉴权)。

**配置即文件**:`data/config/llm.yaml`、`prompts/*.md`、`ontology_schema.yaml`、`agents.yaml` 按 mtime 热加载,无需重启;`app/core/config.py` 统一读取,环境变量(.env)优先于 yaml。portal 令牌在 `data/config/portal_token.txt`(首次启动生成)。**注意 `data/` 目录整体 gitignored**——首次部署需从服务器备份或运行 `build_kb.py` 初始化;配置文件可通过 portal「系统设置」在线编辑(热生效)。

**前端**:`web/` React+Vite,路由 `/s`(学生)`/t`(教师)`/`c`(平台/机构)`/portal`(管理工作台:知识域管理/智能体设置/本体图谱(cytoscape)/会话记录);SSE 对话(event: start/tool/delta/done/error,真流式逐 token 输出)。

## 赛题红线(修改任何生成逻辑前必读)

- 不编造事实;资料无实时余位,**不得声称满员/有余位/付款成功/报名完成**。
- 课程回答必须经检索/引擎动态生成;固定模板仅限欢迎语/菜单/重置/错误提示。
- 知识域边界不可混用(由智能体对接配置决定:学生域/教师域/平台域);范围外内容工具不可见;平台服务资料(素材C)未提供 → 平台问题答"无法确认"。
- 人工服务统一话术"请联系模拟人工课程顾问";不提供真实联系方式。
- 回答必须带引用("出自《文档名》章节")——loop 中有兜底补回逻辑,勿删。

## 测试约定

- `tests/test_ontology_facts.py`:对各知识域全部已知事实(价格/日期/优惠组合/退费/前置/推荐筛选)做回归断言(按 domain-a/b 取数)。修改抽取提示词或引擎后:重跑 `build_kb.py` → 跑本测试;抽取错漏经提示词修正或库内修正后由测试锁死。
- `tests/acceptance_cases.yaml` + `run_acceptance.py`:25 组官方用例(事实8/边界4/推荐5/多轮3/异常5),报告输出 `data/acceptance_report.md`。断言键:`must`(回复须含全部词)、`must_not`(不得含词)、`citation`(须含"出自"引用)、`tools`(须调用过的工具)、`min_len`(最小回复长度)。新增用例按现有格式追加即可。
