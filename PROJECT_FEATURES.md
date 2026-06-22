# SteamAnalysis — 完整功能文档

> v0.3.0 — 面向游戏行业的 LLM Agent 研究分析工作台

---

## 目录

1. [项目概述](#项目概述)
2. [技术栈](#技术栈)
3. [功能模块详解](#功能模块详解)
   - [1. Steam 游戏搜索与信息查询](#1-steam-游戏搜索与信息查询)
   - [2. 快照采集与趋势分析](#2-快照采集与趋势分析)
   - [3. 快照 A/B 对比](#3-快照-ab-对比)
   - [4. Steam 评论分析](#4-steam-评论分析)
   - [5. 网页舆情分析](#5-网页舆情分析)
   - [6. RAG 知识库](#6-rag-知识库)
   - [7. AI Agent 聊天](#7-ai-agent-聊天)
   - [8. 跨会话记忆系统](#8-跨会话记忆系统)
   - [9. 后台任务队列](#9-后台任务队列)
   - [10. 监控调度器](#10-监控调度器)
   - [11. 报告导出](#11-报告导出)
   - [12. 应用设置](#12-应用设置)
4. [前端页面](#前端页面)
5. [企业基础设施](#企业基础设施)
6. [API 端点索引](#api-端点索引)
7. [能力边界与限制](#能力边界与限制)
8. [生产级别约束评估](#生产级别约束评估)
9. [测试指南](#测试指南)
10. [快速启动](#快速启动)

---

## 项目概述

SteamAnalysis 是一个面向游戏公司、发行团队和游戏投资分析场景的**本地优先数据分析 Agent**。项目以 Steam 公开数据为核心数据源，结合本地 SQLite 快照、评论抽样分析、RAG 知识库、监控配置、报告导出和可追踪 Agent 工作流。

**核心设计原则：**
- 不登录 Steam，不读取私有账户数据
- 所有结论必须有可追溯来源（API URL / 本地快照 ID / 报告 ID）
- LLM 不可用时自动降级到确定性规则引擎
- 写入操作需用户显式确认

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn (Python 3.12+) |
| ORM + 迁移 | SQLModel + Alembic |
| 数据库 | SQLite (FTS5 全文搜索 + sqlite-vec 向量搜索) |
| LLM Agent | LangChain (DeepSeek / OpenAI 可切换) |
| LLM 抽象 | Provider 模式 (deepseek / openai)，自动 Metrics 包装 |
| 嵌入 | Provider 模式 (deepseek / openai / hash 降级) |
| HTTP | httpx + tenacity 重试 + 熔断器 (Circuit Breaker) |
| 定时任务 | APScheduler + 独立 Worker 进程 |
| 任务队列 | SQLite-backed 状态机 + asyncio 后台 Worker |
| 前端 | Vue 3 + TypeScript + Vite |
| 状态管理 | Pinia |
| 图表 | ECharts 6 + vue-echarts |
| CSS | Tailwind CSS v4 |
| UI 图标 | Lucide Vue Next |
| Markdown | markdown-it + Shiki 代码高亮 |
| 测试 | pytest (后端) + Vitest (前端单元) + Playwright (E2E) |
| 部署 | Docker + docker-compose (dev/prod 分离) + nginx |
| 可观测性 | 结构化日志 + Request ID + Prometheus Metrics |

---

## 功能模块详解

### 1. Steam 游戏搜索与信息查询

**路由**: `GET /api/games/search`, `GET /api/games/{appid}`, `GET /api/games/{appid}/price-comparison`

**能力:**
- 中英文游戏名搜索（含本地中文别名库），返回按置信度排序的候选列表
- Steam AppID 直接查询（支持 3-8 位数字正则解析）
- 游戏详情：名称、类型、封面图、发行/开发商、分类、标签、推荐总数
- 实时在线人数（Steam ISteamUserStats API，缓存 5 分钟）
- Steam 商店价格与折扣信息（支持指定地区 CC 和语言）
- 多地区价格对比（CN/US/JP 三地区并发请求）
- Steam 新闻/公告获取（最多 20 条）
- 全球成就完成率统计

**涉及文件:**
- Route: `backend/app/api/routes/games.py`, `aliases.py`
- Service: `backend/app/services/steam_client.py`, `game_alias_service.py`
- Schema: `backend/app/schemas/game.py`

**能力边界:**
- 仅限 Steam 公开 HTTP API，无登录态，无私有数据
- 搜索 API 缓存 12 小时
- 每个 Steam API 端点有独立熔断器（5 次失败 → 60s 冷却）
- 所有请求经过 tenacity 指数退避重试（最多 3 次）

---

### 2. 快照采集与趋势分析

**路由**: `POST /api/games/{appid}/snapshots`, `GET /api/games/{appid}/snapshots`, `GET /api/games/{appid}/trend`

**能力:**
- 采集当前游戏状态快照：在线人数、价格、折扣、新闻、源 URL
- 本地 SQLite 持久化存储，带采集时间戳和地区/语言标记
- 快照标签（`POST /api/snapshots/{snapshot_id}/labels`）：如"更新前"、"大促期间"
- 趋势分析：基于本地历史快照，计算在线人数峰值/均值、变化趋势（上升/下降/稳定）
- 价格变化追踪：历年折扣变化、史低检测
- 时间窗口筛选：支持 1-365 天范围

**涉及文件:**
- Route: `backend/app/api/routes/snapshots.py`
- Service: `backend/app/services/snapshot_service.py`
- Schema: `backend/app/schemas/snapshot.py`

**能力边界:**
- 趋势分析仅基于**本地已采集**的快照数据，首次使用无历史数据
- 在线人数为瞬时值，不是日/周均值，受采集时段影响
- 快照采集标记为 L2 写入操作，需在 Agent 聊天中确认

---

### 3. 快照 A/B 对比

**路由**: `POST /api/compare`

**能力:**
- 支持按 `snapshot_id`、`appid`（取最新快照）或 `label`（标签筛选）选取左右两侧快照
- 逐字段对比：在线人数、最终价格、折扣百分比、推荐总数
- 自动计算 delta 值（增量/变化量）
- 可比性检测：地区（CC）和币种一致性检查
- 辅助可视化图表（ECharts 柱状图）
- 对比结果含不确定性说明和深度解读

**涉及文件:**
- Route: `backend/app/api/routes/compare.py`
- Service: `backend/app/services/comparison_service.py`
- Schema: `backend/app/schemas/compare.py`

**能力边界:**
- 纯数值对比，不做因果推断或统计检验
- CC/币种不一致的快照标记为不可比
- 不能跨游戏对比不同类型的指标

---

### 4. Steam 评论分析

**路由**: `GET /api/games/{appid}/reviews`, `POST /api/games/{appid}/reviews/analyze`

**能力:**
- 获取 Steam 最近评论（支持语言过滤：schinese/english/tchinese/japanese/koreana）
- **LLM 话题提取**：批量（8 条/组）发送给 LLM 提取情绪和话题
- **关键词规则 fallback**：当 LLM 不可用时自动降级到中英文关键词匹配
- 输出：样本好评率、正向关键词（如"优化"、"剧情"）、负向关键词（如"bug"、"服务器"）
- 支持过滤：好评/差评分类、时间窗口（最近 N 天）、样本量设定（10-500）
- 语言分层统计：多语言评论时自动展示分布
- 小样本警告：样本量 < 30 时自动添加统计意义提醒
- 分析结果持久化到 `review_analyses` 表

**涉及文件:**
- Route: `backend/app/api/routes/reviews.py`
- Service: `backend/app/services/review_service.py`
- Schema: `backend/app/schemas/review.py`

**能力边界:**
- 评论抽样 ≤ 500 条，不等于 Steam 总体评价（总体评价另有 Steam API 评分字段）
- LLM 分析有 30s 超时限制
- 评论语言过滤依赖 Steam API 的 language 参数

---

### 5. 网页舆情分析

**路由**: `POST /api/web-sentiment/analyze`, `GET /api/web-sentiment/events`, `GET /api/web-sentiment/sources`

**能力:**
- 搜索→抓取→LLM 声明提取→情感评分全流程
- 自动构造搜索词（游戏名 + 舆情关键词）
- 从抓取网页中提取观点声明（player_feedback/review/technical/community）
- 情感评分：positive/negative/neutral/mixed
- 风险强度：low/medium/high/critical
- 每条声明带置信度（0-1）
- 舆情事件和网页来源持久化存储，支持历史浏览
- 支持作为后台任务提交（避免 HTTP 超时）

**涉及文件:**
- Route: `backend/app/api/routes/web_sentiment.py`
- Service: `backend/app/services/web_sentiment_service.py`
- Schema: `backend/app/schemas/web_sentiment.py`

**能力边界:**
- 依赖 Firecrawl API，需要有效的 API Key
- 全链路耗时长（15-60 秒），不适合高频调用
- 搜索质量受搜索引擎限制
- 声明提取置信度依赖 LLM 质量

---

### 6. RAG 知识库

**路由**: `POST /api/knowledge/documents`, `GET /api/knowledge/documents`, `POST /api/knowledge/search`, `GET /api/knowledge/stats`, `DELETE /api/knowledge/documents/{id}`

**能力:**
- 文档导入（Markdown/文本/代码），自动智能分块
- 分块策略：Markdown 标题分割 + 段落窗口（overlap）+ Python 代码函数级拆分
- **混合检索**：FTS5 全文搜索 (BM25) + sqlite-vec 向量搜索 → RRF 融合
- **Cross-Encoder 精排**：LLM 对 Top-20 候选做相关性重评估
- Embedding Provider 切换：deepseek / openai / hash（降级）
- 索引统计：文档数、分块数、FTS 可用性、向量索引可用性
- 限定 appid 范围搜索
- 搜索结果带关键字分、向量分、精排分

**涉及文件:**
- Route: `backend/app/api/routes/knowledge.py`
- Service: `backend/app/services/knowledge_service.py`, `embedding_service.py`
- Schema: `backend/app/schemas/knowledge.py`

**能力边界:**
- 基于本地文档，不联网检索
- 向量搜索依赖 sqlite-vec 扩展（Python 端 cosine 相似度作为 fallback）
- Embedding API 不可用时自动降级为确定性 hash（无语义搜索能力）
- 单次搜索最多加载 3000 个分块做 Python 向量计算

---

### 7. AI Agent 聊天

**路由**: `POST /api/chat` (非流式), `POST /api/chat/stream` (SSE 流式)

**能力:**
- **任务自动分类** (8 种类型)：single_game / game_comparison / review_analysis / web_sentiment / market_intelligence / history_trend / schedule_monitor / export
- **确定性状态机工作流**：PLAN → ACT → OBSERVE → SYNTHESIZE → VALIDATE → DONE
- **自我反思循环**：验证阶段发现问题→自动返回 PLAN 重新分析（最多 3 轮）
- **LangChain Agent 集成**：DeepSeek/OpenAI 可切换，自主调用只读工具
- **SSE 流式事件**：thinking / route / tool_call / observation / validation / result / reflection
- **写入确认机制**：L2（快照采集）和 L3（导出）操作需用户显式确认
- **AgentRun + AgentCheckpoint**：每步状态可追溯、可恢复
- **工具执行统一策略**：输入校验 → 权限检查 → 超时控制 → 重试 → 审计日志
- **长期记忆注入**：自动加载跨会话记忆上下文

**涉及文件:**
- Route: `backend/app/api/routes/chat.py`
- Agent: `backend/app/agent/core.py`, `runtime.py`, `tools.py`, `task_classifier.py`, `prompts.py`, `validators.py`, `memory.py`
- Schema: `backend/app/schemas/chat.py`

**全局工具注册表** (14 个工具):

| 工具名 | 权限 | 超时 | 重试 | 描述 |
|--------|------|------|------|------|
| `search_games` | read | 12s | 2次 | Steam 游戏名搜索 |
| `get_current_players` | read | 12s | 2次 | 实时在线人数 |
| `get_appdetails` | read | 12s | 2次 | 商店详情（价格/折扣/分类） |
| `get_game_news` | read | 12s | 0 | Steam 新闻 |
| `get_achievement_stats` | read | 12s | 0 | 全球成就统计 |
| `list_snapshots` | read | 5s | 0 | 本地快照列表 |
| `compare_snapshots` | read | 5s | 0 | 快照对比 |
| `save_snapshot` | write | 18s | 1次 | 采集保存快照 |
| `label_snapshot` | write | 3s | 0 | 快照打标签 |
| `get_reviews` | read | 18s | 2次 | 获取评论原文 |
| `analyze_reviews` | read | 30s | 1次 | LLM 评论分析 |
| `get_trend_analysis` | read | 5s | 0 | 历史趋势分析 |
| `rag_search` | read | 8s | 0 | 知识库混合检索 |
| `analyze_web_sentiment` | read | 60s | 0 | 网页舆情分析 |
| `recall_memory` | read | 5s | 0 | 跨会话记忆召回 |

**能力边界:**
- LLM 不可用时 Agent 降级为确定性工作流（预设 step-by-step 执行）
- LangChain Agent 只注册只读工具，写入操作走确定性路径
- 一次性对话默认 50 条消息上限
- 工具调用有 15-60s 不等的超时限制

---

### 8. 跨会话记忆系统 🆕

**路由**: `GET /api/memory`, `GET /api/memory/stats`, `GET /api/memory/pending`, `POST /api/memory/confirm/{entry_id}`, `DELETE /api/memory/{entry_id}`

**能力:**
- **MemoryEntry** 模型：支持 fact / preference / summary / event 四种类型
- **FTS5 + vec0 混合语义召回**：RRF 融合 + recency bonus + importance 加权
- **自动事实提取**：
  - 启发式提取（总是运行）：appid 关联检测、偏好语句识别、纠正检测、任务类型识别
  - LLM 提取（可选）：从 user+assistant 消息对中提取结构化事实（text/type/importance）
- **对话摘要**：消息 ≥ 20 条触发，LLM 或模板方式生成摘要，同时存入 MemoryEntry
- **PII 过滤**：记忆写入前自动移除 Email、电话号码、IP、API Key、Bearer Token
- **确认机制**：pending → confirmed 两级状态，LLM 提取的事实需用户确认
- **重要性衰减**：自动归档低重要度（< 0.3）且 30 天未访问的记忆
- **工作上下文注入**：Agent 聊天时自动注入当前对话摘要 + 用户偏好 + 相关记忆 + 最近讨论游戏

**涉及文件:**
- Route: `backend/app/api/routes/memory.py`
- Service: `backend/app/services/memory_service.py`
- Core: `backend/app/core/pii_filter.py`

**能力边界:**
- 记忆召回依赖向量索引，sqlite-vec 不可用时降级为 Python cosine
- PII 检测是正则匹配，不担保 100% 覆盖所有 PII 类型
- LLM 提取是 best-effort 方式，失败不阻塞记忆创建

---

### 9. 后台任务队列 🆕

**路由**: `POST /api/tasks`, `GET /api/tasks/{task_id}`, `POST /api/tasks/{task_id}/cancel`, `GET /api/tasks`

**能力:**
- **状态机**：pending → running → completed / failed / cancelled（terminal 状态不可变）
- **进度轮询**：0-100% 带 human-readable 进度消息
- **协作取消**：handler 在执行过程中周期性检查 `is_cancelled()`，提前中止
- **原子认领**：Worker 通过 status 双重检查防止多 Worker 竞争同一任务
- **内建 Handler**：
  1. `web_sentiment` — 后台执行网页舆情分析（避免 HTTP 超时）
  2. `batch_snapshot` — 批量采集多个 appid 快照，支持中途取消
  3. `report_generate` — 后台生成分析报告（趋势+评论多阶段分析）
- **结构化错误**：error_code (machine-readable) + error_detail (human-readable)
- **独立 Worker 进程**：`python -m app.worker.task_worker` 可独立部署

**涉及文件:**
- Route: `backend/app/api/routes/tasks.py`
- Service: `backend/app/services/task_queue.py`
- Worker: `backend/app/worker/task_worker.py`
- Schema: `backend/app/schemas/task.py`

**能力边界:**
- 任务队列为进程内 asyncio 实现，非持久化消息队列（Redis/RabbitMQ）
- 重启后 pending 任务不会自动重试（需手动重新入队）
- 单 Worker 模式：一个 `asyncio.ensure_future`，无并行任务执行

---

### 10. 监控调度器

**路由**: `GET /api/monitors`, `POST /api/monitors`, `DELETE /api/monitors/{id}`, `GET /api/monitors/alerts`

**能力:**
- APScheduler 定时采集游戏快照
- 可配置监控间隔（默认 60 分钟）
- 自动告警规则：在线人数暴涨跌（> 50%）、折扣变化、新史低
- 告警分级：info / warning / high
- 独立 Scheduler 进程：`python -m app.worker.scheduler`，带 Health File 心跳
- 可通过 `STEAMANALYSIS_ENABLE_SCHEDULER=false` 禁用

**涉及文件:**
- Route: `backend/app/api/routes/monitors.py`
- Service: `backend/app/services/scheduler_service.py`, `monitor_service.py`
- Worker: `backend/app/worker/scheduler.py`

**能力边界:**
- APScheduler 单进程运行，不支持分布式任务调度
- 重启后需重新加载监控任务
- 告警基于 Delta 规则，不做趋势预测

---

### 11. 报告导出

**路由**: `GET /api/reports`, `GET /api/reports/{report_id}/export/markdown`, `GET /api/reports/{report_id}/export/json`

**能力:**
- Markdown 格式导出（完整可读报告）
- JSON 格式导出（结构化数据，含 evidence、snapshot_ids）
- 报告含**可复现元数据**：model 名、prompt_version hash、tool_versions
- 报告存储与 trace_id 关联，可追踪到具体 Agent 执行

**涉及文件:**
- Route: `backend/app/api/routes/exports.py`, `reports.py`
- Service: `backend/app/services/export_service.py`, `report_service.py`

**能力边界:**
- 仅导出已存储的报告（不支持 ad-hoc 生成）
- 无 PDF/Excel 等其他格式

---

### 12. 应用设置

**路由**: `GET /api/settings`, `PUT /api/settings`

**能力:**
- 默认 CC（ISO 国家代码）、默认语言、默认币种
- LLM Provider 选择、模型名、Embedding Provider
- 所有设置通过 `app_settings` 表持久化

**涉及文件:**
- Route: `backend/app/api/routes/settings.py`
- Service: `backend/app/services/settings_service.py`

---

## 前端页面

| 路由 | 组件 | 功能描述 |
|------|------|----------|
| `/` | DashboardView | **工作台**：游戏搜索、收藏管理、在线人数趋势图（ECharts）、最近报告、监控告警 |
| `/games/:appid` | GameDetailView | **游戏详情**：指标卡片、历史快照折线图、新闻列表、趋势分析、多地区价格对比、评论分析面板 |
| `/compare` | CompareView | **A/B 对比**：左右两侧输入 appid+快照ID，逐指标对比表，可比性检测，辅助柱状图 |
| `/chat` | ChatView | **AI 助手**：SSE 流式对话、Markdown 渲染、实时 Agent 步骤可视化、写入确认、后台任务提交 |
| `/knowledge` | KnowledgeView 🆕 | **知识库**：文档上传/删除、索引统计、知识搜索 |
| `/web-sentiment` | WebSentimentView 🆕 | **舆情浏览**：舆情事件时间线 / 网页来源列表双视图切换、按游戏/appid 筛选 |
| `/settings` | SettingsView | **系统设置**：默认 CC/语言/币种、LLM 参数配置 |

### 前端组件

| 组件 | 描述 |
|------|------|
| AppShell.vue | 全局布局外壳，含导航菜单和路由出口 |
| MetricCard.vue | 关键指标卡片（标签+数值+提示） |
| MarkdownRenderer.vue | Markdown 渲染（markdown-it）+ Shiki 代码语法高亮 |
| AgentThinking.vue | Agent 步骤折叠面板（thinking/route/tool_call/observation/validate） |
| ReviewPanel.vue | 评论分析面板：触发分析、展示好评率/关键词/摘要 |
| MonitorConfig.vue | 监控任务管理：创建/删除监控任务、告警列表 |
| GameAliasManager.vue | 别名库管理：添加/删除中文别名映射 |
| KnowledgeBasePanel.vue | 知识库管理面板：上传/搜索/删除 |
| TaskPollingCard.vue 🆕 | 后台任务轮询卡片：进度条、状态图标、取消按钮、结果预览 |

---

## 企业基础设施

### 安全
- **认证**: Bearer Token 认证（通过 `STEAMANALYSIS_AUTH_TOKEN` 配置启用）
- **授权**: RBAC 模型 — public 角色（只读公开端点）+ admin 角色（全部 scopes）
- **Scope 体系**: 细粒度 `<resource>:<action>` 权限字符串（20+ scopes）
- **限流**: IP-based 滑动窗口，全局 30 req/min，Chat 10 req/min，`X-RateLimit-*` 头
- **请求体大小限制**: 5MB
- **安全头**: X-Content-Type-Options / X-Frame-Options / X-XSS-Protection / Referrer-Policy / Permissions-Policy
- **PII 过滤**: Email / 手机号 / IP / API Key / Bearer Token 自动检测与脱敏

### 可观测性
- **结构化日志**: Python logging + Request ID 上下文
- **Prometheus Metrics**: HTTP 请求 / LLM 调用 / 工具调用 / Steam API 调用 counters + histograms
- **HTML Metrics Dashboard**: `GET /api/metrics/dashboard`
- **健康检查**: `GET /api/health`（含 DB 和 Vector 索引可用性）
- **Request Timing**: 每个请求的 `X-Response-Time-Ms` 响应头

### 部署
- **Docker 容器化**: 多阶段 Dockerfile（backend + frontend）
- **docker-compose.yml**: 基础部署（backend + frontend + nginx）
- **docker-compose.dev.yml**: 开发模式（热重载 + 源码挂载）
- **docker-compose.prod.yml**: 生产模式（无源码挂载 + AUTH_TOKEN 强制 + 独立 Scheduler 容器）
- **Healthcheck**: backend（HTTP API 检查）/ frontend（wget 检查）
- **Alembic 数据库迁移**: 版本化 schema 迁移

### CI/CD
- **GitHub Actions**: 测试 + Docker 构建
- **ruff**: Python Lint (E, F, I, UP, B)
- **mypy**: Python 类型检查
- **ESLint + Prettier**: 前端代码规范

---

## API 端点索引

### 公开端点（无需认证）
| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/health` | 健康检查（DB + Vector 索引） |
| GET | `/api/metrics` | Prometheus Metrics |
| GET | `/api/metrics/dashboard` | HTML Metrics 仪表板 |
| GET | `/api/games/search` | 搜索 Steam 游戏 |
| GET | `/api/games/{appid}` | 游戏详情 |
| GET | `/api/games/{appid}/price-comparison` | 多地区价格对比 |
| GET | `/api/games/{appid}/snapshots` | 快照列表 |
| GET | `/api/games/{appid}/trend` | 趋势分析 |
| GET | `/api/games/{appid}/reviews` | 最新评论分析结果 |
| GET | `/api/aliases/games` | 别名列表 |
| GET | `/api/snapshots` | 所有快照 |

### 写入端点（需 Bearer Token 或开发模式确认）
| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/games/{appid}/snapshots` | 采集快照 |
| POST | `/api/snapshots/{snapshot_id}/labels` | 快照打标签 |
| POST | `/api/compare` | 快照对比 |
| POST | `/api/games/{appid}/reviews/analyze` | 触发评论分析 |
| POST | `/api/web-sentiment/analyze` | 触发舆情分析 |
| POST | `/api/knowledge/documents` | 上传知识文档 |
| DELETE | `/api/knowledge/documents/{id}` | 删除知识文档 |
| POST | `/api/knowledge/search` | 知识库搜索 |
| GET | `/api/knowledge/stats` | 知识库统计 |
| POST | `/api/chat` | Agent 聊天（非流式） |
| POST | `/api/chat/stream` | Agent 聊天（SSE 流式） |
| POST | `/api/monitors` | 创建监控任务 |
| DELETE | `/api/monitors/{id}` | 删除监控任务 |
| POST | `/api/tasks` | 创建后台任务 |
| POST | `/api/tasks/{id}/cancel` | 取消后台任务 |
| GET | `/api/reports` | 报告列表 |
| GET | `/api/reports/{id}/export/{format}` | 导出报告 |
| GET/PUT | `/api/settings` | 读写设置 |
| GET/POST/DELETE | `/api/memory/*` | 记忆管理 |

---

## 能力边界与限制

### 数据源限制
| 数据 | 来源 | 频率限制 | 缓存时长 |
|------|------|----------|----------|
| 游戏搜索 | Steam Store Search API | — | 12h |
| 在线人数 | Steam ISteamUserStats | 熔断器保护 | 5min |
| 商店详情 | Steam Store appdetails | 熔断器保护 | 30min |
| 游戏新闻 | Steam ISteamNews | 熔断器保护 | 30min |
| 用户评论 | Steam Store Reviews | 熔断器保护 | 30min |
| 网页搜索 | Firecrawl API | 需 API Key | 无缓存 |

### 规模限制
- 单次评论分析：10-500 条
- 快照对比：2 个快照
- 知识库搜索：最多 3000 个分块做 Python fallback
- Agent 对话历史：单会话 50 条消息
- 收藏游戏：最多 20 个
- 请求体大小：5MB
- 速率限制：全局 30 req/min，Chat 10 req/min

### 降级行为
- LLM 不可用 → 确定性规则引擎（关键词匹配、模板合成）
- 向量索引不可用 → Python cosine 相似度
- Embedding API 不可用 → Hash 确定性向量（无语义能力）
- Steam API 熔断器打开 → 直接返回错误，不重试
- Firecrawl 不可用 → 舆情分析返回空

---

## 生产级别约束评估

### ✅ 已完成

- **多层安全中间件**: RequestId → Timing → SecurityHeaders → CORS → Auth → RateLimit → SizeLimit
- **RBAC 授权**: public/admin 角色 + 20+ 细粒度 Scopes
- **IP 限流**: 滑动窗口 + 路由级别差异化
- **Steam API 熔断器**: 每端点独立，失败阈值 5 → 60s 冷却 → half-open
- **重试**: tenacity 指数退避（Steam API 3 次，工具级别可配）
- **结构化日志**: Request ID 贯穿全链路
- **Prometheus Metrics**: 请求/LLM/工具/Steam API 四维 counters+histograms
- **Docker 容器化**: 多阶段构建，dev/prod compose 分离，healthcheck
- **Alembic 迁移**: 版本化 schema 管理
- **LLM Provider 抽象**: deepseek/openai 切换，embedding provider 切换
- **Agent 可恢复性**: AgentRun + AgentCheckpoint 每步记录
- **工具审计**: ToolCall 表记录每次调用的参数、状态、延迟、trace_id
- **报告可复现**: 模型名 + prompt hash + tool 版本 hash
- **输入校验**: Pydantic 严格模型（范围/长度/枚举约束）
- **PII 过滤**: 写入记忆前自动脱敏
- **健康检查**: DB + Vector 索引双维度
- **CI/CD**: GitHub Actions 测试 + 构建

### ⚠ 需要改进（生产部署前）

1. **数据库**: SQLite → PostgreSQL（高并发写入场景）
2. **Metrics 持久化**: 纯内存 → prometheus_client 库 + Pushgateway
3. **调度器**: 单进程 APScheduler → Celery/Redis 分布式调度
4. **任务队列**: asyncio 队列 → Redis/RabbitMQ 持久化
5. **速率限制**: 内存实现 → Redis 集中式计数器
6. **Session 管理**: localStorage token → 服务端 session + JWT
7. **HTTPS/TLS**: 需在 nginx/反向代理层启用
8. **数据库备份**: 手动脚本 → 自动化 cron + 异地存储
9. **审计日志清理**: 无自动归档策略

---

## 测试指南

### 后端测试

```bash
cd backend

# 安装测试依赖（首次）
.venv/Scripts/pip install -e ".[test]"

# 运行全部测试
.venv/Scripts/python -m pytest app/tests/ -v

# 运行全部测试 + evals
.venv/Scripts/python -m pytest app/tests/ app/evals/ -v

# 运行单个测试文件
.venv/Scripts/python -m pytest app/tests/test_api_games.py -v
.venv/Scripts/python -m pytest app/tests/test_api_chat.py -v
.venv/Scripts/python -m pytest app/tests/test_api_reviews.py -v
.venv/Scripts/python -m pytest app/tests/test_api_tasks.py -v
.venv/Scripts/python -m pytest app/tests/test_comparison_service.py -v
.venv/Scripts/python -m pytest app/tests/test_game_alias_service.py -v
.venv/Scripts/python -m pytest app/tests/test_knowledge_service.py -v
.venv/Scripts/python -m pytest app/tests/test_web_sentiment_service.py -v
.venv/Scripts/python -m pytest app/tests/test_scheduler_service.py -v
.venv/Scripts/python -m pytest app/tests/test_tools.py -v
.venv/Scripts/python -m pytest app/tests/test_auth.py -v
.venv/Scripts/python -m pytest app/tests/test_metrics.py -v
.venv/Scripts/python -m pytest app/tests/test_pii_filter.py -v
.venv/Scripts/python -m pytest app/tests/test_reflection_loop.py -v
.venv/Scripts/python -m pytest app/tests/test_web_source_policy.py -v

# Evals
.venv/Scripts/python -m pytest app/evals/test_classifier_eval.py -v
.venv/Scripts/python -m pytest app/evals/test_rag_eval.py -v
.venv/Scripts/python -m pytest app/evals/test_report_quality_eval.py -v
.venv/Scripts/python -m pytest app/evals/test_tool_selection_eval.py -v

# 跳过慢测试
.venv/Scripts/python -m pytest app/tests/ -v -m "not slow"

# 只跑单元测试（跳过集成测试）
.venv/Scripts/python -m pytest app/tests/ -v -m "not integration"

# 带覆盖率
.venv/Scripts/pip install pytest-cov
.venv/Scripts/python -m pytest app/tests/ --cov=app --cov-report=html
```

### 前端测试

```bash
cd frontend

# 单元测试 (Vitest)
npm run test:unit

# E2E 测试 (Playwright — 需要先安装浏览器）
npx playwright install chromium
npm run test:e2e

# E2E 可视化模式
npm run test:e2e:ui

# 查看 E2E 报告
npm run test:e2e:report

# TypeScript 类型检查
npm run typecheck

# Lint
npm run lint

# 格式化检查
npm run format:check
```

### 手动功能测试（curl）

```bash
BASE="http://127.0.0.1:9000/api"

# 1. 健康检查
curl $BASE/health

# 2. 搜索游戏
curl "$BASE/games/search?query=老头环"

# 3. 采集快照
curl -X POST "$BASE/games/1245620/snapshots" -H "Content-Type: application/json" -d "{}"

# 4. 查看快照
curl "$BASE/games/1245620/snapshots?limit=5"

# 5. 趋势分析
curl "$BASE/games/730/trend?days=7"

# 6. 对比
curl -X POST "$BASE/compare" \
  -H "Content-Type: application/json" \
  -d '{"left":{"appid":730},"right":{"appid":570}}'

# 7. 评论分析
curl -X POST "$BASE/games/730/reviews/analyze?count=20&language=schinese"

# 8. 知识库上传 + 搜索
curl -X POST "$BASE/knowledge/documents" \
  -H "Content-Type: application/json" \
  -d '{"title":"CS2分析笔记","content":"CS2是Counter-Strike系列最新作...","source_type":"note"}'

curl -X POST "$BASE/knowledge/search" \
  -H "Content-Type: application/json" \
  -d '{"query":"CS2更新","limit":5}'

# 9. 舆情分析
curl -X POST "$BASE/web-sentiment/analyze" \
  -H "Content-Type: application/json" \
  -d '{"game":"CS2","query":"CS2 latest update feedback","limit":3}'

# 10. Chat Agent (非流式）
curl -X POST "$BASE/chat" \
  -H "Content-Type: application/json" \
  -d '{"query":"CS2最近怎么样"}'

# 11. 创建后台任务
curl -X POST "$BASE/tasks" \
  -H "Content-Type: application/json" \
  -d '{"task_type":"web_sentiment","input_data":{"game":"CS2","query":"CS2 update 2025","limit":3}}'

# 12. 轮询任务
curl "$BASE/tasks/1"

# 13. 记忆系统
curl "$BASE/memory?user_key=test-user&limit=10"

# 14. Metrics
curl $BASE/metrics
```

---

## 快速启动

### 方式一：本地开发

```bash
# 1. 后端
cd backend
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY（必要），可选 STEAM_API_KEY / FIRECRAWL_API_KEY
.venv/Scripts/pip install -e ".[test]"
.venv/Scripts/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 9000

# 2. 前端（新终端）
cd frontend
cp .env.example .env.local
npm install
npm run dev
# 访问 http://localhost:3173
```

### 方式二：Docker

```bash
# 开发模式（热重载）
cp backend/.env.example backend/.env
docker compose -f docker-compose.dev.yml up -d

# 生产模式
docker compose -f docker-compose.prod.yml up -d

# 访问
# 前端：http://localhost:8080
# API 文档：http://localhost:9000/docs
# Metrics：http://localhost:9000/api/metrics
```

### 方式三：仅后端 API（无前端）

```bash
cd backend
.venv/Scripts/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 9000
# 访问 http://127.0.0.1:9000/docs 使用 Swagger UI 测试所有 API
```

---

## 环境变量参考

| 变量 | 默认值 | 描述 |
|------|--------|------|
| `STEAMANALYSIS_ENV` | development | 运行环境 |
| `STEAMANALYSIS_DATABASE_URL` | sqlite:///./steamanalysis.sqlite3 | 数据库连接 |
| `STEAMANALYSIS_DEFAULT_CC` | CN | 默认国家代码 |
| `STEAMANALYSIS_DEFAULT_LANGUAGE` | schinese | 默认语言 |
| `STEAMANALYSIS_DEFAULT_CURRENCY` | CNY | 默认币种 |
| `STEAMANALYSIS_LLM_PROVIDER` | deepseek | LLM 供应商 (deepseek/openai) |
| `STEAMANALYSIS_LLM_MODEL` | gpt-4o-mini | OpenAI 模型名 |
| `STEAMANALYSIS_EMBEDDING_PROVIDER` | deepseek | 嵌入供应商 (deepseek/openai/hash) |
| `STEAMANALYSIS_EMBEDDING_DIM` | 1536 | 嵌入维度 |
| `STEAMANALYSIS_AUTH_TOKEN` | (空) | 设置后启用 Bearer Token 认证 |
| `STEAMANALYSIS_ENABLE_SCHEDULER` | true | 是否启用后台调度器 |
| `STEAMANALYSIS_RATE_LIMIT_REQUESTS_PER_MINUTE` | 30 | 全局速率限制 |
| `STEAMANALYSIS_RATE_LIMIT_CHAT_PER_MINUTE` | 10 | Chat 端点速率限制 |
| `DEEPSEEK_API_KEY` | (空) | DeepSeek API Key |
| `STEAM_API_KEY` | (空) | Steam Web API Key（可选，增强功能） |
| `FIRECRAWL_API_KEY` | (空) | Firecrawl API Key（网页舆情需要） |
| `OPENAI_API_KEY` | (空) | OpenAI API Key（使用 OpenAI provider 时需要） |
