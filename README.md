# CodeMate

一个支持树形对话历史和 Lane 分支管理的编程智能体。

## 项目结构

```
CodeMate/
├── backend/                 # 后端（Python + FastAPI）
│   ├── src/                # 源代码
│   │   ├── agent/         # Agent 主循环
│   │   ├── storage/       # 树形历史存储
│   │   ├── llm/           # LLM 接口层
│   │   ├── tools/         # 工具系统
│   │   ├── permission/    # 权限控制
│   │   ├── api/           # Web API 层
│   │   ├── errors/        # 错误类型
│   │   ├── observability/ # 日志系统
│   │   └── config.py      # 配置加载
│   ├── tests/             # 测试
│   ├── main.py            # FastAPI 应用入口
│   └── requirements.txt   # Python 依赖
│
├── web-ui/                 # 前端（React + TypeScript）
│   ├── src/               # 源代码
│   │   ├── components/   # React 组件
│   │   ├── store/        # 状态管理
│   │   ├── hooks/        # 自定义 Hooks
│   │   ├── types/        # TypeScript 类型
│   │   └── utils/        # 工具函数
│   ├── public/           # 静态资源
│   ├── package.json      # Node 依赖
│   └── vite.config.ts    # Vite 配置
│
├── local_docs/            # 设计文档
│   ├── 功能设计/          # 功能设计文档
│   ├── 代码设计/          # 代码设计文档
│   └── 草稿/             # 草稿和笔记
│
├── docs/                  # 公开文档
├── examples/              # 示例代码
├── .env.example          # 环境变量模板
└── README.md             # 本文件
```

## 快速开始

### 1. 后端启动

```bash
# 进入后端目录
cd backend

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入你的 API Key

# 启动后端
python main.py
```

后端将在 http://localhost:8000 启动。

访问 http://localhost:8000/docs 查看 API 文档。

### 2. 前端启动

```bash
# 进入前端目录
cd web-ui

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端将在 http://localhost:5173 启动。

## 核心功能

### 1. 树形对话历史
每条消息是树中的一个节点，支持分叉和回溯：
- 左侧树形可视化展示对话结构
- 右侧对话面板显示当前路径内容
- 点击节点可以查看详情和切换路径

### 2. Lane 分支管理
类似 Git 分支，可以同时探索多个方案：
- 创建分支：从任意节点开始新的探索方向
- 切换分支：在不同方案之间快速切换
- 对比分支：左右双栏对比两个方案的差异

### 3. 六个核心工具
- `read_file` - 读取文件内容
- `write_file` - 写入文件
- `edit_file` - 精确编辑文件
- `bash` - 执行 shell 命令
- `glob` - 文件搜索
- `grep` - 内容搜索

### 4. 三级权限控制与工具门禁
- **SAFE**（自动放行）：只读操作
- **WRITE**（workspace 内自动放行）：工作目录内的写操作
- **DANGEROUS**（需用户确认）：危险操作或 workspace 外的修改
- 命令工具支持 session 级白名单；白名单命令仍会先经过危险模式、命令替换和 workspace 路径安全检查

### 5. 子 Agent 系统
将子任务委托给独立上下文的只读 Agent：
- 子 Agent 使用只读工具，不会修改代码
- 内部步骤不污染父 Agent 的对话树
- 返回精简的结论和详细的执行信息

### 6. 实时状态可观测
- Agent 状态徽标显示当前执行阶段
- 工具调用卡片显示执行进度和结果
- 子 Agent 卡片显示步数和实时进度
- Toast 通知提示重要事件

## 技术栈

### 后端
- **框架**: Python 3.11+, FastAPI
- **通信**: WebSocket（实时事件推送）
- **存储**: JSONL（追加式文件存储）
- **LLM**: OpenAI API / DeepSeek API

### 前端
- **框架**: React 18 + TypeScript
- **构建工具**: Vite
- **状态管理**: Zustand
- **可视化**: React Flow + dagre
- **样式**: Tailwind CSS
- **图标**: Lucide React

## API 端点

### REST API
- `POST /api/sessions` - 创建会话
- `GET /api/sessions` - 列出所有会话
- `GET /api/sessions/{id}` - 获取会话快照
- `DELETE /api/sessions/{id}` - 删除会话
- `GET /api/sessions/{id}/lanes` - 列出分支
- `POST /api/sessions/{id}/lanes` - 创建分支
- `POST /api/sessions/{id}/lanes/{lane}/switch` - 切换分支
- `DELETE /api/sessions/{id}/lanes/{lane}` - 删除分支
- `GET /api/sessions/{id}/lanes/compare` - 对比分支
- `GET /api/sessions/{id}/permissions/gate` - 查看命令工具门禁
- `PUT /api/sessions/{id}/permissions/gate` - 更新命令白名单

### WebSocket
- `ws://localhost:8000/ws/{session_id}` - 实时事件推送

