# CodeMate

## 演示视频

<video src="asset/CodeMate演示视频.mp4" controls width="100%">
  <a href="asset/CodeMate演示视频.mp4">查看 CodeMate 演示视频</a>
</video>

[无法直接播放时，点击查看演示视频](asset/CodeMate演示视频.mp4)

CodeMate 是一个面向本地代码库的编程智能体工作台。它把 Agent 对话、树形历史、Lane 方案分支、Git 代码隔离和文件工作台放在同一个界面中，适合需要反复探索、比较和收敛实现方案的开发任务。

> 当前版本以本地单用户工作流为主：后端运行在本机，数据保存在本地文件，前端通过 REST + WebSocket 与后端通信。

## 核心亮点

### 1. 树形记忆管理：保存 Agent 的思考演化过程

用户消息、Agent 回复和工具结果都作为 Entry 持久化，并通过 `parent` 形成树形记忆。系统不会把对话强行压平成一条时间线，而是能够重建每个泳道从根节点到 `leaf_id` 的有效上下文，保留共享前缀并隔离不同泳道的后续内容。前端提供树形画布、当前路径高亮和节点详情查看，便于理解 Agent 如何得到当前结果。

当前实现支持查看历史节点和切换已有泳道；新泳道从当前活动泳道的叶节点创建，尚未提供点击任意历史节点后直接“回溯、分叉、重试”的独立交互入口。这样既避免把尚未实现的能力写成现有功能，也明确了树形记忆模型为后续分支操作留下的扩展基础。

### 2. 泳道管理与 Git 分支管理结合：从思路到代码的完整闭环

泳道（Lane）代表一个相对独立的方案方向，拥有名称、描述、当前记忆叶节点和代码绑定状态。用户可以在同一 Session 中创建和切换多个泳道，对比不同方案的对话与代码结果。

在 Git 项目中，泳道不仅是对话路径，也是代码隔离单元：`main` 泳道使用原始工作区，其他泳道使用托管 Git 分支和独立 Worktree。不同方案可以并行修改而互不覆盖；Agent 运行后的修改可以形成检查点，用户能够查看状态和差异、恢复检查点、放弃未保存修改、将泳道发布为普通本地分支，并在集成前预览变更，最后将已发布的方案合并回主工作区。由此形成“记忆分叉—代码分叉—方案比较—结果集成”的工作流。没有 Git 时仍可使用树形记忆和泳道探索，代码管理能力会明确降级。

### 3. 接近 VSCode 的会话工作台

工作台把活动栏、文件资源管理器、搜索、编辑器标签、Source Control、终端和对话区组合在一起。Agent 修改文件后可以直接在编辑器中查看、保存和审查，不需要在多个工具之间来回切换。

### 4. 工具执行默认受权限门禁保护

工具按 `SAFE`、`WRITE`、`DANGEROUS` 分级。只读操作自动放行；工作区内写入通常自动放行；危险命令、工作区外修改和无法自动判定的操作通过 WebSocket 请求用户确认。命令黑名单、工作区路径检查、命令替换检查和系统关键路径拒绝共同构成安全边界。

### 5. 流式 Agent、并行工具和只读子 Agent

Agent 通过流式 LLM 接口逐步输出文本和工具调用；同一轮中的多个独立工具调用可以并行执行。`delegate_task` 可以把多步调查交给只读子 Agent，子 Agent 使用独立的临时上下文，执行过程不会污染父 Agent 的对话树。

### 6. 本地持久化与可恢复运行

Workspace、Session、Lane、对话树、Git 检查点、操作记录和日志按职责分开保存。JSON/JSONL 结构便于本地备份、检查和迁移；Session 删除采用可恢复 Journal；文件保存使用版本摘要，发现外部修改时返回冲突而不是静默覆盖。

### 7. 上下文预算、自动压缩和智能命名

系统按当前 Lane 生成模型上下文，提供上下文预算显示和手动压缩入口；达到阈值时可生成摘要以控制上下文增长。Session 可以在首个成功 Run 后由模型自动命名，也支持手动重命名并锁定标题。

## 功能介绍

### 工作区、Session 与 Lane

CodeMate 使用三层对象组织一次开发工作：

| 层级 | 作用 | 生命周期 |
|---|---|---|
| Workspace | 一个本地项目目录的注册记录 | 可在多个 Session 间复用 |
| Session | 一次连续的 Agent 工作 | 包含对话、Lane、Git 元数据和日志 |
| Lane | 一个方案方向及其当前对话/代码状态 | 在 Session 内创建、切换、归档或删除 |

