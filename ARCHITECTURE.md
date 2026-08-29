# CodeMate 项目架构

## 目录结构

```
CodeMate/
│
├── backend/                          # 后端服务（Python + FastAPI）
│   ├── src/
│   │   ├── agent/                   # Agent 主循环
│   │   │   ├── loop.py             # 核心执行循环
│   │   │   ├── providers.py        # MessageProvider 抽象
│   │   │   ├── state.py            # 运行状态
│   │   │   └── prompts.py          # 系统提示词
│   │   │
│   │   ├── storage/                 # 树形历史存储
│   │   │   ├── session_storage.py  # Entry 树管理
│   │   │   ├── lane_manager.py     # Lane 指针管理
│   │   │   └── models.py           # 数据模型
│   │   │
│   │   ├── llm/                     # LLM 接口层
│   │   │   ├── client.py           # 统一客户端 + 重试
│   │   │   ├── providers.py        # OpenAI/DeepSeek Provider
│   │   │   └── events.py           # 流式事件定义
│   │   │
│   │   ├── tools/                   # 工具系统
│   │   │   ├── registry.py         # 工具注册表
│   │   │   ├── base.py             # Tool 基类
│   │   │   ├── file_tools.py       # 文件操作工具
│   │   │   ├── exec_tool.py        # 命令执行工具
│   │   │   ├── search_tools.py     # 搜索工具
│   │   │   └── subagent_tool.py    # 子 Agent 工具
│   │   │
│   │   ├── permission/              # 权限控制
│   │   │   ├── manager.py          # 权限管理器
│   │   │   └── rules.py            # 安全规则
│   │   │
│   │   ├── api/                     # Web API 层
│   │   │   ├── routes.py           # REST 路由
│   │   │   ├── ws.py               # WebSocket 端点
│   │   │   ├── schemas.py          # 请求/响应模型
│   │   │   └── session_service.py  # Session 管理
│   │   │
│   │   ├── errors/                  # 错误类型
│   │   ├── observability/           # 日志系统
│   │   └── config.py               # 配置加载
│   │
│   ├── tests/                       # 测试
│   ├── data/sessions/              # 运行时数据（JSONL）
│   ├── logs/                        # 日志文件
│   ├── main.py                      # FastAPI 应用入口
│   └── requirements.txt             # Python 依赖
│
├── frontend/                         # 前端应用（React + TypeScript）
│   ├── src/
│   │   ├── components/             # React 组件
│   │   │   ├── tree/              # 树形画布
│   │   │   │   ├── TreeCanvas.tsx
│   │   │   │   └── TreeNode.tsx
│   │   │   ├── conversation/      # 对话面板
│   │   │   │   ├── ConversationPanel.tsx
│   │   │   │   ├── MessageBubble.tsx
│   │   │   │   └── ToolCallCard.tsx
│   │   │   ├── toolbar/           # 工具栏
│   │   │   │   ├── Toolbar.tsx
│   │   │   │   └── AgentStatusBadge.tsx
│   │   │   ├── modals/            # 模态框
│   │   │   │   ├── CreateLaneModal.tsx
│   │   │   │   ├── PermissionModal.tsx
│   │   │   │   └── CompareDrawer.tsx
│   │   │   ├── Workspace.tsx      # 工作台主组件
│   │   │   ├── SessionPicker.tsx  # 会话选择
│   │   │   └── ToastContainer.tsx # Toast 通知
│   │   │
│   │   ├── store/                  # 状态管理
│   │   │   └── index.ts           # Zustand store
│   │   │
│   │   ├── hooks/                  # 自定义 Hooks
│   │   │   └── useWebSocket.ts    # WebSocket 连接
│   │   │
│   │   ├── types/                  # TypeScript 类型
│   │   │   └── index.ts           # 类型定义
│   │   │
│   │   ├── utils/                  # 工具函数
│   │   │   └── helpers.ts
│   │   │
│   │   ├── App.tsx                 # 主应用组件
│   │   ├── main.tsx                # 入口文件
│   │   └── index.css               # 全局样式
│   │
│   ├── public/                      # 静态资源
│   ├── package.json                # Node 依赖
│   ├── vite.config.ts              # Vite 配置
│   ├── tailwind.config.js          # Tailwind 配置
│   └── README.md                    # 前端文档
│
├── local_docs/                      # 设计文档（中文）
│   ├── 功能设计/
│   │   ├── 00-首页.md
│   │   ├── 01-系统架构概览.md
│   │   ├── 02-数据与存储层/
│   │   ├── 03-Agent核心层/
│   │   ├── 04-支撑模块/
│   │   ├── 05-Web-UI层/
│   │   │   └── 07-Web-UI设计.md    # 前端详细设计
│   │   └── 06-项目管理/
│   ├── 代码设计/
│   └── 草稿/
│
├── docs/                            # 公开文档
├── examples/                        # 示例代码
├── .gitignore
├── .env.example                     # 环境变量模板
└── README.md                        # 项目总览
```