主要事件：
- `node_added` - 树上新增节点
- `text_delta` - 流式文字追加
- `tool_call_start` / `tool_call_end` - 工具执行
- `subagent_started` / `subagent_progress` / `subagent_done` - 子 Agent
- `status_update` - Agent 状态变化
- `permission_request` - 权限请求
- `lane_created` / `lane_switched` / `lane_deleted` - Lane 操作

## 开发

### 运行测试（后端）
```bash
cd backend
pytest
```

### 代码格式化（后端）
```bash
cd backend
black src/ tests/
```

### 类型检查（后端）
```bash
cd backend
mypy src/
```

### 构建前端
```bash
cd web-ui
npm run build
```

## 设计文档

详细的系统设计和实现细节见 `local_docs/` 目录：

- [功能设计/00-首页.md](local_docs/功能设计/00-首页.md) - 项目概述和文档导航
- [功能设计/01-系统架构概览.md](local_docs/功能设计/01-系统架构概览.md) - 整体架构
- [功能设计/02-数据与存储层/02-树形对话历史系统.md](local_docs/功能设计/02-数据与存储层/02-树形对话历史系统.md) - 核心差异化功能
- [功能设计/05-Web-UI层/07-Web-UI设计.md](local_docs/功能设计/05-Web-UI层/07-Web-UI设计.md) - 前端设计完整文档
- [代码设计/00-总览与目录结构.md](local_docs/代码设计/00-总览与目录结构.md) - 代码组织

## 配置

### 环境变量（.env）
```bash
# LLM Provider
LLM_PROVIDER=openai  # 或 deepseek
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# 应用配置
WORKSPACE=./workspace
DATA_DIR=./data/sessions
LOG_DIR=./logs
MAX_ITERATIONS=15
MAX_CONTEXT_TOKENS=8000
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
COMMAND_ALLOWLIST=pwd,ls,cat,head,tail,grep,find,git status,git diff

# 服务器配置
HOST=0.0.0.0
PORT=8000
DEBUG=true
```

## 数据存储

运行时数据存储在 `backend/data/sessions/` 目录：
- `{session_id}.jsonl` - 会话的 Entry 树
- `{session_id}_lanes.jsonl` - 会话的 Lane 指针

日志存储在 `backend/logs/` 目录：
- `agent.jsonl` - 结构化日志

## 故障排查

### 后端启动失败
- 检查 Python 版本（需要 3.11+）
- 确认已安装所有依赖：`pip install -r backend/requirements.txt`
- 检查 `.env` 文件配置是否正确

### 前端连接失败
- 确认后端在 http://localhost:8000 运行
- 检查浏览器控制台的错误信息
- 确认 CORS 配置正确（已在 `main.py` 中配置）

### WebSocket 连接断开
- 检查网络连接
- 查看后端日志中的错误信息
- 前端会自动重连（3秒间隔）

## License

MIT

## 贡献

欢迎提交 Issue 和 Pull Request！

## 联系方式

项目地址：[GitHub仓库地址]