SessionPicker 支持选择工作区、创建工作区、创建 Session、重命名和删除 Session。首次创建时可以使用系统原生目录选择器选择本地目录。

### 树形对话与历史导航

- 用 React Flow + dagre 展示 Entry 树。
- 当前 Lane 的 `leaf_id` 决定当前路径；Entry 的 `parent` 是树路径权威来源。
- 支持点击节点查看详情，并高亮当前 Lane 的有效路径。
- 新 Lane 从当前活动 Lane 的叶节点创建；当前没有任意历史节点直接恢复、分叉或重试的独立按钮。
- 节点详情、对话内容、工具调用和子 Agent 结果在同一工作台中查看。
- 前端发送消息时先显示乐观用户消息，服务端确认后再替换为真实 Entry ID。
- 多个并行工具结果会聚合为一个工具节点，保留每次调用的关联信息。

### Agent 与 LLM

- `LLMClient` 统一 OpenAI Chat Completions 兼容接口。
- 当前支持 `openai` 和 `deepseek` Provider；OpenAI Provider 可通过 `LLM_BASE_URL` 连接兼容网关。
- 支持流式文本、工具调用、usage、reasoning content 和不完整工具调用检测。
- 可重试错误采用指数退避；已经产生文本后不重复重放请求，避免前端出现重复内容。
- Agent 工具失败通常作为 `tool` 结果返回给模型继续处理；Run 级失败通过 `run_error` 反馈。

### 内置工具

主 Agent 默认提供以下工具：

| 工具 | 用途 | 权限级别 |
|---|---|---|
| `read_file` | 读取文本文件 | `SAFE` |
| `list_directory` | 浏览目录直接子项 | `SAFE` |
| `glob` | 按模式查找文件 | `SAFE` |
| `grep` | 搜索文件内容 | `SAFE` |
| `web_search` | 通过配置的搜索服务搜索网页 | `SAFE` |
| `web_fetch` | 抓取公共网页正文 | `SAFE` |
| `write_file` | 创建或覆盖文件 | `WRITE` |
| `edit_file` | 按编辑操作修改文件 | `WRITE` |
| `bash` | 执行命令 | `DANGEROUS` |

`delegate_task` 在运行时注册为只读子 Agent 工具，子 Agent 使用受限工具注册表，不具备写入能力。

联网搜索当前支持配置博查（Bocha）或火山引擎/豆包 Global 搜索；`web_fetch` 对目标 URL 做 SSRF 防护，不应被视为任意网络代理。

### 权限确认与安全边界

- `SAFE` 工具自动放行。
- `WRITE` 工具检查路径：工作区内可自动放行，系统关键路径直接拒绝，工作区外需要确认。
- `bash` 先经过危险模式、命令替换、`cd` 越界、写入目标和黑名单检查。
- 用户确认支持仅本次允许、总是允许和拒绝。
- 子 Agent 复用父 Session 的权限管理器。
- 当前没有 Docker/容器沙箱；安全边界由权限门禁、路径约束、固定工作目录、超时和进程输出控制组成。

### Git、检查点与代码集成

在检测到 Git 仓库且存在初始提交时，CodeMate 启用代码管理能力：

- `main` Lane 使用用户原始工作区。
- 非 `main` Lane 使用托管分支和 Worktree。
- 支持查看工作区状态和 diff、stage/unstage、commit。
- 支持手动检查点，也支持成功 Run 后按空闲时间、最大待处理 Run 数或文件数延迟合并检查点。
- 支持从检查点恢复、放弃未保存修改、将 Lane 发布为普通本地分支。
- 集成前提供预览；集成成功后在 `main` Lane 创建代码检查点并记录来源。

自动检查点失败不会改变已经完成的 Agent Run 结果，但会记录诊断告警。

### VSCode 风格工作台

工作台主要区域如下：

| 区域 | 能力 |
|---|---|
| ActivityBar | Explorer、History、Source Control、Search 等视图切换 |
| Explorer | 浏览工作区文件，打开文本文件 |
| Editor | 多标签编辑、修改、保存、版本冲突提示 |
| Source Control | 查看 Lane/Git 状态、diff、暂存、提交和检查点 |
| Search | 搜索文件名和文本内容，跳过常见忽略目录、二进制文件和过大文件 |
| Terminal | 通过 WebSocket 使用当前 Lane 的终端，Windows 优先使用 WSL，失败时回退 PowerShell |
| Conversation | 流式回复、工具卡片、权限请求、子 Agent、错误和记忆预算 |
| File Review | 审查 Agent 修改，单文件或批量接受/拒绝 |