## 数据流图

```
┌─────────────────────────────────────────────────────────────┐
│                        用户浏览器                            │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                     React 前端                       │   │
│  │  - TreeCanvas (React Flow)                         │   │
│  │  - ConversationPanel                               │   │
│  │  - Zustand Store                                   │   │
│  └────────────┬────────────────────────────┬───────────┘   │
│               │                            │                │
└───────────────┼────────────────────────────┼────────────────┘
                │ REST API                   │ WebSocket
                │ (CRUD)                     │ (实时事件)
                ▼                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI 后端                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                   API 层                             │   │
│  │  - routes.py (REST)                                 │   │
│  │  - ws.py (WebSocket)                                │   │
│  │  - session_service.py (Session 管理)               │   │
│  └────────────┬───────────────────────┬──────────────────┘   │
│               │                       │                      │
│               ▼                       ▼                      │
│  ┌─────────────────────┐  ┌─────────────────────┐          │
│  │   Agent 主循环       │  │   存储层             │          │
│  │  - loop.py          │──│  - SessionStorage   │          │
│  │  - providers.py     │  │  - LaneManager      │          │
│  │  - state.py         │  │  - models.py        │          │
│  └──────┬──────────────┘  └─────────┬───────────┘          │
│         │                           │                       │
│         ▼                           ▼                       │
│  ┌─────────────────┐        ┌──────────────┐              │
│  │  工具系统        │        │  JSONL 文件   │              │
│  │  - file_tools   │        │  *.jsonl      │              │
│  │  - exec_tool    │        │  *_lanes.jsonl│              │
│  │  - search_tools │        └──────────────┘              │
│  │  - subagent_tool│                                       │
│  └────────┬────────┘                                       │
│           │                                                 │
│           ▼                                                 │
│  ┌─────────────────┐                                       │
│  │  权限控制        │                                       │
│  │  - manager.py   │                                       │
│  │  - rules.py     │                                       │
│  └────────┬────────┘                                       │
│           │                                                 │
└───────────┼─────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│                      LLM API                                 │
│  - OpenAI API (gpt-4, gpt-3.5-turbo)                       │
│  - DeepSeek API (deepseek-chat)                            │
└─────────────────────────────────────────────────────────────┘
```

## 核心概念

### 1. Entry 树（树形对话历史）
```
每条消息是一个 Entry 节点：
- id: 唯一标识
- parent: 父节点 ID（构成树结构）
- lane: 归属分支（静态标签）
- role: user / assistant / tool
- content: 消息内容
```

### 2. Lane 指针（分支管理）
```
Lane 是指向树中某个叶子节点的指针：
- lane: 分支名称
- leaf_id: 指向的叶子节点 ID
- 多个 Lane 可以共享公共祖先段
```

### 3. 消息流转
```
用户输入
  ↓
Agent 主循环
  ↓
调用 LLM（流式响应）
  ↓
解析工具调用请求
  ↓
权限检查
  ↓
执行工具（或启动子 Agent）
  ↓
工具结果 → 下一轮
  ↓
最终响应
```

## 技术选型理由

| 组件 | 选型 | 理由 |
|------|------|------|
| 后端框架 | FastAPI | 原生 async/await、自动 API 文档、WebSocket 支持 |
| 存储 | JSONL | 追加式、易调试、无需数据库、版本控制友好 |
| 前端框架 | React 18 | 生态成熟、组件化、Hooks API |
| 构建工具 | Vite | 快速冷启动、HMR、原生 ESM |
| 状态管理 | Zustand | 轻量、无样板代码、TypeScript 友好 |
| 可视化 | React Flow | 开箱即用的拖拽/缩放、自动布局 |
| 样式 | Tailwind CSS | 原子化、无运行时、配置灵活 |
| 通信 | WebSocket | 双向实时通信、流式推送 |

## 开发流程

### 启动顺序
1. **后端**：`cd backend && python main.py`
2. **前端**：`cd frontend && npm run dev`
3. **浏览器**：访问 http://localhost:5173

### 典型开发任务
- **添加新工具**：在 `backend/src/tools/` 下创建新工具类
- **添加新组件**：在 `frontend/src/components/` 下创建新组件
- **修改 API**：更新 `backend/src/api/routes.py` 和前端类型定义
- **调整样式**：修改 `frontend/tailwind.config.js` 或组件内的 className

## 部署建议

### 后端部署
```bash
# 使用 uvicorn + gunicorn
gunicorn backend.main:app -w 4 -k uvicorn.workers.UvicornWorker
```

### 前端部署
```bash
# 构建静态文件
cd frontend && npm run build

# 使用 nginx 或其他静态服务器托管 dist/
```

### Docker 部署
```dockerfile
# 多阶段构建
FROM node:18 AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.11
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./backend/
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
CMD ["python", "backend/main.py"]
```
