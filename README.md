# SteamAnalysis

> v0.2.0 — 面向游戏行业的 LLM Agent 研究分析工作台

SteamAnalysis 是一个面向游戏公司、发行团队和游戏投资分析场景的本地优先数据分析 Agent。项目当前以 Steam 公开数据为核心数据源，结合本地 SQLite 快照、评论抽样分析、RAG 知识库、监控配置、报告导出和可追踪 Agent 工作流，帮助用户围绕游戏热度、价格、评论、趋势和资料证据做初步决策。

项目不会登录 Steam，不读取私有账户数据，也不会代替真实投研结论。它更像一个可扩展的游戏投研工作台：先把公开数据、用户导入资料和 Agent 编排跑通，再逐步接入网页舆情、多源搜索、竞品雷达和评估闭环。

---

## 当前能力

- **Steam 游戏搜索** — Steam 搜索结果和本地中文别名库混合解析
- **游戏公开数据采集** — 采集游戏详情、在线人数、价格、折扣、新闻和来源 URL，保存为本地快照
- **历史趋势分析** — 基于本地快照分析在线人数变化、峰值、均值和价格变化
- **快照对比** — 支持通过 `appid`、`snapshot_id` 或标签对比两个时间点或两个游戏
- **评论抽样分析** — LLM 驱动话题提取 + 关键词 fallback，计算样本好评率，提取正负向关键词
- **网页舆情分析** — 搜索→抓取→LLM 声明提取→情感评分全流程
- **RAG 知识库** — 文档导入、智能分块、FTS5+向量混合检索、Cross-Encoder 精排
- **Agent 聊天** — SSE 流式、任务分类、多轮记忆、工具调用、结构化输出
- **监控调度器** — 后台定时采集 + 自动告警（人数暴涨跌、折扣变化、新史低）
- **报告导出** — Markdown 和 JSON 导出
- **前端工作台** — Dashboard、游戏详情、对比、聊天、设置 5 个页面
- **企业基础设施** — Docker 容器化、结构化日志、Prometheus Metrics、Alembic 迁移、LLM 供应商抽象、熔断器

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn (Python 3.12+) |
| ORM + 迁移 | SQLModel + Alembic |
| 数据库 | SQLite (FTS5 全文搜索 + sqlite-vec 向量搜索) |
| LLM Agent | LangChain (DeepSeek / OpenAI 可切换) |
| 嵌入 | Provider 模式 (hash / openai / deepseek) |
| HTTP | httpx + tenacity 重试 + 熔断器 |
| 定时任务 | APScheduler |
| 前端 | Vue 3 + TypeScript + Vite |
| 状态管理 | Pinia |
| 图表 | ECharts + vue-echarts |
| CSS | Tailwind CSS v4 |
| 部署 | Docker + docker-compose + nginx |

---

## 快速开始

### Docker 一键启动（推荐）

```bash
# 1. 配置环境变量
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入 API keys

# 2. 启动
docker-compose up -d

# 3. 访问
# 前端: http://localhost:8080
# API 文档: http://localhost:9000/docs
# Metrics: http://localhost:9000/api/metrics
```

### 本地开发启动

**后端:**
```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -e ".[test]"
cp .env.example .env  # 填入 API keys
.venv/Scripts/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 9000
```

**前端:**
```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev  # http://localhost:3173
```

---

## 目录结构