文件编辑由后端校验路径、文本类型、文件大小和 `expected_revision`。后端发现文件已经被外部修改时返回 `409 Conflict`，前端不会直接覆盖。

### 实时通信与状态

CRUD、文件和 Git 查询使用 REST；Agent 运行、文本流、工具调用、权限确认、终端 I/O 和子 Agent 进度使用 WebSocket。

常见 WebSocket 事件包括：

- `run_started`、`run_completed`、`run_error`
- `status_update`、`text_delta`
- `tool_call_start`、`tool_call_end`
- `permission_request`、`permission_resolved`
- `node_added`
- `subagent_started`、`subagent_progress`、`subagent_done`
- `file_review`
- `terminal_output`、`terminal_status`
- `lane_created`、`lane_switched`、`lane_deleted`

WebSocket 断开后，前端会自动重连并重新同步 Session 快照；无法继续的权限等待和终端资源由后端清理。

## 项目目录

```text
CodeMate/
├── backend/                         # Python + FastAPI 后端
│   ├── src/
│   │   ├── agent/                   # Agent 主循环、上下文 Provider、系统提示词
│   │   ├── api/                    # REST、WebSocket、SessionRuntime、终端
│   │   ├── errors/                 # AgentError 和 API 错误类型
│   │   ├── intelligence/           # 自动命名等智能化服务
│   │   ├── llm/                   # Provider、流式事件、重试和工具参数拼接
│   │   ├── memory/                # 上下文预算、压缩和项目记忆
│   │   ├── observability/         # 结构化日志
│   │   ├── permission/            # 权限级别、规则、审计和命令黑名单
│   │   ├── storage/               # Workspace、Session、Lane 和 JSONL 持久化
│   │   ├── tools/                 # 文件、命令、搜索和子 Agent 工具
│   │   └── version_control/       # Git 状态、Worktree、检查点和集成
│   ├── tests/                     # 后端测试
│   ├── main.py                    # FastAPI 应用入口
│   ├── requirements.txt           # Python 依赖
│   └── ...                        # 后端源码与测试
├── web-ui/                        # React + TypeScript + Vite 前端
│   ├── src/
│   │   ├── components/            # SessionPicker、Workspace、对话、工作台和弹窗
│   │   ├── hooks/                 # WebSocket 和交互 Hooks
│   │   ├── store/                 # Zustand 全局状态
│   │   ├── types/                 # 前端协议和业务类型
│   │   └── utils/                 # 树布局等工具
│   ├── package.json               # 前端脚本和依赖
│   ├── package-lock.json          # npm 锁定文件
│   └── vite.config.ts             # 开发代理和构建配置
├── .env.example                   # 根目录环境变量模板
├── workspace/                     # 示例/默认工作区，可按需替换
├── data/                          # 运行时数据，默认不提交版本库
├── local_docs/                    # 本地功能设计、代码设计和草稿
├── docs/                          # 公开文档
├── examples/                     # 示例代码
└── README.md                      # 项目说明
```

## 数据与运行时目录

当前 Workspace → Session 布局的主要数据结构如下：

```text
data/
├── workspaces/
│   ├── registry.json
│   └── {workspace_id}/
│       └── sessions/{session_id}/
│           ├── session.json
│           ├── conversation/entries.jsonl
│           ├── lanes.jsonl
│           ├── git/
│           │   ├── bindings.json
│           │   ├── checkpoints.ndjson
│           │   └── operations.ndjson
│           └── logs/
│               └── {session_id}_agent.jsonl
└── deletions/                     # 删除 Journal
```

`DATA_DIR=data/sessions` 仍作为兼容旧数据的配置入口；新布局的根目录由其父目录推导为 `data/`。旧的扁平 Session 文件不会自动删除，需要通过迁移接口显式预览和执行迁移。

## 部署与运行

### 环境要求

- Python 3.11 或更高版本。
- Node.js 与 npm；建议使用当前 LTS 版本。
- 可访问的 OpenAI 或 DeepSeek 兼容 API，以及对应 API Key。
- 若启用 `web_search`，还需要配置博查或火山引擎/豆包搜索服务。
- 若启用 Git 代码隔离，需要 Git，并且目标仓库至少存在一个初始提交。
- Windows 下终端能力优先使用 WSL；没有 WSL 时回退到 PowerShell。

