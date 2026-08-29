# CodeMate Frontend

基于 React + TypeScript + Vite 的 CodeMate 前端应用。

## 技术栈

- **框架**: React 18 + TypeScript
- **构建工具**: Vite
- **状态管理**: Zustand
- **树形可视化**: React Flow + dagre
- **样式**: Tailwind CSS
- **图标**: Lucide React
- **通信**: WebSocket (原生 API)

## 快速开始

### 1. 安装依赖

```bash
npm install
```

### 2. 启动开发服务器

```bash
npm run dev
```

前端将在 http://localhost:5173 启动。

### 3. 确保后端运行

后端需要在 http://localhost:8000 运行，前端会连接：
- REST API: `http://localhost:8000/api`
- WebSocket: `ws://localhost:8000/ws/{session_id}`

### 4. 构建生产版本

```bash
npm run build
```

构建产物在 `dist/` 目录。

## 项目结构

```
frontend/
├── src/
│   ├── components/         # React 组件
│   │   ├── tree/          # 树形画布组件
│   │   ├── conversation/  # 对话面板组件
│   │   ├── toolbar/       # 工具栏组件
│   │   └── modals/        # 模态框组件
│   ├── store/             # Zustand 状态管理
│   ├── hooks/             # 自定义 Hooks
│   ├── types/             # TypeScript 类型定义
│   ├── utils/             # 工具函数
│   ├── App.tsx            # 主应用组件
│   ├── main.tsx           # 入口文件
│   └── index.css          # 全局样式
├── public/                # 静态资源
├── index.html             # HTML 模板
├── package.json
├── tsconfig.json
├── vite.config.ts
└── tailwind.config.js
```

## 核心功能

### 1. 会话管理
- 会话选择页：列出已有会话，创建新会话
- 自动加载会话数据并建立 WebSocket 连接

### 2. 树形可视化
- 使用 React Flow 渲染树形对话历史
- 支持拖拽、缩放、自动布局
- 高亮当前 Lane 的路径
- 节点类型：user / assistant / tool / 子 Agent

### 3. 对话面板
- 流式消息显示（逐字追加）
- 工具调用卡片（可展开查看详情）
- 子 Agent 执行卡片（显示进度）
- 实时输入框（支持多行）

### 4. Lane 分支管理
- 创建分支（即时校验命名规则）
- 切换分支
- 对比两个分支（抽屉视图）

### 5. 权限确认
- 弹窗确认高风险操作
- 显示风险级别和警告信息
- 三种响应：拒绝 / 本次允许 / 总是允许

### 6. 实时状态
- Agent 状态徽标（7 种状态）
- Toast 通知（成功/错误/警告/信息）
- WebSocket 连接状态监控

## WebSocket 事件

前端监听的主要事件：

- `node_added` - 树上新增节点
- `text_delta` - 流式文字追加
- `message_start` / `message_end` - 消息边界
- `tool_call_start` / `tool_call_end` - 工具执行
- `subagent_started` / `subagent_progress` / `subagent_done` - 子 Agent
- `status_update` - Agent 状态变化
- `permission_request` - 权限请求
- `lane_created` / `lane_switched` / `lane_deleted` - Lane 操作

前端发送的事件：

- `send_message` - 发送用户消息
- `permission_response` - 权限响应

## 开发注意事项

### 1. 颜色使用规则
- Lane 分类色：blue / orange / aqua / yellow（按创建顺序分配）
- 状态色：pending / success / warning / error
- 角色不占用颜色通道，用图标区分

### 2. 路径高亮逻辑
- 从 Lane 的 `leaf_id` 沿 `parent` 向上走到根
- 高亮节点边框和连线
- 不使用 `Entry.lane` 字段判断路径

### 3. 性能优化
- `text_delta` 用 requestAnimationFrame 节流
- 树布局用增量更新（避免全量重排）
- 长内容自动截断（超过 500 行）

### 4. 响应式设计
- 桌面端主要形态：左右分屏
- 移动端适配为 P2 优先级（首版不做）

## 故障排查

### WebSocket 连接失败
- 检查后端是否在 http://localhost:8000 运行
- 检查浏览器控制台的错误信息
- 确认 CORS 配置正确

### 树形图不显示
- 检查是否有 entries 数据
- 查看控制台是否有 dagre 布局错误
- 确认 React Flow 的 CSS 已加载

### 流式文字不追加
- 检查 WebSocket 连接状态
- 确认 `text_delta` 事件的 `message_id` 匹配
- 查看 store 中的 messages 数组

## License

MIT