```
Steamgame-analysis-agent-item/
│
├── README.md                         # 项目说明（本文件）
├── PROJECT_FEATURES.md               # 完整功能文档
├── .gitignore                        # Git 忽略规则
├── .dockerignore                     # Docker 构建忽略规则
│
├── Dockerfile.backend                # 后端 Docker 镜像（Python 3.12-slim）
├── Dockerfile.frontend               # 前端 Docker 镜像（Node 20 + nginx）
├── docker-compose.yml                # 服务编排（backend + frontend）
├── nginx.conf                        # nginx 反向代理 + 静态文件配置
│
├── ai-note/                          # AI 讨论与学习笔记
│   ├── 01-project-understanding.md   #   项目理解笔记
│   ├── 02-upgrade-discussion.md      #   升级讨论记录
│   ├── 03-llm-abstraction-notes.md   #   LLM 抽象层设计笔记
│   ├── 04-embedding-upgrade-notes.md #   嵌入服务升级笔记
│   └── 05-enterprise-architecture.md #   企业级架构决策记录
│
├── docs/                             # 项目文档
│   └── steamanalysis-project-feature-details.md  #   详细功能说明 + 评估指标
│
├── backend/                          # 后端 (FastAPI)
│   ├── .env.example                  #   环境变量模板
│   ├── pyproject.toml                #   项目元数据 + 依赖声明
│   ├── alembic.ini                   #   Alembic 迁移配置
│   │
│   ├── alembic/                      #   数据库迁移
│   │   ├── env.py                    #     迁移环境（SQLModel metadata）
│   │   ├── script.py.mako            #     迁移脚本模板
│   │   └── versions/                 #     迁移版本文件
│   │
│   └── app/                          #   应用代码
│       ├── main.py                   #     FastAPI 入口 + 中间件 + lifespan
│       │
│       ├── agent/                    #     Agent 系统
│       │   ├── core.py               #       SteamAnalysisAgent 门面
│       │   ├── runtime.py            #       AgentRuntime 中央编排引擎
│       │   ├── task_classifier.py    #       任务分类器（关键词 + LLM 混合）
│       │   ├── tools.py              #       工具注册表 + 执行器
│       │   ├── prompts.py            #       LLM 提示词模板
│       │   ├── memory.py             #       对话记忆管理
│       │   └── validators.py         #       结果校验器（证据/时效/风险）
│       │
│       ├── api/                      #     API 路由层
│       │   └── routes/
│       │       ├── chat.py           #       Agent 聊天 + SSE 流式
│       │       ├── games.py          #       游戏搜索 + 详情 + 价格对比 + 趋势
│       │       ├── snapshots.py      #       快照采集 + 标签
│       │       ├── compare.py        #       快照 A/B 对比
│       │       ├── reviews.py        #       评论分析（LLM + 关键词）
│       │       ├── web_sentiment.py  #       网页舆情分析
│       │       ├── knowledge.py      #       知识库 CRUD + RAG 检索
│       │       ├── monitors.py       #       监控任务 + 告警
│       │       ├── reports.py        #       分析报告列表
│       │       ├── exports.py        #       报告导出（Markdown/JSON）
│       │       ├── settings.py       #       应用设置
│       │       └── aliases.py        #       游戏别名管理
│       │
│       ├── core/                     #     核心基础设施
│       │   ├── config.py             #       Pydantic Settings + 启动校验
│       │   ├── security.py           #       密钥管理
│       │   ├── logging.py            #       结构化日志 + Request ID
│       │   ├── middleware.py         #       安全中间件栈
│       │   └── metrics.py            #       Prometheus 指标
│       │
│       ├── llm/                      #     LLM 供应商抽象层
│       │   ├── __init__.py           #       公开 API
│       │   └── factory.py            #       工厂函数（deepseek/openai）
│       │
│       ├── db/                       #     数据层
│       │   ├── models.py             #       16 张 SQLModel 表定义
│       │   └── session.py            #       引擎 + 会话 + 迁移初始化
│       │
│       ├── schemas/                  #     Pydantic 请求/响应模型
│       │   ├── common.py             #       JSON 序列化工具
│       │   ├── chat.py               #       Agent 聊天模型
│       │   ├── game.py               #       游戏 + 价格 + 新闻模型
│       │   ├── snapshot.py           #       快照 + 趋势 + 标签模型
│       │   ├── compare.py            #       对比请求/响应模型
│       │   ├── review.py             #       评论 + 情感分析模型
│       │   ├── report.py             #       报告模型
│       │   ├── knowledge.py          #       知识库模型
│       │   ├── web_sentiment.py      #       舆情模型
│       │   ├── monitor.py            #       监控模型
│       │   └── settings.py           #       设置模型
│       │
│       └── services/                 #     业务逻辑层
│           ├── steam_client.py       #       Steam API 客户端（缓存 + 熔断器）
│           ├── snapshot_service.py   #       快照采集 + 趋势分析
│           ├── comparison_service.py #       快照 A/B 对比
│           ├── review_service.py     #       评论分析（LLM + 关键词双模式）
│           ├── web_sentiment_service.py  #   网页舆情全流程
│           ├── knowledge_service.py  #       RAG 知识库（语义嵌入 + Cross-Encoder）
│           ├── embedding_service.py  #       嵌入 Provider（hash/openai/deepseek）
│           ├── scheduler_service.py  #       监控调度器 + 告警规则
│           ├── export_service.py     #       报告导出
│           ├── report_service.py     #       报告 CRUD
│           ├── monitor_service.py    #       监控任务 CRUD
│           ├── game_alias_service.py #       别名管理 + 种子数据
│           ├── settings_service.py   #       设置读写
│           └── knowledge_service.py  #       RAG 全链路 + 混合检索
│
└── frontend/                         # 前端 (Vue 3 + TypeScript)
    ├── .env.example                  #   环境变量模板
    ├── package.json                  #   依赖 + 脚本
    ├── vite.config.ts                #   Vite 构建配置
    ├── index.html                    #   HTML 入口
    │
    └── src/
        ├── main.ts                   #   应用入口 + ECharts 注册
        ├── App.vue                   #   根组件
        ├── styles.css                #   全局样式 + Tailwind + CSS 变量
        │
        ├── api/
        │   ├── client.ts             #     API 客户端（30+ 端点函数 + SSE 流式）
        │   └── types.ts              #     TypeScript 类型定义（30+ 接口）
        │
        ├── router/
        │   └── index.ts              #     Vue Router 配置（5 条路由）
        │
        ├── stores/
        │   ├── settings.ts           #     全局设置 Store
        │   └── workspace.ts          #     收藏 + 报告 Store
        │
        ├── utils/
        │   └── format.ts             #     数字/货币/日期格式化
        │
        ├── views/                    #   页面组件
        │   ├── DashboardView.vue     #     工作台主页
        │   ├── GameDetailView.vue    #     游戏详情页
        │   ├── CompareView.vue       #     快照对比页
        │   ├── ChatView.vue          #     Agent 聊天页
        │   └── SettingsView.vue      #     设置页
        │
        └── components/               #   通用组件
            ├── AppShell.vue          #     全局布局外壳
            ├── MetricCard.vue        #     关键指标卡片
            ├── MarkdownRenderer.vue  #     Markdown + 代码高亮
            ├── AgentThinking.vue     #     Agent 步骤可视化
            ├── ReviewPanel.vue       #     评论分析面板
            ├── MonitorConfig.vue     #     监控任务管理
            ├── GameAliasManager.vue  #     别名库管理
            └── KnowledgeBasePanel.vue#     知识库管理
```