### 开发环境启动

建议打开两个终端。以下命令从项目根目录执行。

#### 1. 创建 Python 环境并安装后端依赖

PowerShell：

```powershell
py -3.11 -m venv .venv
\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
Set-Location backend
python -m pip install -r requirements.txt
```

macOS/Linux/WSL：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
cp .env.example .env
cd backend
python -m pip install -r requirements.txt
```

编辑根目录 `.env`，至少填写 `LLM_API_KEY`。README 中的启动命令从 `backend/` 目录运行，因此模板中的 `WORKSPACE=../workspace`、`DATA_DIR=../data/sessions` 和 `LOG_DIR=../logs` 均相对于 `backend/` 解析；也可以改成目标代码库的绝对路径。

#### 2. 启动后端

在 `backend/` 目录执行：

```bash
python main.py
```

等价的开发启动命令是：

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

后端地址：

- 服务状态：`http://127.0.0.1:8000/`
- 健康检查：`http://127.0.0.1:8000/health`
- OpenAPI 文档：`http://127.0.0.1:8000/docs`
- WebSocket：`ws://127.0.0.1:8000/ws/{session_id}`

#### 3. 安装并启动前端

在另一个终端执行：

```bash
cd web-ui
npm install
npm run dev
```

打开 `http://localhost:5173`。Vite 开发服务器会把 `/api` 代理到 `http://localhost:8000`，把 `/ws` 代理到 `ws://localhost:8000`。

### 生产构建与部署

当前项目没有把前端静态文件内置到 FastAPI 中。生产部署需要分别运行后端，并用静态文件服务器托管 `web-ui/dist`，同时把 `/api` 和 `/ws` 反向代理到后端。

#### 1. 构建前端

```bash
cd web-ui
npm ci
npm run build
```

构建产物位于 `web-ui/dist/`。构建脚本会先执行 TypeScript 检查，再执行 Vite 构建。

#### 2. 运行后端

在生产环境中使用独立进程管理器启动，不要使用 `--reload`：

```bash
cd backend
..\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Linux/WSL 使用：

```bash
cd backend
../.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

生产环境应设置 `DEBUG=false`，限制 `CORS_ORIGINS` 为实际前端来源，并把 `WORKSPACE`、`DATA_DIR`、`LOG_DIR` 和 `CODEMATE_WORKTREE_ROOT` 配置为明确的持久化路径。

#### 3. 配置反向代理

以 Nginx 为例，关键路由需要同时支持 HTTP 和 WebSocket：

```nginx
server {
    listen 80;
    server_name your-host.example;

    root /opt/codemate/web-ui/dist;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

反向代理与前端使用同源地址时，不需要在前端代码中硬编码后端地址；WebSocket 会根据页面协议自动选择 `ws://` 或 `wss://`。

### 配置说明

配置从根目录 `.env` 和进程环境变量加载。相对路径相对于后端进程的当前工作目录解析，部署时建议使用绝对路径；按本文命令从 `backend/` 启动时，优先使用根目录模板中的路径。

#### LLM

```dotenv
LLM_PROVIDER=deepseek
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=2000
LLM_MAX_RETRIES=3
```

使用 OpenAI 或兼容网关时，将 `LLM_PROVIDER` 改为 `openai`，并相应设置 `LLM_BASE_URL` 和 `LLM_MODEL`。

#### 搜索服务

```dotenv
WEB_SEARCH_PROVIDER=bocha
BOCHA_API_KEY=your_bocha_api_key_here
BOCHA_BASE_URL=https://api.bochaai.com
```

切换火山引擎/豆包 Global 搜索：

```dotenv
WEB_SEARCH_PROVIDER=volcengine
VOLCENGINE_SEARCH_API_KEY=your_search_api_key_here
VOLCENGINE_SEARCH_ENDPOINT=https://open.feedcoopapi.com/search_api/global_search
VOLCENGINE_SEARCH_MAX_SNIPPET_LENGTH=1000
VOLCENGINE_SEARCH_ICP_HOST_ONLY=false
```

#### 工作区、数据和运行参数

```dotenv
WORKSPACE=../workspace
DATA_DIR=../data/sessions
LOG_DIR=../logs
CODEMATE_WORKTREE_ROOT=
MAX_ITERATIONS=20
MAX_CONTEXT_TOKENS=8000
CONTEXT_RESERVE_TOKENS=2000
COMPACTION_KEEP_RECENT_TOKENS=3000
COMPACTION_SUMMARY_MAX_TOKENS=1200
COMPACTION_THRESHOLD_RATIO=0.8
CHECKPOINT_MAX_FILE_BYTES=10485760
CHECKPOINT_FREQUENCY_MODE=balanced
CHECKPOINT_MERGE_WINDOW_SECONDS=300
CHECKPOINT_MAX_PENDING_RUNS=10
CHECKPOINT_MAX_PENDING_FILES=20
CHECKPOINT_MAX_PENDING_SECONDS=1800
```

#### 服务和安全

```dotenv
HOST=127.0.0.1
PORT=8000
DEBUG=false
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
COMMAND_BLACKLIST=rm,mkfs,format,dd,git push,git reset --hard
```

`COMMAND_BLACKLIST` 是额外的命令拒绝规则，不会替代危险命令识别、命令替换检查和工作区路径检查。

## API 概览

REST 前缀为 `/api`，主要接口按职责分组：

| 分组 | 典型接口 |
|---|---|
| Workspace | `GET/POST /api/workspaces`、`PATCH /api/workspaces/{id}`、`DELETE /api/workspaces/{id}` |
| Session | `GET/POST /api/sessions`、`GET/PATCH/DELETE /api/sessions/{id}` |
| 上下文 | `POST /api/sessions/{id}/compact` |
| 文件 | `GET /workspace/files`、`GET/POST /workspace/file`、`GET /workspace/search` |
| 文件审查 | `POST /file-reviews/{review_id}/accept`、`reject`、`accept-all`、`reject-all` |
| Lane | `GET/POST /lanes`、`POST /lanes/{lane}/switch`、`compare`、`archive`、`restore-lane` |
| Git | `status`、`diff`、`stage`、`unstage`、`commit`、`checkpoint`、`restore`、`discard`、`publish`、`integrate` |
| 权限 | `/permissions/audit`、`/permissions/gate` |
| 迁移 | `/api/storage/legacy-migration` |

完整请求和响应模型以运行中的 OpenAPI 页面为准：`http://127.0.0.1:8000/docs`。

## 开发与验证

后端：

```bash
cd backend
pytest
```

前端：

```bash
cd web-ui
npm test
npm run build
```

只运行前端测试但不进入 watch 模式时使用 `npm test`；需要交互式 watch 模式时使用 `npm run test:watch`。

## 设计文档

当前实现对应的中文设计文档位于 `local_docs/功能设计/`：

- [功能设计首页](local_docs/功能设计/00-首页.md)
- [系统架构概览](local_docs/功能设计/01-系统架构概览.md)
- [工作区与会话管理](local_docs/功能设计/02-数据与存储层/01-工作区与会话管理.md)
- [树形对话历史系统](local_docs/功能设计/02-数据与存储层/02-树形对话历史系统.md)
- [Lane 分支管理系统](local_docs/功能设计/02-数据与存储层/03-Lane分支管理系统.md)
- [Lane 与 Git 融合分支管理](local_docs/功能设计/02-数据与存储层/16-Lane与Git融合分支管理方案.md)
- [Agent 主循环](local_docs/功能设计/03-Agent核心层/04-Agent主循环.md)
- [LLM 接口层](local_docs/功能设计/03-Agent核心层/06-LLM接口层.md)
- [子 Agent 系统](local_docs/功能设计/03-Agent核心层/15-子Agent系统.md)
- [VSCode 风格会话工作台](local_docs/功能设计/05-Web-UI层/08-VSCode风格会话工作台.md)
- [日志与可观测性](local_docs/功能设计/04-支撑模块/11-日志与可观测性.md)

`local_docs/草稿/` 用于保留尚未正式落地的方案和过程记录；已经实现的功能应优先维护 `local_docs/功能设计/` 中的正式文档。

## 当前范围与限制

当前版本明确聚焦本地单用户开发工作流，暂不提供：

- 远程协作和多租户隔离。
- 远程 Git push 和远程仓库管理。
- 完整 IDE 语言服务、调试器和编译任务编排。
- Docker/容器级沙箱。
- 独立日志检索 UI、跨 Session 日志聚合和日志轮转。
- 复杂 Git 历史改写和自动冲突解决。

如需扩展这些能力，请先同步更新对应的功能设计和通信/存储边界。