---

## 文档索引

| 文档 | 路径 | 说明 |
|------|------|------|
| 功能文档 | [PROJECT_FEATURES.md](PROJECT_FEATURES.md) | 完整功能说明 + API 列表 + 配置参考 |
| 详细设计 | [docs/steamanalysis-project-feature-details.md](docs/steamanalysis-project-feature-details.md) | 各模块详细实现 + 评估指标 + 架构图 |
| AI 笔记 | [ai-note/](ai-note/) | AI 讨论、学习笔记、架构决策记录 |
| 升级规划 | [C:\Users\thresh\.claude\plans\precious-spinning-bumblebee.md] | 6 Phase 企业级升级计划 |

---

## 常用命令

```bash
# 后端测试
cd backend && .venv/Scripts/python -m pytest

# 前端构建
cd frontend && npm run build

# 采集 Steam 快照
curl -X POST http://127.0.0.1:9000/api/games/730/snapshots -H "Content-Type: application/json" -d "{}"

# 触发舆情分析
curl -X POST http://127.0.0.1:9000/api/web-sentiment/analyze \
  -H "Content-Type: application/json" \
  -d '{"game":"ELDEN RING","query":"ELDEN RING update backlash","limit":3}'

# Docker 构建 + 启动
docker-compose up -d --build
```

---

## 运行模式说明

- 默认 `docker-compose.yml` 启动 `backend`、`task_worker`、`frontend`，并显式关闭 API 进程内 scheduler；它不提供自动监控调度。
- 严格生产环境使用 `docker-compose.prod.yml`，其中 `scheduler` 是独立服务，负责自动监控任务。
- 开发环境 `docker-compose.dev.yml` 同样关闭 API 进程内 scheduler，避免热重载时重复调度。
- 运行时依赖状态查看：`GET /api/status`。轻量健康检查仍使用 `GET /api/health`。
